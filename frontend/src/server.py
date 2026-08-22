"""FastAPI server: scene composer + mflux job API + static UI."""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.catalog_loader import default_scene, engine_defaults, load_schema, reload_catalogs
from src.composer import compose_prompt, scene_tags
from src.constraints import apply_edit_preset, blocked_options, sanitize_scene
from src.system_prompts import SYSTEM_EDIT, SYSTEM_GEN
from src.engine import engine
from src.imageutil import MAX_IMAGE_BYTES, sniffed_image_suffix
from src.jobs import Job, jobs
from src.lora_match import list_catalog, match_loras
from src.models import ComposeRequest, ComposeResponse, GenerateRequest, JobResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

FRONTEND_ROOT = Path(os.environ.get("STUDIO_ROOT", Path(__file__).resolve().parent.parent))
DATA_HOME = Path(os.environ.get("STUDIO_DATA_HOME", "/opt/ivoai"))
WEB_DIR = FRONTEND_ROOT / "web"

# Container-local only. Not bind-mounted to the host.
OUTPUTS_DIR = Path(os.environ.get("STUDIO_OUTPUTS_DIR", "/data/outputs"))
UPLOADS_DIR = Path(os.environ.get("STUDIO_UPLOADS_DIR", "/data/uploads"))

for d in (OUTPUTS_DIR, UPLOADS_DIR):
    d.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Local Apple Studio", version="0.2.0")


def _job_response(job: Job) -> JobResponse:
    return JobResponse(
        id=job.id,
        status=job.status.value,
        progress=job.progress,
        message=job.message,
        step=job.step,
        steps=job.steps,
        error=job.error,
        result=job.result,
    )


