"""Assemble a natural-language Flux prompt from a structured scene."""

from __future__ import annotations

from typing import Any

from src.catalog_loader import load_fragments
from src.constraints import preset_fragment
from src.system_prompts import EDIT_IDENTITY_LOCK


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


def _join_edit(parts: list[str]) -> str:
    """Sentence-style join so edit instructions are not a comma soup."""
    seen: set[str] = set()
    sentences: list[str] = []
    for p in parts:
        p = (p or "").strip().strip(",").strip()
        if not p:
            continue
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        if p[-1] not in ".!?":
            p += "."
        if p[0].islower():
            p = p[0].upper() + p[1:]
        sentences.append(p)
    # Drop a chunk that is fully contained in a longer one.
    kept: list[str] = []
    lowers = [s.lower() for s in sentences]
    for s, sl in zip(sentences, lowers):
        if any(sl != other and sl.rstrip(".!") in other for other in lowers):
            continue
        kept.append(s)
    return " ".join(kept)


def _covered(haystack: str, needle: str) -> bool:
    if not needle:
        return True
    h = " ".join(haystack.lower().split())
    n = " ".join(needle.lower().split()).rstrip(".!")
    if not n or n in h:
        return True
    words = [w for w in n.replace(",", " ").split() if len(w) > 3]
    if len(words) >= 3 and sum(1 for w in words if w in h) >= max(3, len(words) - 1):
        return True
    return False


def _filter_edit_triggers(prompt: str, triggers: list[str] | None) -> list[str]:
    """Keep short unique LoRA tokens. Skip gen-style sentences already covered."""
    if not triggers:
        return []
    out: list[str] = []
    existing = prompt.lower()
    skip_prefixes = ("a woman", "the girl", "the image", "the photograph", "image shows")
    for raw in triggers:
        t = (raw or "").strip().strip(",")
        if not t:
            continue
        low = t.lower()
        if t.isupper() and len(t) >= 4:
            if t not in out:
                out.append(t)
            continue
        if low.startswith(skip_prefixes) or len(t) > 48:
            continue
        if low in existing or _covered(existing, t):
            continue
        stems = [w.strip(".,") for w in low.split() if len(w) > 4]
        if stems and all(w[:5] in existing for w in stems):
            continue
        if t not in out:
            out.append(t)
    return out


def _tag_value(value: Any) -> bool:
    return value not in (None, "", "keep", "none")


FEATURE_TAGS: dict[str, list[str]] = {
    "spreading": ["act:spreading"],
    "vaginal_gape": ["act:vaginal_gape"],
    "anal_gape": ["act:anal_gape"],
    "prolapse": ["act:prolapse"],
    "masturbation": ["act:masturbation"],
    "creampie": ["finish:cum_inside"],
    "cum_face": ["finish:cum_face"],
    "cum_body": ["finish:cum_body"],
    "wet": ["finish:wet"],
    "sloppy": ["finish:sloppy"],
    "anal": ["act:anal"],
    "deepthroat": ["act:deepthroat"],
}


