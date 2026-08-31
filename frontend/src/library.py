"""In-container photo library on tmpfs /data/library.

Survives page refresh. Dies with the frontend container. No host volume.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from src.imageutil import MAX_IMAGE_BYTES, sniffed_image_suffix

LIBRARY_DIR = Path(os.environ.get("STUDIO_LIBRARY_DIR", "/data/library"))
IMAGES_DIR = LIBRARY_DIR / "images"
INDEX_PATH = LIBRARY_DIR / "index.json"

_lock = threading.Lock()


def ensure_dirs() -> None:
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)


def _empty_index() -> dict[str, Any]:
    return {"items": []}


def _read_index() -> dict[str, Any]:
    if not INDEX_PATH.is_file():
        return _empty_index()
    try:
        data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_index()
    if not isinstance(data, dict):
        return _empty_index()
    items = data.get("items")
    if not isinstance(items, list):
        data["items"] = []
    return data


def _write_index(data: dict[str, Any]) -> None:
    tmp = INDEX_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(INDEX_PATH)


def _public(item: dict[str, Any]) -> dict[str, Any]:
    name = str(item.get("filename") or "")
    return {
        "id": item.get("id"),
        "name": item.get("name") or "",
        "kind": item.get("kind") or "generated",
        "prompt": item.get("prompt") or "",
        "scene": item.get("scene") or {},
        "mode": item.get("mode") or "",
        "loras": item.get("loras") or [],
        "seed": item.get("seed"),
        "created_at": item.get("created_at"),
        "filename": name,
        "source_file": item.get("source_file") or "",
        "url": f"/library/{name}" if name else "",
    }


def _default_title(scene: dict[str, Any] | None, mode: str, kind: str) -> str:
    scene = scene or {}
    pose = str((scene.get("position") or {}).get("pose") or "").strip()
    sex = str((scene.get("sex") or {}).get("category") or "").strip()
    stamp = time.strftime("%Y-%m-%d %H:%M")
    if kind == "upload":
        return f"Upload · {stamp}"
    bits = [x for x in [mode, sex, pose] if x]
    return f"{' · '.join(bits)} · {stamp}" if bits else stamp


def list_items() -> list[dict[str, Any]]:
    ensure_dirs()
    with _lock:
        items = list(_read_index().get("items") or [])
    items.sort(key=lambda it: float(it.get("created_at") or 0), reverse=True)
    return [_public(it) for it in items]


def get_item(item_id: str) -> dict[str, Any] | None:
    with _lock:
        for it in _read_index().get("items") or []:
            if str(it.get("id")) == item_id:
                return dict(it)
    return None


def image_path(filename: str) -> Path:
    return IMAGES_DIR / Path(filename).name


def already_has_source(source_file: str) -> dict[str, Any] | None:
    src = Path(source_file).name
    if not src:
        return None
    with _lock:
        for it in _read_index().get("items") or []:
            if str(it.get("source_file") or "") == src:
                return _public(it)
    return None


def ingest_bytes(
    raw: bytes,
    *,
    suffix: str,
    kind: str,
    name: str | None = None,
    prompt: str | None = None,
    scene: dict[str, Any] | None = None,
    mode: str | None = None,
    loras: list[Any] | None = None,
    seed: int | None = None,
    source_file: str | None = None,
) -> dict[str, Any]:
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError(f"Image exceeds {MAX_IMAGE_BYTES} bytes")
    ensure_dirs()
    item_id = uuid.uuid4().hex[:12]
    ext = suffix if suffix.startswith(".") else f".{suffix}"
    filename = f"{item_id}{ext}"
    dest = IMAGES_DIR / filename
    dest.write_bytes(raw)
    item = {
        "id": item_id,
        "name": (name or "").strip() or _default_title(scene, mode or "", kind),
        "kind": kind,
        "prompt": prompt or "",
        "scene": scene or {},
        "mode": mode or "",
        "loras": loras or [],
        "seed": seed,
        "created_at": time.time(),
        "filename": filename,
        "source_file": Path(source_file).name if source_file else "",
    }
    with _lock:
        data = _read_index()
        data["items"].append(item)
        _write_index(data)
    return _public(item)


def ingest_output(
    path: Path,
    *,
    prompt: str | None = None,
    scene: dict[str, Any] | None = None,
    mode: str | None = None,
    loras: list[Any] | None = None,
    seed: int | None = None,
    name: str | None = None,
) -> dict[str, Any] | None:
    path = Path(path)
    if not path.is_file():
        return None
    existing = already_has_source(path.name)
    if existing:
        return existing
    raw = path.read_bytes()
    suffix = sniffed_image_suffix(raw) or path.suffix or ".png"
    return ingest_bytes(
        raw,
        suffix=suffix,
        kind="generated",
        name=name,
        prompt=prompt,
        scene=scene,
        mode=mode,
        loras=loras,
        seed=seed,
        source_file=path.name,
    )


def rename_item(item_id: str, name: str) -> dict[str, Any] | None:
    title = (name or "").strip()
    if not title:
        raise ValueError("Name is empty")
    with _lock:
        data = _read_index()
        for it in data.get("items") or []:
            if str(it.get("id")) == item_id:
                it["name"] = title
                _write_index(data)
                return _public(it)
    return None


def delete_item(item_id: str) -> bool:
    with _lock:
        data = _read_index()
        items = list(data.get("items") or [])
        keep = [it for it in items if str(it.get("id")) != item_id]
        if len(keep) == len(items):
            return False
        removed = next(it for it in items if str(it.get("id")) == item_id)
        data["items"] = keep
        _write_index(data)
    filename = str(removed.get("filename") or "")
    if filename:
        image_path(filename).unlink(missing_ok=True)
    return True
