"""Select LoRAs for a scene based on tags, priority, and conflicts."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.catalog_loader import engine_defaults, load_loras
from src.composer import scene_tags

DATA_HOME = Path(os.environ.get("STUDIO_DATA_HOME", "/opt/ivoai"))
DEFAULT_LORA_DIR = Path(os.environ.get("STUDIO_LORA_DIR", DATA_HOME / "lora"))


def _prompt_trigger(entry: dict[str, Any]) -> str:
    short = (entry.get("prompt_trigger") or "").strip()
    if short:
        return short
    for t in entry.get("triggers") or []:
        token = str(t).strip()
        if token and len(token) <= 40:
            return token
    return ""


@dataclass
class MatchedLora:
    id: str
    name: str
    file: str
    path: str | None
    scale: float
    score: int
    reasons: list[str]
    triggers: list[str]
    available: bool
    auto: bool = True
    exclusive_group: str | None = None
    prompt_trigger: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "file": self.file,
            "path": self.path,
            "scale": self.scale,
            "score": self.score,
            "reasons": self.reasons,
            "triggers": self.triggers,
            "available": self.available,
            "auto": self.auto,
            "exclusive_group": self.exclusive_group,
            "prompt_trigger": self.prompt_trigger,
        }


def _on_disk(file_name: str, *, names: set[str] | None, lora_dir: Path) -> bool:
    if not file_name:
        return False
    if names is not None:
        return Path(file_name).name in names
    return (lora_dir / Path(file_name).name).is_file()


def match_loras(
    scene: dict[str, Any],
    *,
    lora_dir: Path | None = None,
    on_disk: set[str] | None = None,
    max_loras: int | None = None,
    manual: list[dict[str, Any]] | None = None,
    skip_groups: set[str] | None = None,
) -> list[MatchedLora]:
    """
    Score catalog LoRAs against scene tags.
    on_disk: basenames the backend reports as present (preferred).
    """
    lora_dir = lora_dir or DEFAULT_LORA_DIR
    max_loras = max_loras if max_loras is not None else int(engine_defaults().get("max_loras", 2))
    if int(max_loras) <= 0 and not manual:
        return []
    skip_groups = skip_groups or set()
    tags = scene_tags(scene)
    catalog = load_loras()

    scored: list[MatchedLora] = []
    for entry in catalog:
        if entry.get("enabled") is False:
            continue
        if entry.get("auto") is False:
            continue
        group = (entry.get("exclusive_group") or "").strip() or None
        if group and group in skip_groups:
            continue
        file_name = (entry.get("file") or "").strip()
        entry_tags = set(entry.get("tags") or [])
        require_all = set(entry.get("require_all") or [])
        require_any = set(entry.get("require_any") or [])
        if not entry_tags and not require_all and not require_any:
            continue

        overlap = (entry_tags | require_all | require_any) & tags
        if require_all and not require_all <= tags:
            continue
        if require_any and not (require_any & tags):
            continue

        # No explicit require_*: keep the old strong-tag gate so a lone
        # partners:solo (etc.) cannot pull in a pose LoRA.
        strong = {
            t
            for t in overlap
            if t.startswith(("act:", "position:", "camera:", "finish:"))
            or t in {"subject:futa", "subject:femboy", "body:implants", "body:emphasis"}
            or t.startswith("body.breasts:implants")
            or t.startswith("body.nipples:")
        }
        if not require_all and not require_any:
            if not overlap:
                continue
            if not strong:
                continue

        # Conflicts: if any conflict tag is present in the scene, skip.
        conflicts = set(entry.get("conflicts") or [])
        if conflicts & tags:
            continue

        priority = int(entry.get("priority") or 0)
        score = (
            priority
            + 20 * len(require_all & tags)
            + 12 * len(require_any & tags)
            + 10 * len(entry_tags & tags)
            + 5 * len(strong)
        )
        reasons = sorted((require_all & tags) | strong | (require_any & tags))

        present = _on_disk(file_name, names=on_disk, lora_dir=lora_dir)
        group = (entry.get("exclusive_group") or "").strip() or None

        scored.append(
            MatchedLora(
                id=entry["id"],
                name=entry.get("name") or entry["id"],
                file=file_name,
                path=file_name if present else None,
                scale=float(entry.get("default_scale") or 0.8),
                score=score,
                reasons=reasons,
                triggers=list(entry.get("triggers") or []),
                available=present,
                auto=True,
                exclusive_group=group,
                prompt_trigger=_prompt_trigger(entry),
            )
        )

    scored.sort(key=lambda m: m.score, reverse=True)

    # Apply manual overrides / pins.
    manual = manual or []
    by_id = {m.id: m for m in scored}
    for pin in manual:
        pid = pin.get("id")
        if not pid:
            continue
        if pid in by_id:
            if pin.get("scale") is not None:
                by_id[pid].scale = float(pin["scale"])
            by_id[pid].auto = False
        else:
            # Force from catalog even if tags didn't match.
            entry = next((e for e in catalog if e.get("id") == pid), None)
            if not entry or entry.get("enabled") is False:
                continue
            file_name = (entry.get("file") or "").strip()
            present = _on_disk(file_name, names=on_disk, lora_dir=lora_dir)
            group = (entry.get("exclusive_group") or "").strip() or None
            by_id[pid] = MatchedLora(
                id=pid,
                name=entry.get("name") or pid,
                file=file_name,
                path=file_name if present else None,
                scale=float(pin.get("scale") if pin.get("scale") is not None else entry.get("default_scale") or 0.8),
                score=999,
                reasons=["manual"],
                triggers=list(entry.get("triggers") or []),
                available=present,
                auto=False,
                exclusive_group=group,
                prompt_trigger=_prompt_trigger(entry),
            )

    # Prefer manual pins first, then highest score; cap stack size.
    pinned = [m for m in by_id.values() if not m.auto]
    auto = [m for m in by_id.values() if m.auto]
    auto.sort(key=lambda m: m.score, reverse=True)

    selected: list[MatchedLora] = []
    used_files: set[str] = set()
    used_groups: set[str] = set()
    for m in pinned + auto:
        if m.file and m.file in used_files:
            continue
        if m.exclusive_group and m.exclusive_group in used_groups:
            continue
        selected.append(m)
        if m.file:
            used_files.add(m.file)
        if m.exclusive_group:
            used_groups.add(m.exclusive_group)
        if len(selected) >= max_loras:
            break

    return selected


def list_catalog(
    lora_dir: Path | None = None,
    *,
    on_disk: set[str] | None = None,
) -> list[dict[str, Any]]:
    lora_dir = lora_dir or DEFAULT_LORA_DIR
    out = []
    for entry in load_loras():
        file_name = (entry.get("file") or "").strip()
        present = _on_disk(file_name, names=on_disk, lora_dir=lora_dir)
        out.append(
            {
                "id": entry["id"],
                "name": entry.get("name") or entry["id"],
                "file": file_name,
                "default_scale": entry.get("default_scale", 0.8),
                "priority": entry.get("priority", 0),
                "tags": entry.get("tags") or [],
                "triggers": entry.get("triggers") or [],
                "enabled": entry.get("enabled", True) is not False,
                "available": present,
                "path": file_name if present else None,
                "exclusive_group": (entry.get("exclusive_group") or "").strip() or None,
                "auto": entry.get("auto") is not False,
            }
        )
    return out
