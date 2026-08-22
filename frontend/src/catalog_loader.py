"""Load catalog YAML files (schema, fragments, loras)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

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


def reload_catalogs() -> None:
    load_schema.cache_clear()
    load_fragments.cache_clear()
    load_loras.cache_clear()
    load_constraints.cache_clear()
