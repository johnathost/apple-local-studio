"""Assemble a natural-language Flux prompt from a structured scene."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from src.catalog_loader import load_fragments
from src.system_prompts import SEMEN_LOCK

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
    "wet_body": ["finish:wet"],
    "dripping": ["finish:wet", "act:spreading"],
    "squirting": ["finish:wet"],
    "drool": ["finish:sloppy"],
    "hard_nipples": ["body.nipples:erect"],
    "anal_creampie": ["finish:cum_inside", "act:anal"],
    "cum_tits": ["finish:cum_body"],
    "cum_ass": ["finish:cum_body"],
    "cum_thighs": ["finish:cum_inside"],
    "cum_mouth": ["finish:cum_face"],
    "smeared_makeup": ["finish:sloppy"],
    "afterglow": ["finish:wet"],
    "hickeys": ["finish:wet"],
    "handprints": ["finish:wet"],
    "spit_tits": ["finish:sloppy"],
    "oiled": ["finish:wet"],
    "condom": ["finish:cum_body"],
    "rectal_leak": ["finish:rectal_leak"],
    "rectal_tear": ["finish:rectal_leak"],
}

_VAGINAL_FLUID_EXTRAS = {"dripping", "squirting", "creampie"}
_SEMEN_HOLE_EXTRAS = {"anal_creampie", "prolapse_creampie"}
_SLEEVE_EXTRAS = {"rectal_leak", "rectal_tear"}
# These steal the crotch: wet/used/outie pussy wins over a rectal sleeve.
_SLEEVE_SKIP_PUSSY = {"creamy", "used", "gaping", "outie", "open"}

_SEX_TAGS: dict[str, list[str]] = {
    "solo": ["partners:solo"],
    "masturbation": ["partners:solo", "act:masturbation"],
    "vaginal": ["act:vaginal", "partners:one_man"],
    "anal": ["act:anal", "partners:one_man"],
    "oral": ["act:oral", "partners:one_man"],
    "gangbang": ["act:all_holes", "act:anal", "act:vaginal", "act:oral", "partners:three_men"],
    "toys": ["act:dildo", "partners:solo"],
}

_SPREAD_POSES = {
    "spread_heels",
    "spread_v",
    "spread_held",
    "spread_press",
    "legs_spread",
    "oral_spread",
    "oral_fold",
    "happy_baby",
    "spread_split",
    "spread_shoulders",
    "spread_edge",
    "spread_one_up",
    "lean_back",
    "soles_out",
    "hold_heels",
    "butterfly",
    "ankles_head",
}
_DOGGY_POSES = {
    "doggy_lookback",
    "doggy_chest",
    "doggy_crawl",
    "doggy_present",
    "all_fours",
}
_ORAL_POSES = {"oral_spread", "oral_fold"}
_RIDING_POSES = {"reverse_lookback"}
_TOY_TAGS: dict[str, list[str]] = {
    "fingers": ["act:masturbation"],
    "dildo_ride_pussy": ["act:dildo", "act:masturbation"],
    "dildo_ride_anal": ["act:dildo", "act:masturbation", "act:anal"],
    "horse_ride_pussy": ["act:dildo", "act:masturbation"],
    "horse_ride_anal": ["act:dildo", "act:masturbation", "act:anal"],
    "wand": ["act:masturbation"],
    "double": ["act:dildo", "act:masturbation"],
}

_PUSSY_TAGS: dict[str, list[str]] = {
    "puffy": ["act:spreading"],
    "open": ["act:spreading"],
    "used": ["act:spreading"],
    "gaping": ["act:vaginal_gape", "act:spreading"],
    "outie": ["act:spreading"],
    "clit": ["act:spreading"],
    "creamy": ["finish:wet"],
}

_ASSHOLE_TAGS: dict[str, list[str]] = {
    "used": ["act:anal_gape"],
    "winking": ["act:anal_gape"],
    "gaping": ["act:anal_gape"],
    "prolapse": ["act:prolapse"],
    "puffy_rim": ["act:anal_gape"],
    "cheeks_spread": ["act:spreading"],
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
    pose_id = str(position.get("pose") or "")
    if _tag_value(pose_id):
        tags.add(f"position:{pose_id}")
        if pose_id in _SPREAD_POSES:
            tags.add("position:legs_spread")
        if pose_id in _DOGGY_POSES:
            tags.add("position:all_fours")
            tags.add("position:doggy")
        if pose_id in _RIDING_POSES:
            tags.add("position:reverse_cowgirl")

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

    sex = (scene.get("sex") or {}).get("category")
    if _tag_value(sex):
        for tag in _SEX_TAGS.get(str(sex), []):
            tags.add(tag)

    for look in _selected_ids(scene, "pussy", "look"):
        for tag in _PUSSY_TAGS.get(look, []):
            tags.add(tag)

    for look in _selected_ids(scene, "asshole", "look"):
        for tag in _ASSHOLE_TAGS.get(look, []):
            tags.add(tag)

    toy = (scene.get("toys") or {}).get("use")
    if _tag_value(toy):
        for tag in _TOY_TAGS.get(str(toy), []):
            tags.add(tag)

    for feat in (scene.get("features") or {}).get("extras") or []:
        if not _tag_value(feat):
            continue
        for tag in FEATURE_TAGS.get(str(feat), []):
            tags.add(tag)
    for feat in (scene.get("extras") or {}).get("effects") or []:
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


def retarget_pose_for_extras(scene: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Plates are retired. Identity + SNOFS invent the crotch."""
    return scene, []


