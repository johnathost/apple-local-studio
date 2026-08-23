#!/usr/bin/env python3
"""Backend mflux server (Metal). Loopback HTTP for the frontend container.

Binds 127.0.0.1:8090 by default. LoRA weights live on the host.
Reference images and generated PNGs travel over HTTP (no shared mounts).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import queue
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Iterator

import hmac

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse


def _code_root() -> Path:
    """Directory that contains the `src` package."""
    if env := os.environ.get("STUDIO_FRONTEND"):
        return Path(env)
    parent = Path(__file__).resolve().parent.parent
    if (parent / "src" / "mflux_backend.py").is_file():
        return parent  # deployed: /opt/ivoai/studio
    frontend = parent / "frontend"
    if (frontend / "src" / "mflux_backend.py").is_file():
        return frontend  # repo checkout
    return parent


CODE_ROOT = _code_root()
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from src.imageutil import MAX_IMAGE_BYTES, MAX_REF_IMAGES, sniffed_image_suffix  # noqa: E402
from src.mflux_backend import MfluxBackendError, backend, last_progress  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] backend: %(message)s",
)
logger = logging.getLogger("backend")

DATA_HOME = Path(os.environ.get("STUDIO_DATA_HOME", "/opt/ivoai"))
LORA_DIR = Path(os.environ.get("STUDIO_LORA_DIR", DATA_HOME / "lora"))
TMP_DIR = Path(os.environ.get("STUDIO_TMP_DIR") or os.environ.get("TMPDIR") or (DATA_HOME / "tmp"))
LORA_DIR.mkdir(parents=True, exist_ok=True)
TMP_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Local Apple Studio backend", version="0.2.0")
BACKEND_SECRET = os.environ.get("STUDIO_BACKEND_SECRET") or ""


@app.middleware("http")
async def require_backend_secret(request: Request, call_next):  # type: ignore[no-untyped-def]
    if not BACKEND_SECRET:
        return JSONResponse({"detail": "Backend secret is not configured"}, status_code=503)
    token = request.headers.get("x-studio-secret") or ""
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if not hmac.compare_digest(token, BACKEND_SECRET):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


class LoraItem(BaseModel):
    file: str
    scale: float = 0.8


class RefImage(BaseModel):
    filename: str
    data: str  # base64


class GenerateRequest(BaseModel):
    prompt: str
    width: int = 1024
    height: int = 576
    steps: int = 4
    seed: int | None = None
    quantize: int = 8
    mode: str = "gen"
    image_strength: float | None = None
    guidance: float | None = None
    loras: list[LoraItem] = Field(default_factory=list)
    ref_images: list[RefImage] = Field(default_factory=list)
    system_mode: str | None = None
    genital_override: bool = False


def _lora_files() -> list[str]:
    if not LORA_DIR.is_dir():
        return []
    return sorted(p.name for p in LORA_DIR.iterdir() if p.is_file() and p.suffix == ".safetensors")


@app.get("/health")
def health() -> dict[str, Any]:
    st = backend.status()
    st["ok"] = True
    st["lora_dir"] = str(LORA_DIR)
    st["lora_files"] = _lora_files()
    return st


@app.get("/progress")
def progress() -> dict[str, Any]:
    return {"ok": True, **last_progress()}


@app.get("/loras")
def list_loras() -> dict[str, list[str]]:
    return {"files": _lora_files()}


@app.post("/unload")
def unload() -> dict[str, Any]:
    backend.unload()
    return {"ok": True, **backend.status()}


def _prepare_generate(req: GenerateRequest) -> tuple[list[str], list[float], list[str] | None, Path]:
    lora_paths: list[str] = []
    lora_scales: list[float] = []
    for item in req.loras:
        name = Path(item.file).name
        path = LORA_DIR / name
        if not path.is_file():
            raise HTTPException(400, f"LoRA not found on host: {name}")
        lora_paths.append(str(path))
        lora_scales.append(float(item.scale))

    tmp = Path(tempfile.mkdtemp(prefix="las-gen-", dir=str(TMP_DIR)))
    image_paths: list[str] | None = None
    if req.ref_images:
        if len(req.ref_images) > MAX_REF_IMAGES:
            shutil.rmtree(tmp, ignore_errors=True)
            raise HTTPException(400, f"At most {MAX_REF_IMAGES} reference images")
        image_paths = []
        for item in req.ref_images:
            try:
                raw = base64.b64decode(item.data, validate=True)
            except Exception as e:  # noqa: BLE001
                shutil.rmtree(tmp, ignore_errors=True)
                raise HTTPException(400, f"Invalid reference image: {e}") from e
            if len(raw) > MAX_IMAGE_BYTES:
                shutil.rmtree(tmp, ignore_errors=True)
                raise HTTPException(413, f"Reference image exceeds {MAX_IMAGE_BYTES} bytes")
            suffix = sniffed_image_suffix(raw)
            if not suffix:
                shutil.rmtree(tmp, ignore_errors=True)
                raise HTTPException(400, "Reference image must be PNG, JPEG, or WebP")
            dest = tmp / f"ref-{len(image_paths)}{suffix}"
            dest.write_bytes(raw)
            image_paths.append(str(dest))
    return lora_paths, lora_scales, image_paths, tmp


def _generate_events(req: GenerateRequest) -> Iterator[str]:
    lora_paths, lora_scales, image_paths, tmp = _prepare_generate(req)
    events: queue.Queue[tuple[str, Any]] = queue.Queue()

    def on_progress(info: dict[str, Any]) -> None:
        events.put(("progress", info))

    def worker() -> None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        pending = tmp / f"{stamp}-pending.png"
        try:
            result = backend.generate(
                prompt=req.prompt,
                out_path=pending,
                width=req.width,
                height=req.height,
                steps=req.steps,
                seed=req.seed,
                quantize=req.quantize,
                lora_paths=lora_paths,
                lora_scales=lora_scales,
                image_paths=image_paths,
                on_progress=on_progress,
                mode=req.mode,
                image_strength=req.image_strength,
                guidance=req.guidance,
                system_mode=req.system_mode,
                genital_override=req.genital_override,
            )
            final_name = f"{stamp}-{result['seed']}.png"
            final_path = Path(result.get("path") or pending)
            if not final_path.is_file():
                raise MfluxBackendError("Backend produced no image file")
            png = final_path.read_bytes()
            events.put(
                (
                    "done",
                    {
                        "ok": True,
                        "image_file": final_name,
                        "seed": result["seed"],
                        "image_base64": base64.b64encode(png).decode("ascii"),
                    },
                )
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("generate failed")
            events.put(("error", f"{type(e).__name__}: {e}"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    threading.Thread(target=worker, name="las-generate", daemon=True).start()
    while True:
        kind, payload = events.get()
        if kind == "progress":
            line = {"type": "progress", **payload}
            yield json.dumps(line, ensure_ascii=False) + "\n"
        elif kind == "done":
            yield json.dumps({"type": "done", **payload}, ensure_ascii=False) + "\n"
            return
        else:
            yield json.dumps({"type": "error", "error": str(payload)}, ensure_ascii=False) + "\n"
            return


@app.post("/generate")
def generate(req: GenerateRequest) -> StreamingResponse:
    mode = (req.mode or "gen").strip().lower()
    if mode not in {"gen", "edit"}:
        raise HTTPException(400, "mode must be gen or edit")
    if mode == "edit" and not req.ref_images:
        raise HTTPException(400, "Edit mode requires a reference image")
    req.mode = mode
    return StreamingResponse(
        _generate_events(req),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def main() -> None:
    import uvicorn

    host = os.environ.get("BACKEND_HOST", "127.0.0.1")
    port = int(os.environ.get("BACKEND_PORT", "8090"))
    logger.info("Starting backend on %s:%s", host, port)
    logger.info("LORA_DIR=%s", LORA_DIR)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
