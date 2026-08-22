"""Assemble a natural-language Flux prompt from a structured scene."""

from __future__ import annotations

from typing import Any

from src.catalog_loader import load_fragments


def _frag(fragments: dict[str, Any], key: str, value: Any) -> str | list[str]:
    bucket = fragments.get(key)
    if bucket is None:
        return ""
    if isinstance(bucket, dict):
        if value is None or value == "":
            return ""
        if isinstance(value, list):
            parts = []
            for item in value:
                piece = bucket.get(item, "")
                if piece:
                    parts.append(piece)
            return parts
        return bucket.get(value, "") or ""
    return ""


def _join_unique(parts: list[str]) -> str:
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        p = (p or "").strip().strip(",")
        if not p:
            continue
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return ", ".join(out)


def scene_tags(scene: dict[str, Any]) -> set[str]:
    """Flatten scene into matcher tags like act:vaginal, position:missionary."""
    tags: set[str] = set()

    subject = scene.get("subject") or {}
    if subject.get("type"):
        tags.add(f"subject:{subject['type']}")

    body = scene.get("body") or {}
    breasts = body.get("breasts")
    if breasts:
        tags.add(f"body.breasts:{breasts}")
        if breasts == "implants":
            tags.add("body:implants")
    if body.get("nipples"):
        tags.add(f"body.nipples:{body['nipples']}")
    if body.get("body_detail"):
        tags.add("body:emphasis")

    position = scene.get("position") or {}
    if position.get("pose"):
        tags.add(f"position:{position['pose']}")

    act = scene.get("act") or {}
    for a in act.get("primary") or []:
        if a and a != "none":
            tags.add(f"act:{a}")

    camera = scene.get("camera") or {}
    if camera.get("angle"):
        tags.add(f"camera:{camera['angle']}")

    partners = scene.get("partners") or {}
    if partners.get("count"):
        tags.add(f"partners:{partners['count']}")

    finish = scene.get("finish") or {}
    for fx in finish.get("effects") or []:
        tags.add(f"finish:{fx}")

    return tags


def compose_edit_prompt(
    scene: dict[str, Any],
    *,
    extra_triggers: list[str] | None = None,
    raw_override: str | None = None,
) -> str:
    """Instruction-style prompt for Flux2KleinEdit."""
    if raw_override and raw_override.strip():
        base = raw_override.strip()
        if extra_triggers:
            triggers = _join_unique(list(extra_triggers))
            if triggers:
                return f"{base}, {triggers}"
        return base

    fr = load_fragments("edit")
    chunks: list[str] = [
        "Edit this photograph in place. Do not replace the person or invent a new face."
    ]

    keep = scene.get("keep") or {}
    keep_bits = _frag(fr, "keep.traits", keep.get("traits") or [])
    if isinstance(keep_bits, list) and keep_bits:
        chunks.append("Keep: " + _join_unique(keep_bits))

    change = scene.get("change") or {}
    change_bits = _frag(fr, "change.targets", change.get("targets") or [])
    if isinstance(change_bits, list) and change_bits:
        chunks.append("Change: " + _join_unique(change_bits))

    clothing = scene.get("clothing") or {}
    cloth = _frag(fr, "clothing.state", clothing.get("state"))
    if isinstance(cloth, str) and cloth:
        chunks.append(cloth)
    cloth_details = (clothing.get("details") or "").strip()
    if cloth_details:
        chunks.append(cloth_details)

    position = scene.get("position") or {}
    pose = _frag(fr, "position.pose", position.get("pose"))
    if isinstance(pose, str) and pose:
        chunks.append(pose)

    act = scene.get("act") or {}
    acts = _frag(fr, "act.primary", act.get("primary") or [])
    if isinstance(acts, list):
        chunks.extend([a for a in acts if a])

    camera = scene.get("camera") or {}
    angle = _frag(fr, "camera.angle", camera.get("angle"))
    if isinstance(angle, str) and angle:
        chunks.append(angle)

    finish = scene.get("finish") or {}
    fx = _frag(fr, "finish.effects", finish.get("effects") or [])
    if isinstance(fx, list):
        chunks.extend(fx)

    strength = scene.get("strength") or {}
    amt = _frag(fr, "strength.amount", strength.get("amount"))
    if isinstance(amt, str) and amt:
        chunks.append(amt)

    instruction = scene.get("instruction") or {}
    text = (instruction.get("text") or "").strip()
    if text:
        chunks.append("Request: " + text)

    if extra_triggers:
        chunks.extend(extra_triggers)

    chunks.append(
        "Photorealistic photograph, sharp details, natural skin, match the original lighting, "
        "correct anatomy, unstretched, coherent sex act."
    )

    prompt = _join_unique(chunks)
    if prompt and not prompt[0].isupper():
        prompt = prompt[0].upper() + prompt[1:]
    return prompt