def wants_genital_override(scene: dict[str, Any]) -> bool:
    return False


def _sleeve_paragraphs(fr: dict[str, Any], extras: set[str]) -> list[str]:
    """The good_examples notes pack: partner, yellow-brown leak, red sleeve."""
    lines: list[str] = []
    partner = fr.get("anal_prolapse_partner")
    if isinstance(partner, str) and partner.strip():
        lines.append(partner.strip())
    filth = bool(extras & _SLEEVE_EXTRAS)
    if filth:
        fluids = fr.get("anal_prolapse_fluids")
        if isinstance(fluids, str) and fluids.strip():
            lines.append(fluids.strip())
    sleeve_key = (
        "anal_prolapse_sleeve_torn"
        if filth
        else "anal_prolapse_sleeve"
    )
    sleeve_text = fr.get(sleeve_key) or fr.get("anal_prolapse_sleeve")
    if isinstance(sleeve_text, str) and sleeve_text.strip():
        lines.append(sleeve_text.strip())
    return lines


def _gangbang_lines(pose: str) -> list[str]:
    """Fit three men into the pose already in the prompt. Do not restage her."""
    men = (
        "gangbang, one girl and three men. "
        "a cock in her pussy, a cock in her asshole, a cock in her mouth. "
        "three men with their own hips and legs. she looks at you."
    )
    if pose == "keep":
        return [
            men,
            "keep her original pose and camera. the men fit around her as she already is.",
        ]
    return [men]