def scene_tags(scene: dict[str, Any]) -> set[str]:
    """Flatten scene into matcher tags like act:vaginal, position:missionary."""
    tags: set[str] = set()

    subject = scene.get("subject") or {}
    if _tag_value(subject.get("type")):
        tags.add(f"subject:{subject['type']}")

    body = scene.get("body") or {}
    breasts = body.get("breasts")
    if _tag_value(breasts):
        tags.add(f"body.breasts:{breasts}")
        if breasts == "implants":
            tags.add("body:implants")
    if _tag_value(body.get("nipples")):
        tags.add(f"body.nipples:{body['nipples']}")
    if body.get("body_detail"):
        tags.add("body:emphasis")

    position = scene.get("position") or {}
    if _tag_value(position.get("pose")):
        tags.add(f"position:{position['pose']}")

    act = scene.get("act") or {}
    for a in act.get("primary") or []:
        if _tag_value(a):
            tags.add(f"act:{a}")

    camera = scene.get("camera") or {}
    angle = camera.get("angle")
    if _tag_value(angle):
        tags.add(f"camera:{angle}")
        if angle == "pov_45":
            tags.add("camera:pov")

    partners = scene.get("partners") or {}
    if _tag_value(partners.get("count")):
        tags.add(f"partners:{partners['count']}")

    finish = scene.get("finish") or {}
    for fx in finish.get("effects") or []:
        if _tag_value(fx):
            tags.add(f"finish:{fx}")

    clothing = scene.get("clothing") or {}
    if _tag_value(clothing.get("heels")):
        tags.add(f"clothing.heels:{clothing['heels']}")

    for feat in (scene.get("features") or {}).get("extras") or []:
        if not _tag_value(feat):
            continue
        for tag in FEATURE_TAGS.get(str(feat), []):
            tags.add(tag)

    if (scene.get("clothing") or {}).get("state") in {"nude", "lingerie", "partially", "dress_hiked"}:
        if not _tag_value((scene.get("pose") or {}).get("scene")) and not _tag_value(
            (scene.get("position") or {}).get("pose")
        ):
            tags.add("edit:undress")

    return tags


def compose_edit_prompt(
    scene: dict[str, Any],
    *,
    extra_triggers: list[str] | None = None,
    raw_override: str | None = None,
    pose_ref: bool = False,
) -> str:
    """Target-scene edit prompt. Lead with what to restage; identity once."""
    if raw_override and raw_override.strip():
        return raw_override.strip()

    fr = load_fragments("edit")
    pose_id = (scene.get("position") or {}).get("pose")
    angle_id = (scene.get("camera") or {}).get("angle")
    acts = [a for a in ((scene.get("act") or {}).get("primary") or []) if _tag_value(a)]
    pose_changing = _tag_value(pose_id)
    camera_changing = _tag_value(angle_id)
    must_restage = pose_changing or camera_changing or pose_ref

    chunks: list[str] = []
    if pose_ref:
        chunks.append(
            "The first image is the person (keep her face, skin, hair). "
            "The second image is pose and camera only — match that body position and framing. "
            "Do not copy the second person's identity or the first image's pose"
        )
    elif must_restage:
        chunks.append(
            "Restage this photo. Do not copy the original pose or camera angle."
        )
    chunks.append(EDIT_IDENTITY_LOCK)

    preset_id = (scene.get("pose") or {}).get("scene") or (scene.get("preset") or {}).get("scene")
    preset_text = preset_fragment(preset_id)
    skip_pose = False
    skip_camera = False
    skip_acts: set[str] = set()
    if preset_text:
        chunks.append(preset_text)
        skip_pose = True
        skip_camera = True
        for act_id in acts:
            piece = _frag(fr, "act.primary", act_id)
            if isinstance(piece, str) and piece and _covered(preset_text, piece):
                skip_acts.add(act_id)
            elif act_id == "spreading" and "spread" in preset_text.lower():
                skip_acts.add(act_id)

    on_back = pose_id in {"legs_spread", "lying_back", "missionary"}
    if not preset_text and angle_id == "pov_45" and (on_back or not pose_changing):
        chunks.append(
            "New shot: she is lying on her back with her legs spread wide, knees bent and open, "
            "photographed POV from a 45 degree angle so her face, breasts, genitals, asshole "
            "and buttocks are all fully visible in one frame"
        )
        skip_pose = True
        skip_camera = True
        skip_acts.add("spreading")

    clothing = scene.get("clothing") or {}
    cloth = _frag(fr, "clothing.state", clothing.get("state"))
    if isinstance(cloth, str) and cloth and not _covered(" ".join(chunks), cloth):
        chunks.append(cloth)
    heels = _frag(fr, "clothing.heels", clothing.get("heels"))
    if isinstance(heels, str) and heels:
        chunks.append(heels)
    cloth_details = (clothing.get("details") or "").strip()
    if cloth_details:
        chunks.append(cloth_details)

    if not skip_pose:
        pose = _frag(fr, "position.pose", pose_id)
        if isinstance(pose, str) and pose:
            chunks.append(pose)
    if pose_id in {"legs_spread", "missionary", "lying_back"}:
        skip_acts.add("spreading")

    for act_id in acts:
        if act_id in skip_acts:
            continue
        piece = _frag(fr, "act.primary", act_id)
        if isinstance(piece, str) and piece and not _covered(" ".join(chunks), piece):
            chunks.append(piece)

    partners = scene.get("partners") or {}
    pcount = _frag(fr, "partners.count", partners.get("count"))
    if isinstance(pcount, str) and pcount and not _covered(" ".join(chunks), pcount):
        chunks.append(pcount)

    if not skip_camera:
        angle = _frag(fr, "camera.angle", angle_id)
        if isinstance(angle, str) and angle and not _covered(" ".join(chunks), angle):
            chunks.append(angle)

    finish = scene.get("finish") or {}
    fx = _frag(fr, "finish.effects", finish.get("effects") or [])
    if isinstance(fx, list):
        for item in fx:
            if item and not _covered(" ".join(chunks), item):
                chunks.append(item)

    feats = _frag(fr, "features.extras", (scene.get("features") or {}).get("extras") or [])
    if isinstance(feats, list):
        for item in feats:
            if item and not _covered(" ".join(chunks), item):
                chunks.append(item)

    keep = scene.get("keep") or {}
    keep_ids = [k for k in (keep.get("traits") or []) if _tag_value(k)]
    skip_keep = {"face", "skin", "hair"}
    if must_restage:
        skip_keep.update({"body", "lighting", "setting"})
    if _tag_value(clothing.get("state")):
        skip_keep.add("outfit")
    extra_keep = [k for k in keep_ids if k not in skip_keep]
    keep_bits = _frag(fr, "keep.traits", extra_keep)
    if isinstance(keep_bits, list) and keep_bits:
        chunks.append("Also keep " + _join_unique(keep_bits))

    instruction = scene.get("instruction") or {}
    text = (instruction.get("text") or "").strip()
    if text:
        chunks.append(text)

    extras = _filter_edit_triggers(" ".join(chunks), extra_triggers)
    chunks.extend(extras)

    if must_restage:
        chunks.append("Apply the new pose and camera fully")
    chunks.append("Photoreal, sharp, natural skin, correct anatomy")

    return _join_edit(chunks)