def _compose(req: ComposeRequest) -> ComposeResponse:
    mode = (req.mode or "gen").strip().lower()
    if mode not in {"gen", "edit"}:
        mode = "gen"
    scene = {**default_scene(mode), **(req.scene or {})}
    # deep-merge top-level groups if partial
    base = default_scene(mode)
    for k, v in (req.scene or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = {**base[k], **v}
        else:
            base[k] = v
    scene = base

    winner = (req.winner or "").strip() or None
    if mode == "edit" and winner == "preset.scene":
        preset_id = (scene.get("preset") or {}).get("scene")
        scene = apply_edit_preset(scene, preset_id)

    scene, dropped = sanitize_scene(scene, winner=winner, mode=mode)

    matched = match_loras(
        scene,
        on_disk=set(engine.list_lora_files()),
        max_loras=req.max_loras,
        manual=[m.model_dump() for m in req.manual_loras],
    )
    triggers: list[str] = []
    if req.include_triggers:
        for m in matched:
            triggers.extend(m.triggers)

    prompt = compose_prompt(
        scene,
        extra_triggers=triggers if req.include_triggers else None,
        raw_override=req.raw_prompt,
        mode=mode,
    )
    return ComposeResponse(
        prompt=prompt,
        tags=sorted(scene_tags(scene)),
        loras=[m.to_dict() for m in matched],
        scene=scene,
        dropped=dropped,
        blocked=blocked_options(scene),
    )


@app.get("/api/health")
def health() -> dict[str, Any]:
    eng = engine.status()
    return {
        "ok": True,
        "engine": eng,
        "outputs_dir": str(OUTPUTS_DIR),
        "uploads_dir": str(UPLOADS_DIR),
    }


@app.get("/api/schema")
def api_schema(mode: str = "gen") -> dict[str, Any]:
    return load_schema(mode)


@app.get("/api/defaults")
def api_defaults(mode: str = "gen") -> dict[str, Any]:
    return {
        "scene": default_scene(mode),
        "engine": engine_defaults(mode),
        "system_prompts": {"gen": SYSTEM_GEN, "edit": SYSTEM_EDIT},
        "mode": "edit" if (mode or "").strip().lower() == "edit" else "gen",
    }


@app.get("/api/loras")
def api_loras() -> list[dict[str, Any]]:
    return list_catalog(on_disk=set(engine.list_lora_files()))


@app.post("/api/compose", response_model=ComposeResponse)
def api_compose(req: ComposeRequest) -> ComposeResponse:
    return _compose(req)


@app.post("/api/generate", response_model=JobResponse)
def api_generate(req: GenerateRequest) -> JobResponse:
    composed = _compose(
        ComposeRequest(
            scene=req.scene,
            raw_prompt=req.raw_prompt or req.prompt,
            manual_loras=req.manual_loras,
            mode=req.mode,
            max_loras=req.max_loras,
            include_triggers=req.include_triggers,
            winner=req.winner,
        )
    )
    prompt = (req.prompt or composed.prompt or "").strip()
    if not prompt:
        raise HTTPException(400, "Prompt is empty")

    mode = (req.mode or "gen").strip().lower()
    if mode not in {"gen", "edit"}:
        raise HTTPException(400, "mode must be gen or edit")
    defaults = engine_defaults(mode)

    # Basename-only LoRA list (shared mounts / remote backend)
    lora_meta: list[dict[str, Any]] = []
    for m in composed.loras:
        if not m.get("available"):
            continue
        file_name = m.get("file") or (Path(m["path"]).name if m.get("path") else "")
        if not file_name:
            continue
        lora_meta.append(
            {
                "id": m.get("id"),
                "name": m.get("name"),
                "file": Path(file_name).name,
                "scale": float(m.get("scale") or 0.8),
            }
        )

    ref_images: list[str] = []
    if mode == "edit" and not req.image_paths:
        raise HTTPException(400, "Edit mode requires a source image")
    for p in req.image_paths or []:
        name = Path(p).name
        path = UPLOADS_DIR / name
        if not path.is_file():
            raise HTTPException(400, f"Image not found: {name}")
        ref_images.append(name)

    job = jobs.submit(
        {
            "prompt": prompt,
            "width": req.width or defaults.get("width", 1024),
            "height": req.height or defaults.get("height", 576),
            "steps": req.steps or defaults.get("steps", 4),
            "seed": req.seed if req.seed is not None else defaults.get("seed"),
            "quantize": req.quantize or defaults.get("quantize", 8),
            "loras": lora_meta,
            "ref_images": ref_images,
            "mode": mode,
            "image_strength": req.image_strength,
            "guidance": req.guidance if req.guidance is not None else defaults.get("guidance"),
            "scene": composed.scene,
        }
    )
    return _job_response(job)


@app.get("/api/jobs/{job_id}", response_model=JobResponse)
def api_job(job_id: str) -> JobResponse:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return _job_response(job)


@app.get("/api/jobs")
def api_jobs(limit: int = 30) -> list[dict[str, Any]]:
    return [_job_response(j).model_dump() for j in jobs.list_recent(limit)]


@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...)) -> dict[str, str]:
    header = await file.read(16)
    suffix = sniffed_image_suffix(header)
    if not suffix:
        raise HTTPException(400, "Only PNG, JPEG, and WebP images are allowed")

    dest = UPLOADS_DIR / f"upload-{uuid.uuid4().hex}{suffix}"
    written = len(header)
    try:
        with dest.open("wb") as out:
            out.write(header)
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_IMAGE_BYTES:
                    raise HTTPException(413, f"Upload exceeds {MAX_IMAGE_BYTES} bytes")
                out.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    return {"filename": dest.name, "url": f"/uploads/{dest.name}"}


@app.post("/api/reload-catalog")
def api_reload() -> dict[str, str]:
    reload_catalogs()
    return {"status": "reloaded"}


@app.post("/api/engine/unload")
def api_unload() -> dict[str, Any]:
    try:
        engine.unload()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Unload failed: {e}") from e
    return engine.status()


def _file_in(root: Path, name: str) -> Path:
    """Serve only a basename that resolves inside root."""
    base = Path(name).name
    if not base or base in {".", ".."}:
        raise HTTPException(404)
    root_r = root.resolve()
    path = (root_r / base).resolve()
    if not path.is_relative_to(root_r) or not path.is_file():
        raise HTTPException(404)
    return path


@app.get("/outputs/{name}")
def get_output(name: str) -> FileResponse:
    return FileResponse(_file_in(OUTPUTS_DIR, name))


@app.get("/uploads/{name}")
def get_upload(name: str) -> FileResponse:
    return FileResponse(_file_in(UPLOADS_DIR, name))


# Static UI last so API routes take precedence
if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


def main() -> None:
    import uvicorn

    uvicorn.run("src.server:app", host="127.0.0.1", port=8080, reload=False)


if __name__ == "__main__":
    main()
