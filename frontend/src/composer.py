"""Assemble a natural-language Flux prompt from a structured scene."""

from __future__ import annotations

from typing import Any

from src.catalog_loader import load_fragments
from src.constraints import preset_fragment
from src.system_prompts import EDIT_IDENTITY_LOCK, SEMEN_LOCK


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
    "prolapse_creampie": ["act:prolapse", "act:prolapse_creampie", "finish:cum_inside"],
    "prolapse_fucking": ["act:prolapse", "act:prolapse_fucking", "act:anal"],
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


def _selected_ids(scene: dict[str, Any], group: str, key: str) -> set[str]:
    val = (scene.get(group) or {}).get(key)
    if isinstance(val, list):
        return {str(x) for x in val if _tag_value(x)}
    if _tag_value(val):
        return {str(val)}
    return set()


_FLUID_IDS = {"creampie", "cum_face", "cum_body", "cum_inside"}
_PENIS_ACTS = {
    "vaginal",
    "anal",
    "oral",
    "deepthroat",
    "all_holes",
    "titfuck",
    "prolapse_fucking",
}
_PROLAPSE_IDS = {"prolapse", "prolapse_creampie", "prolapse_fucking"}


def _penetration_bits(scene: dict[str, Any]) -> list[str]:
    """Force readable male anatomy. Klein edit otherwise drops the cock as 'extra'."""
    acts = _selected_ids(scene, "act", "primary")
    extras = _selected_ids(scene, "features", "extras")
    partners = (scene.get("partners") or {}).get("count")
    wants_penis = (
        bool(acts & _PENIS_ACTS)
        or bool(extras & _PENIS_ACTS)
        or partners in {"one_man", "two_men", "three_men"}
    )
    if not wants_penis:
        return []
    if "prolapse_fucking" in acts or "prolapse_fucking" in extras:
        return [
            "A realistic erect penis is penetrating through the center of the prolapsed "
            "rosebud into the anus, shaft and glans visible, pink everted mucosa ringing "
            "the shaft, male hips and thighs attached"
        ]
    if "anal" in acts or "anal" in extras:
        return [
            "A realistic erect penis is in the shot, shaft and glans visible, "
            "correctly attached to male hips and thighs, the shaft entering her anus"
        ]
    if "vaginal" in acts:
        return [
            "A realistic erect penis is in the shot, shaft and glans visible, "
            "correctly attached to male hips and thighs, the shaft entering her vagina"
        ]
    if acts & {"oral", "deepthroat"}:
        return [
            "A realistic erect penis is in her mouth, shaft and glans visible, attached to a male body"
        ]
    if "titfuck" in acts:
        return [
            "A realistic erect penis is between her breasts, shaft and glans visible, attached to a male body"
        ]
    return [
        "The male partner's erect penis, hips, and thighs are visible and correctly attached"
    ]


def _fluid_bits(scene: dict[str, Any]) -> list[str]:
    """Flux paints unspecified 'cum' as yellow. Name the color and the orifice."""
    extras = _selected_ids(scene, "features", "extras")
    finish = _selected_ids(scene, "finish", "effects")
    acts = _selected_ids(scene, "act", "primary")
    out: list[str] = []
    prolapse_on = bool(acts & _PROLAPSE_IDS or extras & _PROLAPSE_IDS)
    cream_on = (
        "creampie" in extras
        or "cum_inside" in finish
        or "prolapse_creampie" in extras
        or "prolapse_creampie" in acts
    )
    if cream_on and prolapse_on:
        out.append(
            "Pearly-white semen smeared on the everted folds and dripping from the anal rim, "
            "creamy white, not yellow, not a rope pouring from a hole"
        )
    elif cream_on:
        if acts & {"anal", "anal_gape"} or extras & {"anal_gape", "anal"}:
            out.append(
                "Thick opaque pearly-white semen leaking from the open anus, creamy white cum "
                "pooling on the rim, not yellow, not golden, not urine"
            )
        else:
            out.append(
                "Thick opaque pearly-white semen leaking from the pussy, creamy white cum "
                "on the labia, not yellow, not golden, not urine"
            )
    if "cum_face" in extras or "cum_face" in finish:
        out.append("Thick opaque pearly-white semen on their face, white streaks, not yellow")
    if "cum_body" in extras or "cum_body" in finish:
        out.append("Thick opaque pearly-white semen on their body, white not yellow")
    return out


