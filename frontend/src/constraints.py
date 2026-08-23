"""Keep composed scenes physically coherent.

Rules live in catalog/constraints.yaml. The UI sends `winner` (the field
just changed) so last-write wins; compose with no winner uses sanitize_order.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from src.catalog_loader import load_constraints


def _split(path: str) -> tuple[str, str]:
    group, _, key = path.partition(".")
    if not group or not key:
        raise ValueError(f"Invalid constraint path: {path}")
    return group, key


def _get(scene: dict[str, Any], path: str) -> Any:
    group, key = _split(path)
    bucket = scene.get(group)
    if not isinstance(bucket, dict):
        return None
    return bucket.get(key)


def _ensure_bucket(scene: dict[str, Any], path: str) -> dict[str, Any]:
    group, _ = _split(path)
    bucket = scene.get(group)
    if not isinstance(bucket, dict):
        bucket = {}
        scene[group] = bucket
    return bucket


def _iter_selected(scene: dict[str, Any], path: str) -> list[str]:
    val = _get(scene, path)
    if val is None or val == "" or val == "keep":
        return []
    if isinstance(val, list):
        return [str(x) for x in val if x not in (None, "", "none", "keep")]
    return [str(val)]


def _apply_actions(scene: dict[str, Any], actions: list[Any] | None) -> list[str]:
    dropped: list[str] = []
    if not actions:
        return dropped
    for action in actions:
        if not isinstance(action, dict):
            continue
        field = str(action.get("field") or "")
        if "." not in field:
            continue
        group, key = _split(field)
        bucket = _ensure_bucket(scene, field)
        cur = bucket.get(key)

        drop = [str(x) for x in (action.get("drop") or [])]
        if drop:
            if isinstance(cur, list):
                new = [x for x in cur if str(x) not in drop]
                removed = [x for x in cur if str(x) in drop]
                if removed:
                    bucket[key] = new
                    dropped.extend(f"{field}:{x}" for x in removed)
            elif cur is not None and str(cur) in drop:
                # Choice fields need replace_with; dropping alone is a no-op.
                pass

        replace_if = action.get("replace_if_in")
        if replace_if is not None:
            allowed = {str(x) for x in replace_if}
            if cur is not None and str(cur) in allowed:
                new_val = action.get("replace_with")
                if new_val != cur:
                    dropped.append(f"{field}:{cur}→{new_val}")
                    bucket[key] = new_val
    return dropped


def _on_select(spec: dict[str, Any]) -> dict[str, Any]:
    raw = spec.get("on_select") if spec else None
    return raw if isinstance(raw, dict) else {}


def apply_edit_preset(scene: dict[str, Any], preset_id: str | None) -> dict[str, Any]:
    """Merge a named edit preset's field patch into the scene."""
    if not preset_id or preset_id == "none":
        return scene
    spec = load_constraints()
    presets = spec.get("edit_presets") or {}
    entry = presets.get(preset_id)
    if not isinstance(entry, dict):
        return scene
    apply = entry.get("apply") or {}
    if not isinstance(apply, dict):
        return scene
    out = deepcopy(scene)
    for group, fields in apply.items():
        if not isinstance(fields, dict):
            out[group] = fields
            continue
        base = dict(out.get(group) or {}) if isinstance(out.get(group), dict) else {}
        base.update(fields)
        out[group] = base
    out.setdefault("preset", {})
    if not isinstance(out["preset"], dict):
        out["preset"] = {}
    out["preset"]["scene"] = preset_id
    return out


def preset_fragment(preset_id: str | None) -> str:
    if not preset_id or preset_id == "none":
        return ""
    entry = (load_constraints().get("edit_presets") or {}).get(preset_id) or {}
    frag = entry.get("fragment") or ""
    return str(frag).strip()


def preset_caption(preset_id: str | None) -> str:
    """One-line pose caption for Klein. Falls back to the fragment's first sentence."""
    if not preset_id or preset_id == "none":
        return ""
    entry = (load_constraints().get("edit_presets") or {}).get(preset_id) or {}
    cap = str(entry.get("caption") or "").strip().rstrip(".")
    if cap:
        return cap
    frag = str(entry.get("fragment") or "").strip()
    if not frag:
        return ""
    return frag.split(".")[0].strip()


def blocked_options(scene: dict[str, Any]) -> dict[str, list[str]]:
    """Options that conflict with the current scene (UI greys them out)."""
    spec = _on_select(load_constraints())
    blocked: dict[str, set[str]] = {}
    for path, values in spec.items():
        if not isinstance(values, dict):
            continue
        for selected in _iter_selected(scene, str(path)):
            # Solo is the gen default; don't strike through partner acts.
            # Clicking those acts still upgrades partners via last-write.
            if str(path) == "partners.count" and selected == "solo":
                continue
            actions = values.get(selected) or []
            if not isinstance(actions, list):
                continue
            for action in actions:
                if not isinstance(action, dict):
                    continue
                field = str(action.get("field") or "")
                if not field:
                    continue
                bucket = blocked.setdefault(field, set())
                bucket.update(str(x) for x in (action.get("drop") or []))
                bucket.update(str(x) for x in (action.get("replace_if_in") or []))
    return {k: sorted(v) for k, v in blocked.items()}


def sanitize_scene(
    scene: dict[str, Any],
    *,
    winner: str | None = None,
    mode: str = "gen",
) -> tuple[dict[str, Any], list[str]]:
    """Return (scene, dropped descriptors). Never mutates the input."""
    _ = mode
    out = deepcopy(scene)
    spec = load_constraints()
    on_select = _on_select(spec)
    dropped: list[str] = []

    def apply_path(path: str) -> None:
        values = on_select.get(path) or {}
        if not isinstance(values, dict):
            return
        for selected in _iter_selected(out, path):
            dropped.extend(_apply_actions(out, values.get(selected)))

    winner = (winner or "").strip() or None
    if winner and winner in on_select:
        apply_path(winner)
        return out, dropped

    order = list(spec.get("sanitize_order") or [])
    if not order:
        order = ["position.pose", "act.primary", "camera.angle", "partners.count"]
    for path in order:
        apply_path(str(path))
    return out, dropped