def compose_edit_prompt(
    scene: dict[str, Any],
    *,
    extra_triggers: list[str] | None = None,
    raw_override: str | None = None,
    pose_ref: bool = False,
) -> str:
    """SNOFS-style sentences from the scene builder. No Photo 2."""
    del pose_ref  # plates retired
    if raw_override and raw_override.strip():
        return raw_override.strip()

    fr = load_fragments("edit")
    clothing = scene.get("clothing") or {}
    pose = (scene.get("position") or {}).get("pose") or "legs_spread"
    sex = (scene.get("sex") or {}).get("category") or "solo"
    extras = _selected_ids(scene, "extras", "effects") | _selected_ids(scene, "features", "extras")
    pussy = _selected_ids(scene, "pussy", "look")
    ass = _selected_ids(scene, "asshole", "look")
    face = (scene.get("expression") or {}).get("face")

    if "prolapse_creampie" in extras:
        ass = set(ass)
        ass.add("prolapse")
    if "rectal_leak" in extras:
        extras = extras - _VAGINAL_FLUID_EXTRAS - _SEMEN_HOLE_EXTRAS
        pussy = pussy - {"creamy"}
    # Sleeve extras name his cock. Solo/oral would contradict that.
    if extras & _SLEEVE_EXTRAS and str(sex) not in {"anal", "gangbang"}:
        sex = "anal"
    # Sleeve is prompt anatomy (inside-out asshole on his cock), not the prolapse LoRA.
    # Rectal leak / torn sleeve with anal must emit it even if Prolapse
    # was not clicked — otherwise Klein draws a wet pussy and no sleeve.
    sleeve = str(sex) == "anal" and (
        "prolapse" in ass or bool(extras & _SLEEVE_EXTRAS)
    )
    if sleeve:
        pussy = pussy - _SLEEVE_SKIP_PUSSY

    lines: list[str] = []
    if str(pose) == "keep":
        lines.append("Keep her original pose and camera. Do not invent a new body position.")

    pose_line = _frag(fr, "position.pose", pose)
    if isinstance(pose_line, str) and pose_line and str(pose) != "keep":
        lines.append(pose_line)

    sleeve_lines: list[str] = []
    if sleeve:
        sleeve_lines = _sleeve_paragraphs(fr, extras)
        extras = extras - {"rectal_tear", "rectal_leak"}
    elif sex == "gangbang":
        lines.extend(_gangbang_lines(str(pose)))
    elif sex == "oral" and str(pose) in _ORAL_POSES:
        pass
    else:
        sex_line = _frag(fr, "sex.category", sex)
        if isinstance(sex_line, str) and sex_line:
            lines.append(sex_line)

    face_line = _frag(fr, "expression.face", face or "keep")
    if isinstance(face_line, str) and face_line and str(face or "keep") != "keep":
        lines.append(face_line)

    cloth = _frag(fr, "clothing.state", clothing.get("state"))
    if isinstance(cloth, str) and cloth:
        lines.append(cloth)
    heels = _frag(fr, "clothing.heels", clothing.get("heels"))
    if isinstance(heels, str) and heels:
        lines.append(heels)

    toy = (scene.get("toys") or {}).get("use")
    toy_line = _frag(fr, "toys.use", toy)
    if isinstance(toy_line, str) and toy_line:
        lines.append(toy_line)

    pussy_bits = _frag(fr, "pussy.look", sorted(pussy))
    if isinstance(pussy_bits, list):
        lines.extend(pussy_bits)
    elif isinstance(pussy_bits, str) and pussy_bits:
        lines.append(pussy_bits)

    ass_for_frag = set(ass)
    if sleeve:
        ass_for_frag.discard("prolapse")
    ass_bits = _frag(fr, "asshole.look", sorted(ass_for_frag))
    if isinstance(ass_bits, list):
        lines.extend(ass_bits)
    elif isinstance(ass_bits, str) and ass_bits:
        lines.append(ass_bits)

    extra_bits = _frag(fr, "extras.effects", sorted(extras))
    if isinstance(extra_bits, list):
        lines.extend(extra_bits)
    elif isinstance(extra_bits, str) and extra_bits:
        lines.append(extra_bits)

    notes = (scene.get("instruction") or {}).get("text") or ""
    if str(notes).strip():
        lines.append(str(notes).strip())

    # Same place the good_examples notes sat: last, after pose/clothes.
    if sleeve_lines:
        lines.extend(sleeve_lines)

    if extra_triggers:
        trig = _join_unique(list(extra_triggers))
        if trig:
            lines.append(trig)

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
    if cloth and cloth[0].islower():
        cloth = cloth[0].upper() + cloth[1:]
    chunks: list[str] = [
        f"Strip her. {cloth}",
        "Same woman, same face, same hair, same skin, same tattoos, same pose, same camera.",
        "A photograph.",
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
    if finish_ids & {"cum_inside", "cum_face", "cum_body"} and "rectal_leak" not in finish_ids:
        chunks.append(SEMEN_LOCK)

    prompt = _join_unique(chunks)
    # Prefer a readable sentence-ish start for Flux.
    if prompt and not prompt[0].isupper():
        prompt = prompt[0].upper() + prompt[1:]
    return prompt