def compose_prompt(
    scene: dict[str, Any],
    *,
    extra_triggers: list[str] | None = None,
    raw_override: str | None = None,
    mode: str = "gen",
) -> str:
    """Build final prompt. raw_override replaces the assembled body if set."""
    if (mode or "").strip().lower() == "edit":
        return compose_edit_prompt(scene, extra_triggers=extra_triggers, raw_override=raw_override)

    if raw_override and raw_override.strip():
        base = raw_override.strip()
        if extra_triggers:
            triggers = _join_unique(list(extra_triggers))
            if triggers:
                return f"{base}, {triggers}"
        return base

    fr = load_fragments("gen")
    chunks: list[str] = []

    style = scene.get("style") or {}
    look = _frag(fr, "style.look", style.get("look"))
    if isinstance(look, str) and look:
        chunks.append(look)

    subject = scene.get("subject") or {}
    age = _frag(fr, "subject.age_look", subject.get("age_look"))
    subj = _frag(fr, "subject.type", subject.get("type"))
    if isinstance(age, str) and age and isinstance(subj, str) and subj:
        chunks.append(f"{age} {subj}")
    elif isinstance(subj, str) and subj:
        chunks.append(subj)
    elif isinstance(age, str) and age:
        chunks.append(age)

    body = scene.get("body") or {}
    for key in ("breasts", "ass", "hips", "nipples", "pubic_hair"):
        piece = _frag(fr, f"body.{key}", body.get(key))
        if isinstance(piece, str) and piece:
            chunks.append(piece)
    details = _frag(fr, "body.body_detail", body.get("body_detail") or [])
    if isinstance(details, list):
        chunks.extend(details)

    clothing = scene.get("clothing") or {}
    cloth = _frag(fr, "clothing.state", clothing.get("state"))
    if isinstance(cloth, str) and cloth:
        chunks.append(cloth)
    cloth_details = (clothing.get("details") or "").strip()
    if cloth_details:
        chunks.append(cloth_details)

    setting = scene.get("setting") or {}
    place = _frag(fr, "setting.place", setting.get("place"))
    if isinstance(place, str) and place:
        chunks.append(place)

    position = scene.get("position") or {}
    pose = _frag(fr, "position.pose", position.get("pose"))
    if isinstance(pose, str) and pose:
        chunks.append(pose)

    act = scene.get("act") or {}
    acts = _frag(fr, "act.primary", act.get("primary") or [])
    if isinstance(acts, list):
        chunks.extend(acts)

    partners = scene.get("partners") or {}
    pcount = _frag(fr, "partners.count", partners.get("count"))
    if isinstance(pcount, str) and pcount:
        chunks.append(pcount)
    pvis = _frag(fr, "partners.visibility", partners.get("visibility"))
    if isinstance(pvis, str) and pvis:
        chunks.append(pvis)

    camera = scene.get("camera") or {}
    angle = _frag(fr, "camera.angle", camera.get("angle"))
    if isinstance(angle, str) and angle:
        chunks.append(angle)
    framing = _frag(fr, "camera.framing", camera.get("framing"))
    if isinstance(framing, str) and framing:
        chunks.append(framing)

    finish = scene.get("finish") or {}
    fx = _frag(fr, "finish.effects", finish.get("effects") or [])
    if isinstance(fx, list):
        chunks.extend(fx)

    notes = (style.get("notes") or "").strip()
    if notes:
        chunks.append(notes)

    if extra_triggers:
        chunks.extend(extra_triggers)

    chunks.append("correct anatomy, unstretched proportions, coherent sex act")

    prompt = _join_unique(chunks)
    # Prefer a readable sentence-ish start for Flux.
    if prompt and not prompt[0].isupper():
        prompt = prompt[0].upper() + prompt[1:]
    return prompt
