"""Load catalog YAML files (schema, fragments, loras)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import json
import yaml

ROOT = Path(__file__).resolve().parent.parent
CATALOG_DIR = ROOT / "catalog"


def _read_yaml(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"Catalog file missing: {path}")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _norm_mode(mode: str | None) -> str:
    m = (mode or "").strip().lower()
    if m in {"undress", "pose"}:
        return m
    if m == "edit":
        return "pose"
    return "gen"


def catalog_mode(mode: str | None) -> str:
    return _norm_mode(mode)


def engine_mode(mode: str | None) -> str:
    """mflux path: undress/pose are image edits."""
    return "edit" if _norm_mode(mode) in {"undress", "pose"} else "gen"


@lru_cache(maxsize=1)
def load_constraints() -> dict[str, Any]:
    path = CATALOG_DIR / "constraints.yaml"
    if not path.exists():
        return {}
    return _read_yaml(path)


@lru_cache(maxsize=4)
def load_schema(mode: str = "gen") -> dict[str, Any]:
    kind = _norm_mode(mode)
    name = {
        "undress": "undress_schema.yaml",
        "pose": "pose_schema.yaml",
        "gen": "schema.yaml",
    }[kind]
    data = dict(_read_yaml(CATALOG_DIR / name))
    extra = load_constraints()
    data["constraints"] = extra.get("on_select") or {}
    data["presets"] = extra.get("edit_presets") or {}
    data["sanitize_order"] = extra.get("sanitize_order") or []
    if kind == "pose":
        data["pose_categories"] = []
    return data


@lru_cache(maxsize=4)
def load_fragments(mode: str = "gen") -> dict[str, Any]:
    kind = _norm_mode(mode)
    name = "fragments.yaml" if kind == "gen" else "edit_fragments.yaml"
    return _read_yaml(CATALOG_DIR / name)


@lru_cache(maxsize=1)
def load_loras() -> list[dict[str, Any]]:
    data = _read_yaml(CATALOG_DIR / "loras.yaml")
    return list(data.get("loras") or [])


def default_scene(mode: str = "gen") -> dict[str, Any]:
    """Build default scene dict from schema field defaults."""
    schema = load_schema(mode)
    scene: dict[str, Any] = {}
    for group in schema.get("groups", []):
        gid = group["id"]
        scene[gid] = {}
        for field in group.get("fields", []):
            scene[gid][field["id"]] = field.get("default")
    return scene


def engine_defaults(mode: str = "gen") -> dict[str, Any]:
    return dict(load_schema(mode).get("engine_defaults") or {})


@lru_cache(maxsize=1)
def load_pose_plates() -> dict[str, Any]:
    path = CATALOG_DIR / "pose_plates.json"
    if not path.exists():
        return {"categories": []}
    return json.loads(path.read_text(encoding="utf-8"))


def pose_categories_public() -> list[dict[str, Any]]:
    """Categories + pose titles and image URLs (no base64)."""
    out: list[dict[str, Any]] = []
    for cat in load_pose_plates().get("categories") or []:
        poses = []
        for p in cat.get("poses") or []:
            pid = str(p.get("id") or "")
            if not pid:
                continue
            poses.append(
                {
                    "id": pid,
                    "title": p.get("title") or pid,
                    "image_url": f"/api/pose-plates/{pid}",
                }
            )
        out.append(
            {
                "id": cat.get("id") or "cat",
                "label": cat.get("label") or cat.get("id") or "Poses",
                "poses": poses,
            }
        )
    return out


def pose_plate_bytes(pose_id: str | None) -> tuple[bytes, str] | None:
    """Decoded plate bytes and filename suffix, or None."""
    if not pose_id:
        return None
    stem = Path(str(pose_id)).name
    if stem in {".", ".."}:
        return None
    import base64

    for cat in load_pose_plates().get("categories") or []:
        for p in cat.get("poses") or []:
            if str(p.get("id")) != stem:
                continue
            b64 = p.get("image_b64") or ""
            if not b64:
                return None
            raw = base64.b64decode(b64)
            mime = str(p.get("mime") or "image/png")
            suffix = ".jpg" if "jpeg" in mime else ".webp" if "webp" in mime else ".png"
            return raw, suffix
    return None


def bundled_pose_ref(pose_id: str | None) -> bool:
    return pose_plate_bytes(pose_id) is not None


@lru_cache(maxsize=1)
def load_scenes() -> dict[str, Any]:
    path = CATALOG_DIR / "scenes.yaml"
    if not path.exists():
        return {"extras": [], "scenes": []}
    return _read_yaml(path) or {"extras": [], "scenes": []}


def scenes_public() -> dict[str, Any]:
    """Scenes with plate thumb URLs (no base64)."""
    plates: dict[str, dict[str, Any]] = {}
    for cat in pose_categories_public():
        for p in cat.get("poses") or []:
            plates[str(p.get("id"))] = {
                **p,
                "category": cat.get("id"),
                "category_label": cat.get("label"),
            }
    extras = list(load_scenes().get("extras") or [])
    scenes: list[dict[str, Any]] = []
    for raw in load_scenes().get("scenes") or []:
        if not isinstance(raw, dict):
            continue
        director = str(raw.get("director") or "plate").strip().lower() or "plate"
        plate_id = str(raw.get("plate") or (raw.get("id") if director == "plate" else "") or "")
        if director == "plate" and not plate_id:
            continue
        meta = plates.get(plate_id) or {}
        sid = str(raw.get("id") or plate_id)
        scenes.append(
            {
                "id": sid,
                "label": raw.get("label") or meta.get("title") or sid,
                "plate": plate_id or None,
                "director": director,
                "category": raw.get("category") or meta.get("category") or "scenes",
                "category_label": raw.get("category_label") or meta.get("category_label") or "Scenes",
                "image_url": meta.get("image_url") or (f"/api/pose-plates/{plate_id}" if plate_id else None),
                "compatible_extras": [str(x) for x in (raw.get("compatible_extras") or [])],
            }
        )
    return {"extras": extras, "scenes": scenes}


def reload_catalogs() -> None:
    load_schema.cache_clear()
    load_fragments.cache_clear()
    load_loras.cache_clear()
    load_constraints.cache_clear()
    load_pose_plates.cache_clear()
    load_scenes.cache_clear()