def compose_undress_prompt(
    scene: dict[str, Any],
    *,
    extra_triggers: list[str] | None = None,
    raw_override: str | None = None,
) -> str:
    if raw_override and raw_override.strip():
        return raw_override.strip()

    fr = load_fragments("undress")
    clothing = scene.get("clothing") or {}
    state = clothing.get("state") or "nude"
    cloth = _frag(fr, "clothing.state", state)
    if not (isinstance(cloth, str) and cloth):
        cloth = "she is nude, no clothes"
    chunks: list[str] = [
        f"{cloth}. Keep the same person, face, hair, skin, tattoos, pose, camera, and background.",
        "Do not change body shape or proportions.",
    ]
    heels = _frag(fr, "clothing.heels", clothing.get("heels"))
    if isinstance(heels, str) and heels:
        chunks.append(heels)
    return _join_edit(chunks)


def compose_prompt(
    scene: dict[str, Any],
    *,
    extra_triggers: list[str] | None = None,
    raw_override: str | None = None,
    mode: str = "gen",
    pose_ref: bool = False,
) -> str:
    """Build final prompt. raw_override replaces the assembled body if set."""
    kind = (mode or "").strip().lower()
    if kind == "undress":
        return compose_undress_prompt(
            scene, extra_triggers=extra_triggers, raw_override=raw_override
        )
    if kind in {"edit", "pose"}:
        return compose_edit_prompt(
            scene,
            extra_triggers=extra_triggers,
            raw_override=raw_override,
            pose_ref=pose_ref,
        )

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
    heels = _frag(fr, "clothing.heels", clothing.get("heels"))
    if isinstance(heels, str) and heels:
        chunks.append(heels)
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
