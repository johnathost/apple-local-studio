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
    return "edit" if (mode or "").strip().lower() == "edit" else "gen"


@lru_cache(maxsize=2)
def load_schema(mode: str = "gen") -> dict[str, Any]:
    name = "edit_schema.yaml" if _norm_mode(mode) == "edit" else "schema.yaml"
    return _read_yaml(CATALOG_DIR / name)


@lru_cache(maxsize=2)
def load_fragments(mode: str = "gen") -> dict[str, Any]:
    name = "edit_fragments.yaml" if _norm_mode(mode) == "edit" else "fragments.yaml"
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
