"""Wish-list → ordered Klein steps. One region per step, last PNG is next subject."""

from __future__ import annotations

import os
import random
import uuid
from pathlib import Path
from typing import Any

from src.catalog_loader import (
    catalog_mode,
    default_scene,
    engine_defaults,
    engine_mode,
)
from src.composer import wants_genital_override
from src.imageutil import sniffed_image_suffix


MAX_STEPS = 4
MAX_TAKES = 2

def plan_recipe(
    *,
    undress: bool,
    scene: dict[str, Any] | None = None,
    scene_id: str | None = None,
    extras: list[str] | None = None,
    max_steps: int = MAX_STEPS,
) -> list[dict[str, Any]]:
    """Undress (optional) then one SNOFS pose job with the full scene builder."""
    del scene_id, extras  # plates / extra-steps retired
    steps: list[dict[str, Any]] = []
    if undress:
        steps.append({"kind": "undress", "label": "Undress", "scene": {}})
    pose_scene = dict(scene or {})
    if pose_scene or not undress:
        sex = ((pose_scene.get("sex") or {}).get("category") or "solo")
        pose = ((pose_scene.get("position") or {}).get("pose") or "pose")
        bits = [str(x) for x in (pose, sex) if x]
        steps.append(
            {
                "kind": "pose",
                "label": " · ".join(bits) or "Pose",
                "scene": pose_scene,
            }
        )
    if not steps:
        raise ValueError("Recipe is empty — pick undress or a pose")
    return steps[:max_steps]


def _promote(src: Path) -> str:
    uploads = Path(os.environ.get("STUDIO_UPLOADS_DIR", "/data/uploads"))
    uploads.mkdir(parents=True, exist_ok=True)
    raw = src.read_bytes()
    suffix = sniffed_image_suffix(raw) or src.suffix or ".png"
    dest = uploads / f"cont-{uuid.uuid4().hex}{suffix}"
    dest.write_bytes(raw)
    return dest.name


def keep_frames(raw: Any) -> list[dict[str, Any]]:
    """Sanitize prior filmstrip frames (basename-only output files)."""
    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw or []):
        if not isinstance(item, dict):
            continue
        name = Path(str(item.get("image_file") or "")).name
        if not name or name in {".", ".."}:
            continue
        out.append(
            {
                "label": str(item.get("label") or f"Step {i + 1}"),
                "status": "done",
                "image_file": name,
                "image_url": f"/outputs/{name}",
                "index": i,
            }
        )
        if len(out) >= MAX_STEPS:
            break
    return out


def clamp_takes(n: Any) -> int:
    try:
        v = int(n)
    except (TypeError, ValueError):
        return 1
    if v <= 1:
        return 1
    return MAX_TAKES


def take_seeds(base: int | None, n: int) -> list[int | None]:
    """One seed, or two distinct seeds. None = backend picks at generate time."""
    if n <= 1:
        return [base]
    a = int(base) if base is not None else random.randint(0, 2**31 - 1)
    b = (a + 7919) % (2**31)
    if b == a:
        b = (a + 1) % (2**31)
    return [a, b]


def _queued_frame(step: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "label": str(step.get("label") or f"Step {index + 1}"),
        "status": "queued",
        "image_file": None,
        "image_url": None,
        "index": index,
    }


