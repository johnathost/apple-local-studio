"""Assemble a natural-language Flux prompt from a structured scene."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from src.catalog_loader import bundled_pose_ref, load_fragments
from src.constraints import apply_edit_preset, preset_caption, preset_director, preset_fragment
from src.system_prompts import EDIT_IDENTITY_LOCK, SEMEN_LOCK

# FK_allholes training caption (lora.md), first scene only — not the all-fours add-on.
GANGBANG_LORA_PROMPT = (
    "the image shows one girl and three men. all three men are penetrating the girl in some way. "
    "oral, anal and vaginal sex. the girl is turned with her ass to the camera in an half-side view "
    "on her body. her face is partially visible from side. the first man is lying on his back and "
    "the girl is straddling on him. he is covered by the girls upper body. the first man is "
    "penetrating the girls vagina, his testicles are visible and his penis visible penetrates her "
    "vagina. the face of the first man is not visible. the second man is standing behind the girl, "
    "his upper body and face is out of frame and not visible. the penis of the second man is clearly "
    "penetrating the girls anus, while the first man is penetrating her vagina. the third man is "
    "standing next to the girl. she holds the penis of the third man in her mouth, performing oral "
    "sex on him."
)


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


# Extras that need a plate which already shows that crotch. Klein cannot invent
# a second hole onto a spreading-pussy crop in 4 distilled steps.
_PLATE_FOR_EXTRA = {
    "prolapse_fucking": "prolapse_chair_tight",
    "prolapse_creampie": "prolapse_chair_tight",
    "prolapse": "prolapse_chair_tight",
}


def retarget_pose_for_extras(scene: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """If extras disagree with the selected plate, switch to a matching one.

    Photo 2 must already contain the genitals we want. Identity stays Photo 1.
    Furniture is not sacred.
    """
    current = str((scene.get("pose") or {}).get("scene") or "")
    requested = _selected_ids(scene, "features", "extras") | _selected_ids(scene, "act", "primary")
    donor = None
    for extra, plate in _PLATE_FOR_EXTRA.items():
        if extra in requested:
            donor = plate
            break
    if not donor or donor == current or current.startswith("prolapse"):
        return scene, []
    if not bundled_pose_ref(donor):
        return scene, []
    extras_keep = scene.get("features")
    out = deepcopy(scene)
    out.setdefault("pose", {})["scene"] = donor
    out = apply_edit_preset(out, donor)
    if isinstance(extras_keep, dict):
        out["features"] = extras_keep
    return out, [f"using {donor} so the reference already shows that crotch"]


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


def compose_edit_prompt(
    scene: dict[str, Any],
    *,
    extra_triggers: list[str] | None = None,
    raw_override: str | None = None,
    pose_ref: bool = False,
) -> str:
    """Short labeled caption. Klein 4-step follows triggers + Field: fact, not essays."""
    if raw_override and raw_override.strip():
        return raw_override.strip()

    extras = _selected_ids(scene, "features", "extras")
    acts = _selected_ids(scene, "act", "primary")
    finish = _selected_ids(scene, "finish", "effects")
    selected = extras | acts
    override = wants_genital_override(scene)
    wants_penis = bool(selected & _PENIS_ACTS)
    preset_id = (scene.get("pose") or {}).get("scene") or (scene.get("preset") or {}).get("scene")
    pose_key = str(preset_id or "")
    director = preset_director(pose_key)
    lora_dir = director == "lora"
    use_plate = bool(pose_ref) and director != "lora"
    caption = preset_caption(pose_key)
    clothing = scene.get("clothing") or {}
    fr = load_fragments("edit")

    lines: list[str] = []
    if extra_triggers:
        trig = _join_unique(list(extra_triggers))
        if trig:
            lines.append(trig)

    # LoRA test: fire the catalog caption, don't mix in our labeled pose essay.
    if pose_key == "lora_gangbang" and not use_plate:
        bits = list(lines)
        bits.append(EDIT_IDENTITY_LOCK)
        bits.append(GANGBANG_LORA_PROMPT)
        notes = (scene.get("instruction") or {}).get("text") or ""
        if str(notes).strip():
            bits.append(str(notes).strip())
        return "\n".join(bits)

    if use_plate:
        lines.append("Photo 1: identity, same face, skin, hair.")
        if pose_key.startswith("prolapse") or "rosebud" in (preset_fragment(pose_key) or "").lower():
            if wants_penis:
                lines.append(
                    "Photo 2: pose and crotch — copy the rosebud on the anus. "
                    "There is no penis in photo 2; add a real one. "
                    "Do not copy photo 2's face or nails."
                )
            else:
                lines.append(
                    "Photo 2: pose and crotch — copy the rosebud on the anus. "
                    "Do not copy photo 2's face or nails."
                )
        elif pose_key.startswith("anal_"):
            lines.append("Photo 2: pose and the fuck. Copy the cock in her ass from the photo.")
        elif override and wants_penis:
            lines.append(
                "Photo 2: pose and legs. There is no cock in photo 2; she's getting fucked — add a real one."
            )
        elif override:
            lines.append("Photo 2: pose and legs.")
        elif wants_penis:
            lines.append("Photo 2: pose, camera, and the fuck. Copy the cock in the photo.")
        else:
            lines.append(
                "Photo 2: pose, camera, and crotch. "
                "Copy her spread pussy and her asshole from photo 2. Pussy above, asshole below."
            )
    else:
        lines.append(EDIT_IDENTITY_LOCK)
        if pose_key == "lora_gangbang":
            lines.append(
                "white bed, tight crop on her ass and the sex. "
                "not a wide group photo, male upper bodies and faces out of frame"
            )
        elif lora_dir or not use_plate:
            lines.append(
                "Plain white seamless studio background, white void, no room, no furniture."
            )
            lines.append(
                "If the photo is a portrait or headshot, invent a full body in this pose. Keep the face."
            )

    if caption:
        lines.append(f"Pose: {caption}.")

    cloth = _frag(fr, "clothing.state", clothing.get("state"))
    if isinstance(cloth, str) and cloth:
        lines.append(f"Outfit: {cloth}.")
    heels = _frag(fr, "clothing.heels", clothing.get("heels"))
    if isinstance(heels, str) and heels:
        lines.append(f"Heels: {heels}.")

    cream = bool(
        selected & {"prolapse_creampie", "creampie"}
        or finish & {"cum_inside"}
    )
    if selected & _PROLAPSE_IDS:
        lines.append("two holes: her pussy on top, her asshole underneath, skin between them")
        lines.append("Pussy: spread pussy, labia, nothing coming out of it.")
        anus = (
            "Asshole: she has a prolapsed asshole, rosebud, folded wet rectal lining "
            "hanging out of her ass"
        )
        if cream:
            anus += ", cum smeared on the folds"
        lines.append(anus + ".")
    elif "anal_gape" in selected:
        anus = "Asshole: anal gape, she has a gaping ass, huge gape, used asshole"
        if cream:
            anus += ", cum leaking out of her ass"
        lines.append(anus + ".")
    elif "vaginal_gape" in selected:
        pussy = "Pussy: she has a gaping pussy, she is spreading her pussy open"
        if cream:
            pussy += ", cum leaking out of her pussy"
        lines.append(pussy + ".")
    elif "spreading" in selected or pose_key.startswith("spread_"):
        lines.append(
            "she's spreading her legs, showing her pussy and her asshole, "
            "two holes: pussy toward her belly, asshole toward the seat, skin between them"
        )
        if lora_dir:
            pussy = (
                "her pussy spread open, labia, clit, a wet hole. "
                "her asshole is a separate pucker right below"
            )
        else:
            pussy = (
                "copy her spread pussy from photo 2: labia, clit, wet hole, "
                "her asshole showing just below"
            )
        if cream:
            pussy += ", cum leaking out of her pussy"
        lines.append(pussy + ".")

    if "all_holes" in selected or pose_key == "lora_gangbang":
        # Match FK_allholes training caption / Civitai example, not a wide lineup.
        lines.append("one girl and three men, all three men are penetrating the girl")
        lines.append("oral, anal and vaginal sex")
        lines.append(
            "the girl is turned with her ass to the camera in a half-side view, "
            "her face partially visible from the side"
        )
        lines.append(
            "the first man is lying on his back, she is straddling him, "
            "he is covered by her upper body, his penis in her vagina, his testicles visible, "
            "his face not visible"
        )
        lines.append(
            "the second man is standing behind her, upper body and face out of frame, "
            "his penis penetrating her anus"
        )
        lines.append(
            "the third man is standing next to her, she holds his penis in her mouth, "
            "performing oral sex, his face out of frame"
        )
    elif "prolapse_fucking" in selected:
        lines.append(
            "a man is fucking her prolapsed asshole, a real cock through the rosebud "
            "into her ass, his hips and thighs attached"
        )
    elif wants_penis and "anal" in selected:
        lines.append(
            "a man is fucking her in the ass, a real cock in her asshole, "
            "his hips and thighs in frame, her pussy empty above it"
        )
    elif wants_penis and "vaginal" in selected:
        lines.append(
            "a man is fucking her pussy, a real cock in her cunt, "
            "his hips and thighs in frame"
        )

    if extras & {"cum_face"} or finish & {"cum_face"}:
        lines.append("cum on her face, a facial, white streaks")
    if extras & {"cum_body"} or finish & {"cum_body"}:
        lines.append("cum on her tits and body")

    partners = (scene.get("partners") or {}).get("count")
    if not wants_penis and partners in {None, "solo", "keep", ""}:
        if selected & _PROLAPSE_IDS or override:
            lines.append("Alone, no penis.")

    notes = (scene.get("instruction") or {}).get("text") or ""
    if str(notes).strip():
        lines.append(str(notes).strip())

    return "\n".join(lines)


def compose_undress_prompt(
    scene: dict[str, Any],
    *,
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
        return compose_undress_prompt(scene, raw_override=raw_override)
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