def wants_genital_override(scene: dict[str, Any]) -> bool:
    """True when extras ask for crotch anatomy the pose plate does not show."""
    extras = _selected_ids(scene, "features", "extras")
    acts = _selected_ids(scene, "act", "primary")
    requested = extras | acts
    if not (requested & (_PROLAPSE_IDS | {"anal_gape", "vaginal_gape"})):
        return False
    preset_id = (scene.get("pose") or {}).get("scene") or (scene.get("preset") or {}).get(
        "scene"
    ) or ""
    preset = (preset_fragment(str(preset_id)) or "").lower()
    pid = str(preset_id)
    if requested & _PROLAPSE_IDS and (
        "rosebud" in preset or "prolapse" in preset or pid.startswith("prolapse")
    ):
        return False
    if "anal_gape" in requested and (
        "gape" in preset or "dilated" in preset or pid.startswith("anal_")
    ):
        return False
    return True


def _prolapse_layout_bits() -> list[str]:
    return [
        "Keep this pose and furniture. Two holes: pussy above, anus below, skin between them. "
        "AN4LPR0L4PS3 rosebud comes out of the anus, not out of the pussy"
    ]


def _soften_preset_for_prolapse(text: str) -> str:
    """Stop spreading plates from owning the crotch when a rosebud is requested."""
    out = text
    for old, new in (
        (
            "Both hands hold her inner thighs and spread her pussy open",
            "Both hands hold her inner thighs apart",
        ),
        (
            "Pussy is the center of the frame, anus just below it",
            "Vulva visible in the upper crotch, anus below the perineum",
        ),
        (
            "pussy is the center of the frame, anus just below it",
            "vulva visible in the upper crotch, anus below the perineum",
        ),
        ("spread her pussy open", "hold her inner thighs apart"),
        ("spreading her pussy", "holding her inner thighs"),
    ):
        out = out.replace(old, new)
    return out


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

    extras_ids = _selected_ids(scene, "features", "extras")
    act_ids = _selected_ids(scene, "act", "primary")
    selected_prolapse = extras_ids | act_ids
    override = wants_genital_override(scene)
    wants_penis = bool((extras_ids | act_ids) & _PENIS_ACTS)
    skip_acts: set[str] = set()

    chunks: list[str] = []
    if pose_ref:
        pose_key = str(
            (scene.get("pose") or {}).get("scene")
            or (scene.get("preset") or {}).get("scene")
            or ""
        )
        if pose_key.startswith("prolapse") or "rosebud" in (preset_fragment(pose_key) or "").lower():
            chunks.append(
                "Photo 1 is identity: face, skin, hair. "
                "Photo 2 is pose, camera, and anal anatomy. Copy the rosebud on the anus "
                "from photo 2. Do not copy photo 2's face or nails. Same person as photo 1."
            )
        elif override:
            chunks.append(
                "Photo 1 is identity: face, skin, hair. "
                "Photo 2 is the pose: keep that furniture, legs, hands, and camera. "
                "Do not change the furniture. Do not copy photo 2's face. Same person as photo 1."
            )
        elif wants_penis:
            chunks.append(
                "Photo 1 is identity: face, skin, hair. "
                "Photo 2 is the target scene: copy pose, camera, and any penis, partner, "
                "or fluids actually visible in photo 2. Same person as photo 1."
            )
        else:
            chunks.append(
                "Photo 1 is identity: face, skin, hair. "
                "Photo 2 is pose and camera. Keep that furniture and body position. Same person as photo 1."
            )
    else:
        chunks.append(EDIT_IDENTITY_LOCK)

    if selected_prolapse & _PROLAPSE_IDS:
        chunks.extend(_prolapse_layout_bits())
    if selected_prolapse & {"prolapse_creampie", "prolapse_fucking"}:
        skip_acts.add("prolapse")
    # Lead with crotch extras so 4-step Klein does not lock onto "pussy is the center".
    early_ids = [
        x
        for x in list(extras_ids) + [a for a in act_ids if a not in extras_ids]
        if x in _PROLAPSE_IDS or x in {"anal_gape", "vaginal_gape"}
    ]
    seen_early: set[str] = set()
    for item_id in early_ids:
        if item_id in seen_early or item_id in skip_acts:
            continue
        seen_early.add(item_id)
        piece = _frag(fr, "features.extras", item_id) or _frag(fr, "act.primary", item_id)
        if isinstance(piece, str) and piece and not _covered(" ".join(chunks), piece):
            chunks.append(piece)
            skip_acts.add(item_id)

    preset_id = (scene.get("pose") or {}).get("scene") or (scene.get("preset") or {}).get("scene")
    preset_text = preset_fragment(preset_id)
    skip_pose = False
    skip_camera = False
    skip_partners = False
    if preset_text:
        if selected_prolapse & _PROLAPSE_IDS:
            preset_text = _soften_preset_for_prolapse(preset_text)
        chunks.append(preset_text)
        skip_pose = True
        skip_camera = True
        low_preset = preset_text.lower()
        if any(
            tok in low_preset
            for tok in ("alone", "one man", "two men", "three men", "if a penis", "photo 2")
        ):
            skip_partners = True
        if "penis" in low_preset and any(t in low_preset for t in ("hips", "thigh", "attached")):
            skip_partners = True
        for act_id in acts:
            piece = _frag(fr, "act.primary", act_id)
            if isinstance(piece, str) and piece and _covered(preset_text, piece):
                skip_acts.add(act_id)
            elif act_id == "spreading" and "spread" in low_preset:
                skip_acts.add(act_id)
            elif (
                act_id == "anal"
                and "penis" in low_preset
                and any(t in low_preset for t in ("anus", "anal"))
            ):
                skip_acts.add(act_id)
            elif act_id == "vaginal" and "penis" in low_preset and "vagin" in low_preset:
                skip_acts.add(act_id)
            elif act_id == "masturbation" and "masturbat" in low_preset:
                skip_acts.add(act_id)
            elif act_id == "anal_gape" and any(
                t in low_preset for t in ("dilated", "anal canal", "sphincter")
            ):
                skip_acts.add(act_id)
            elif act_id in _PROLAPSE_IDS and "rosebud" in low_preset and "everted" in low_preset:
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
    if selected_prolapse & _PROLAPSE_IDS:
        skip_acts.add("anal_gape")
    if selected_prolapse & {"prolapse_creampie", "prolapse_fucking"}:
        skip_acts.add("prolapse")

    for act_id in acts:
        if act_id in skip_acts:
            continue
        piece = _frag(fr, "act.primary", act_id)
        if isinstance(piece, str) and piece and not _covered(" ".join(chunks), piece):
            chunks.append(piece)

    partners = scene.get("partners") or {}
    pcount = _frag(fr, "partners.count", partners.get("count"))
    so_far = " ".join(chunks).lower()
    if (
        not skip_partners
        and isinstance(pcount, str)
        and pcount
        and not _covered(so_far, pcount)
        and not ("alone" in so_far and "alone" in pcount.lower())
    ):
        chunks.append(pcount)

    if not skip_camera:
        angle = _frag(fr, "camera.angle", angle_id)
        if isinstance(angle, str) and angle and not _covered(" ".join(chunks), angle):
            chunks.append(angle)

    finish = scene.get("finish") or {}
    fx_ids = [x for x in (finish.get("effects") or []) if _tag_value(x) and x not in _FLUID_IDS]
    fx = _frag(fr, "finish.effects", fx_ids)
    if isinstance(fx, list):
        for item in fx:
            if item and not _covered(" ".join(chunks), item):
                chunks.append(item)

    feat_ids = [
        x
        for x in ((scene.get("features") or {}).get("extras") or [])
        if _tag_value(x) and x not in _FLUID_IDS
    ]
    if (_selected_ids(scene, "act", "primary") | set(feat_ids)) & _PROLAPSE_IDS:
        feat_ids = [x for x in feat_ids if x != "anal_gape"]
    if any(x in feat_ids for x in ("prolapse_creampie", "prolapse_fucking")):
        feat_ids = [x for x in feat_ids if x != "prolapse"]
    feat_ids = [x for x in feat_ids if x not in skip_acts]
    feats = _frag(fr, "features.extras", feat_ids)
    if isinstance(feats, list):
        for item in feats:
            if item and not _covered(" ".join(chunks), item):
                chunks.append(item)

    hay = " ".join(chunks).lower()
    penis_already = (
        "penis" in hay
        and any(t in hay for t in ("penetrat", "enter", "inside", "if a penis", "if one is there"))
        and any(t in hay for t in ("hip", "thigh", "attached", "photo 2", "rosebud"))
    )
    fluid_bits = _fluid_bits(scene)
    if "pearly-white" in hay or "pearly white" in hay:
        fluid_bits = []
    extra_bits = [] if penis_already else _penetration_bits(scene)
    extra_bits.extend(fluid_bits)
    for bit in extra_bits:
        if bit and not _covered(" ".join(chunks), bit):
            chunks.append(bit)
    if fluid_bits and not _covered(" ".join(chunks), SEMEN_LOCK):
        chunks.append(SEMEN_LOCK)

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
    chunks.append("Photoreal photograph")

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
    finish_ids = {
        str(x)
        for x in ((scene.get("finish") or {}).get("effects") or [])
        if _tag_value(x)
    }
    if finish_ids & {"cum_inside", "cum_face", "cum_body"}:
        chunks.append(SEMEN_LOCK)

    prompt = _join_unique(chunks)
    # Prefer a readable sentence-ish start for Flux.
    if prompt and not prompt[0].isupper():
        prompt = prompt[0].upper() + prompt[1:]
    return prompt
