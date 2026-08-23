"""Wish-list → ordered Klein steps. One region per step, last PNG is next subject."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from src.catalog_loader import (
    bundled_pose_ref,
    catalog_mode,
    default_scene,
    engine_defaults,
    engine_mode,
    pose_plate_bytes,
    scenes_public,
)
from src.composer import _PLATE_FOR_EXTRA, wants_genital_override
from src.imageutil import sniffed_image_suffix


MAX_STEPS = 4

GENITAL_EXTRAS = {
    "creampie",
    "vaginal_gape",
    "anal_gape",
    "prolapse",
    "prolapse_creampie",
    "prolapse_fucking",
}

_LABELS = {
    "undress": "Undress",
    "pose": "Pose",
    "creampie": "Creampie",
    "vaginal_gape": "Vaginal gape",
    "anal_gape": "Anal gape",
    "prolapse": "Anal prolapse",
    "prolapse_creampie": "Prolapse creampie",
    "prolapse_fucking": "Prolapse fucking",
    "cum_face": "Cum on face",
    "cum_body": "Cum on body",
    "wet": "Wet",
    "masturbation": "Masturbation",
}


def _extra_label(extra_id: str) -> str:
    for item in scenes_public().get("extras") or []:
        if item.get("id") == extra_id:
            return str(item.get("label") or extra_id)
    return _LABELS.get(extra_id, extra_id)


def _scene_label(scene_id: str | None) -> str:
    if not scene_id:
        return "Pose"
    for item in scenes_public().get("scenes") or []:
        if item.get("id") == scene_id or item.get("plate") == scene_id:
            return str(item.get("label") or scene_id)
    return scene_id


def plan_recipe(
    *,
    undress: bool,
    scene_id: str | None,
    extras: list[str] | None,
    max_steps: int = MAX_STEPS,
) -> list[dict[str, Any]]:
    """Ordered steps. First genital extra rides with the pose; the rest follow."""
    extras = [str(x) for x in (extras or []) if x]
    genital = [e for e in extras if e in GENITAL_EXTRAS]
    rest = [e for e in extras if e not in GENITAL_EXTRAS]
    pose_id = (scene_id or "").strip() or None
    if genital:
        donor = _PLATE_FOR_EXTRA.get(genital[0])
        if donor and bundled_pose_ref(donor):
            pose_id = donor

    steps: list[dict[str, Any]] = []
    if undress:
        steps.append({"kind": "undress", "label": "Undress", "pose_id": None, "extras": []})

    if pose_id or genital:
        first_g = genital[0] if genital else None
        pose_extras = [first_g] if first_g else []
        label = _scene_label(pose_id)
        if first_g:
            label = f"{label} · {_extra_label(first_g)}"
        steps.append(
            {
                "kind": "pose",
                "label": label,
                "pose_id": pose_id,
                "extras": pose_extras,
            }
        )
        follow = genital[1:] + rest
    else:
        follow = extras

    for extra in follow:
        if len(steps) >= max_steps:
            break
        steps.append(
            {
                "kind": "extra",
                "label": _extra_label(extra),
                "pose_id": pose_id,
                "extras": [extra],
            }
        )

    if not steps:
        raise ValueError("Recipe is empty — pick undress, a scene, or an extra")
    return steps[:max_steps]


def _promote(src: Path) -> str:
    uploads = Path(os.environ.get("STUDIO_UPLOADS_DIR", "/data/uploads"))
    uploads.mkdir(parents=True, exist_ok=True)
    raw = src.read_bytes()
    suffix = sniffed_image_suffix(raw) or src.suffix or ".png"
    dest = uploads / f"cont-{uuid.uuid4().hex}{suffix}"
    dest.write_bytes(raw)
    return dest.name


def lora_files_for_job(composed: Any) -> list[dict[str, Any]]:
    """Basename-only LoRA list for the backend (shared mounts / remote)."""
    out: list[dict[str, Any]] = []
    for m in composed.loras:
        if not m.get("available"):
            continue
        file_name = m.get("file") or (Path(m["path"]).name if m.get("path") else "")
        if not file_name:
            continue
        out.append(
            {
                "id": m.get("id"),
                "name": m.get("name"),
                "file": Path(file_name).name,
                "scale": float(m.get("scale") or 0.8),
            }
        )
    return out


def _ensure_plate(pose_id: str | None, ref_images: list[str]) -> list[str]:
    if not pose_id:
        return ref_images
    plate = pose_plate_bytes(pose_id)
    if plate is None:
        return ref_images
    uploads = Path(os.environ.get("STUDIO_UPLOADS_DIR", "/data/uploads"))
    uploads.mkdir(parents=True, exist_ok=True)
    raw, suffix = plate
    dest = uploads / f"pose-ref-{Path(pose_id).name}{suffix}"
    if not dest.is_file() or dest.stat().st_size != len(raw):
        dest.write_bytes(raw)
    if dest.name not in ref_images:
        ref_images.append(dest.name)
    return ref_images


def build_step_job(
    step: dict[str, Any],
    *,
    identity: str,
    width: int,
    height: int,
    steps: int,
    seed: int | None,
    quantize: int,
    guidance: float | None,
    max_loras: int | None,
    notes: str | None,
) -> dict[str, Any]:
    """Compose a single Klein job request (same shape as /api/generate)."""
    from src.models import ComposeRequest
    from src.server import _compose

    kind = step["kind"]
    pose_id = step.get("pose_id")
    extras = list(step.get("extras") or [])
    if kind == "undress":
        mode = "undress"
        scene = default_scene("undress")
        include_triggers = False
    else:
        mode = "pose"
        scene = default_scene("pose")
        if pose_id:
            scene.setdefault("pose", {})["scene"] = pose_id
        scene.setdefault("features", {})["extras"] = extras
        include_triggers = True

    composed = _compose(
        ComposeRequest(
            scene=scene,
            raw_prompt=notes if kind == "undress" else None,
            mode=mode,
            include_triggers=include_triggers,
            pose_ref=mode == "pose",
            max_loras=max_loras,
        )
    )
    prompt = (composed.prompt or "").strip()
    if not prompt:
        raise ValueError(f"Empty prompt for step {step.get('label')}")

    cat = catalog_mode(mode)
    eng = engine_mode(mode)
    defaults = engine_defaults(cat)
    refs = [Path(identity).name]
    if eng == "edit" and mode == "pose":
        refs = _ensure_plate(composed.scene.get("pose", {}).get("scene") or pose_id, refs)

    return {
        "prompt": prompt,
        "width": width or defaults.get("width", 1024),
        "height": height or defaults.get("height", 576),
        "steps": steps or defaults.get("steps", 4),
        "seed": seed,
        "quantize": quantize or defaults.get("quantize", 8),
        "loras": lora_files_for_job(composed),
        "ref_images": refs,
        "mode": eng,
        "system_mode": cat if cat in {"undress", "pose"} else eng,
        "image_strength": None if cat in {"undress", "pose"} else defaults.get("image_strength"),
        "guidance": guidance if guidance is not None else defaults.get("guidance"),
        "scene": composed.scene,
        "genital_override": wants_genital_override(composed.scene),
        "label": step.get("label") or kind,
    }


def run_recipe(job: Any, *, generate_fn: Any, on_inner_progress: Any) -> None:
    """Run planned steps inline on the job worker. generate_fn(req) -> Path."""
    req = job.request
    plan = list(req.get("plan") or [])
    identity = Path(str(req.get("identity") or "")).name
    if not plan:
        raise ValueError("Recipe has no steps")
    n = len(plan)
    job.steps = n
    results: list[dict[str, Any]] = []
    current = identity

    for i, step in enumerate(plan):
        job.step = i + 1
        job.message = str(step.get("label") or f"Step {i + 1}")
        job.progress = i / n

        def _progress(info: dict[str, Any], *, _i: int = i) -> None:
            inner = float(info.get("progress") or 0)
            job.progress = (_i + max(0.0, min(inner, 1.0))) / n
            msg = info.get("message")
            if msg:
                job.message = f"{step.get('label')}: {msg}"
            on_inner_progress(info)

        payload = build_step_job(
            step,
            identity=current,
            width=int(req.get("width") or 1024),
            height=int(req.get("height") or 576),
            steps=int(req.get("steps") or 4),
            seed=req.get("seed"),
            quantize=int(req.get("quantize") or 4),
            guidance=req.get("guidance"),
            max_loras=req.get("max_loras"),
            notes=req.get("notes"),
        )
        path = generate_fn(payload, _progress)
        out_name = Path(path).name
        results.append(
            {
                "label": step.get("label"),
                "status": "done",
                "image_file": out_name,
                "image_url": f"/outputs/{out_name}",
                "prompt": payload.get("prompt"),
                "loras": payload.get("loras") or [],
            }
        )
        current = _promote(Path(path))

    last = results[-1]
    job.progress = 1.0
    job.message = "Done"
    job.result = {
        "image_path": f"/data/outputs/{last['image_file']}",
        "image_url": last["image_url"],
        "image_file": last["image_file"],
        "prompt": last.get("prompt"),
        "loras": last.get("loras") or [],
        "steps": results,
    }