def _publish_frames(job: Any, frames: list[dict[str, Any]], *, done: bool = False) -> None:
    finished = [f for f in frames if f.get("image_file")]
    last = finished[-1] if finished else None
    job.result = {
        "image_path": f"/data/outputs/{last['image_file']}" if last else None,
        "image_url": last.get("image_url") if last else None,
        "image_file": last.get("image_file") if last else None,
        "prompt": last.get("prompt") if last else None,
        "loras": (last.get("loras") or []) if last else [],
        "steps": frames,
        "partial": not done,
    }


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
    manual_loras: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compose a single Klein job request (same shape as /api/generate)."""
    from src.models import ComposeRequest, LoraPin
    from src.server import _compose

    kind = step["kind"]
    if kind == "undress":
        mode = "undress"
        scene = default_scene("undress")
        include_triggers = False
    else:
        mode = "pose"
        scene = dict(step.get("scene") or default_scene("pose"))
        if notes and str(notes).strip():
            scene.setdefault("instruction", {})["text"] = str(notes).strip()
        include_triggers = True

    composed = _compose(
        ComposeRequest(
            scene=scene,
            raw_prompt=notes if kind == "undress" else None,
            mode=mode,
            include_triggers=include_triggers,
            pose_ref=False,
            max_loras=max_loras,
            manual_loras=[]
            if kind == "undress"
            else [
                LoraPin(**m) if isinstance(m, dict) else m for m in (manual_loras or [])
            ],
        )
    )
    prompt = (composed.prompt or "").strip()
    if not prompt:
        raise ValueError(f"Empty prompt for step {step.get('label')}")

    cat = catalog_mode(mode)
    eng = engine_mode(mode)
    defaults = engine_defaults(cat)
    refs = [Path(identity).name]

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

    retry_step = req.get("retry_step")
    kept = keep_frames(req.get("keep_steps"))
    if retry_step is not None:
        idx = int(retry_step)
        if idx < 0 or idx >= len(plan):
            raise ValueError("retry_step out of range")
        run_plan = [plan[idx]]
        start = idx
        frames: list[dict[str, Any]] = list(kept[:idx])
        while len(frames) < idx:
            frames.append(_queued_frame({"label": f"Step {len(frames) + 1}"}, len(frames)))
    else:
        run_plan = plan
        start = 0
        frames = []

    frames.extend(_queued_frame(step, start + i) for i, step in enumerate(run_plan))
    takes_n = clamp_takes(req.get("takes"))
    klein_counts = [
        takes_n if i == len(run_plan) - 1 else 1 for i in range(len(run_plan))
    ]
    total_klein = max(sum(klein_counts), 1)
    job.steps = total_klein
    job.step = 1
    _publish_frames(job, frames)
    current = identity
    klein_done = 0

    # One LoRA stack for the whole recipe. Undress (0 LoRAs) → pose (1–2)
    # used to full-reload 9B in between and that is the 10-minute tax.
    job_kw = dict(
        width=int(req.get("width") or 1024),
        height=int(req.get("height") or 576),
        steps=int(req.get("steps") or 4),
        seed=None,
        quantize=int(req.get("quantize") or 4),
        guidance=req.get("guidance"),
        max_loras=req.get("max_loras"),
        notes=req.get("notes"),
        manual_loras=list(req.get("manual_loras") or []),
    )
    payloads = [build_step_job(step, identity=identity, **job_kw) for step in run_plan]
    # Keep SNOFS (and any extra pin) sticky across pose steps so Metal does
    # not reload 9B. Do not stamp that stack onto undress — SNOFS restages.
    sticky = next(
        (p.get("loras") for p in payloads if p.get("loras") and p.get("system_mode") != "undress"),
        None,
    )
    if sticky:
        for p in payloads:
            if p.get("system_mode") != "undress":
                p["loras"] = sticky

    for i, step in enumerate(run_plan):
        slot = start + i
        n_takes = klein_counts[i]
        label = str(step.get("label") or f"Step {i + 1}")
        job.message = label
        if slot < len(frames):
            frames[slot]["status"] = "running"
            _publish_frames(job, frames)

        payload = dict(payloads[i])
        refs = [current] + [r for r in (payload.get("ref_images") or [])[1:]]
        payload["ref_images"] = refs
        seeds = take_seeds(req.get("seed"), n_takes)
        rolled: list[dict[str, Any]] = []
        last_path: Path | None = None

        for t, seed in enumerate(seeds):
            take_id = chr(ord("A") + t)
            job.step = klein_done + 1
            job.message = label if n_takes == 1 else f"{label} · take {take_id}"

            def _progress(
                info: dict[str, Any],
                *,
                _k: int = klein_done,
                _tid: str = take_id,
                _lab: str = label,
                _multi: bool = n_takes > 1,
            ) -> None:
                inner = float(info.get("progress") or 0)
                job.progress = (_k + max(0.0, min(inner, 1.0))) / total_klein
                msg = info.get("message")
                if msg:
                    job.message = f"{_lab} · take {_tid}: {msg}" if _multi else f"{_lab}: {msg}"
                on_inner_progress(info)

            gen_payload = dict(payload)
            gen_payload["seed"] = seed
            path = generate_fn(gen_payload, _progress)
            last_path = Path(path)
            out_name = last_path.name
            rolled.append(
                {
                    "id": take_id,
                    "seed": seed,
                    "image_file": out_name,
                    "image_url": f"/outputs/{out_name}",
                }
            )
            show = rolled[-1]
            pending = [
                {"id": chr(ord("A") + t + 1), "seed": None, "image_file": None, "image_url": None}
            ] if t + 1 < n_takes else []
            frames[slot] = {
                "label": label,
                "status": "running" if t + 1 < n_takes else "done",
                "image_file": show["image_file"],
                "image_url": show["image_url"],
                "prompt": payload.get("prompt"),
                "loras": payload.get("loras") or [],
                "index": slot,
                "seed": show.get("seed"),
                "takes": list(rolled) + pending,
                "pick_required": n_takes > 1,
            }
            _publish_frames(job, frames)
            klein_done += 1

        if last_path is not None:
            current = _promote(last_path)

    job.progress = 1.0
    job.message = "Pick a take" if takes_n > 1 else "Done"
    _publish_frames(job, frames, done=True)
