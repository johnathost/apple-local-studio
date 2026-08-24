"""Instruction prefixes prepended to every mflux prompt.

Flux has no chat roles; this is the system message, applied on the host
right before generate_image so the UI prompt stays the user's scene.
"""

from __future__ import annotations

QUALITY_LOCK = (
    "Correct human anatomy: one head, two arms, two hands, two legs, five fingers per hand. "
    "Natural body proportions, unstretched, not wide or elongated. "
    "The sex act must be physically possible and readable. "
    "No extra limbs, no fused bodies, no melted or monster features, no duplicate faces."
)

# Pose/sex restage must NOT use QUALITY_LOCK's "one head, two arms". That fights
# a male partner and a penis (the model treats them as extra anatomy).
SEMEN_LOCK = (
    "Semen is thick, opaque, pearly white; never yellow, golden, or urine-colored."
)

SEX_SCENE_LOCK = (
    "No extra limbs, no melted genitals, no fused pussy-and-anus into one hole, "
    "no floating disconnected penis."
)

# Short identity lock for the user-facing edit prompt. Pose/camera are NOT locked.
EDIT_IDENTITY_LOCK = (
    "Same person as the photo: same face, same skin complexion, same hair. Do not swap identity."
)

SYSTEM_GEN = (
    "System: Create a single photorealistic explicit adult photograph that makes visual sense. "
    "Every person depicted is a consenting adult 18 years or older. "
    "Follow the scene description. Natural skin, realistic lighting, "
    "no text, no watermark, no illustration. "
    f"{QUALITY_LOCK}"
)

SYSTEM_UNDRESS = (
    "System: Clothing-only edit of the source photograph. "
    "Do not change her face, hair, skin complexion, makeup, tattoos, or body shape. "
    "Do not change pose, camera, framing, lighting, or background. "
    "Only remove or open the clothing. Natural anatomy, photoreal, no text, no watermark."
)

SYSTEM_EDIT = (
    "System: Restage the source photograph. "
    "Keep the same adult's face, hair, and skin (man or woman). "
    "Change pose, camera, and the requested anatomy to match the edit request. "
    "Photoreal, natural skin, no text, no watermark. "
    f"{SEX_SCENE_LOCK}"
)

# Pose with no plate: LoRA + text invent the body. Portrait → full scene on white.
# Do NOT say "no extra limbs / no floating penis" here — gangbang LoRAs need
# extra male bodies, and that lock glues cocks onto her torso.
SYSTEM_EDIT_LORA = (
    "System: One reference photo is WHO: keep this person's face, skin, hair, and nails. "
    "Invent the rest of the body and the requested pose. "
    "Plain white seamless studio background, white void, no room, no furniture. "
    "If the photo is a portrait or headshot, create a full body in this pose on that white background. "
    "Follow the sex act in the edit request. Men are separate people with their own hips and legs. "
    "Photoreal, no text, no watermark."
)

# Used when a pose plate is passed as the second reference image.
SYSTEM_EDIT_POSE = (
    "System: Two reference photos. "
    "Image 1 is WHO: keep this person's face, skin, hair, and nails. "
    "Image 2 is the pose and the genitals: copy body position, camera, and crotch from image 2. "
    "Copy image 2's vulva: mons, labia, a natural cleft above a separate anus. "
    "Do not copy image 2's face, hair, or identity. "
    "Photoreal, no text, no watermark. "
    f"{SEX_SCENE_LOCK}"
)

# Spreading plate + gape/prolapse extras: the plate's crotch is the WRONG anatomy.
SYSTEM_EDIT_POSE_OVERRIDE = (
    "System: Photo 1 is the person (face, skin, hair). "
    "Photo 2 is the pose: keep that furniture, legs, hands, and camera. "
    "Two openings. Pussy on top. Prolapsed anus below. "
    "The prolapse is folded wrinkled flesh, not a smooth pink ball. "
    "If a penis is requested, draw a real skin-colored cock attached to male hips, not a toy. "
    "Photoreal, no text, no watermark."
)

# Used as CFG negative when guidance > 1 (mflux only encodes a negative then).
QUALITY_NEGATIVE = (
    "deformed, mutated, extra limbs, extra arms, extra legs, extra fingers, "
    "fused bodies, melted skin, monster, grotesque, bad anatomy, "
    "stretched, squashed, elongated body, wide face, disfigured, "
    "cloned face, extra heads, poorly drawn hands, messy anatomy, "
    "different person, different face, different skin tone, pale-washed skin, "
    "identity swap, new body, swapped face, "
    "yellow cum, yellow semen, golden cum, urine, piss, honey-colored semen, "
    "text, watermark, cartoon, illustration, 3d render"
)

# Pose/undress skip QUALITY_NEGATIVE (deformed/grotesque fights gape).
# Dry pose: no cum/semen tokens at all (they leak into a pearl on the mons).
DRY_POSE_NEGATIVE = (
    "pearl, egg, orb, marble, blob on crotch, toy sitting on skin, sticker on crotch, "
    "gash, wound, knife cut, extra vagina, missing labia, "
    "fused pussy and anus, cloaca, one giant genital hole, "
    "dildo, glass penis, detached cock, floating penis"
)

# Only when the edit actually asks for cum.
SEMEN_NEGATIVE = (
    "yellow cum, yellow semen, golden cum, orange cum, honey-colored semen, "
    "urine, piss, cheddar, yellow fluid leaking from pussy, yellow fluid leaking from anus, "
    "fused pussy and anus, cloaca, one giant genital hole, extra vagina, "
    "doughnut, donut, pastry, glazed icing, bagel, silicone ring, fleshlight, "
    "toy sitting on skin, sticker on crotch, toothpaste cum, rope of cum pouring, "
    "white egg, peeled egg, marshmallow, white balloon, dollop of cream, white blob, "
    "smooth pink ball, sphere, balloon, tomato, lollipop, ping pong, "
    "dildo, glass penis, pearl, orb on a stick, detached cock, floating penis, "
    "vaginal prolapse, tissue hanging from the pussy, insides coming out of the vagina, "
    "cervix, swirl hanging from the vulva"
)


def with_system_prompt(
    user_prompt: str,
    *,
    mode: str,
    pose_ref: bool = False,
    genital_override: bool = False,
) -> str:
    m = (mode or "").strip().lower()
    if m == "undress":
        system = SYSTEM_UNDRESS
    elif m in {"edit", "pose"}:
        if pose_ref and genital_override:
            system = SYSTEM_EDIT_POSE_OVERRIDE
        elif pose_ref:
            system = SYSTEM_EDIT_POSE
        elif m == "pose":
            system = SYSTEM_EDIT_LORA
        else:
            system = SYSTEM_EDIT
    else:
        system = SYSTEM_GEN
    user = (user_prompt or "").strip()
    if not user:
        return system
    # Only mention semen when the edit actually asks for it. On a dry spread,
    # "pearly white" in the system prompt becomes a pearl glued to the mons.
    low = user.lower()
    if m in {"edit", "pose"} and any(
        k in low for k in ("semen", "creampie", "cum:", "cum ")
    ):
        system = f"{system} {SEMEN_LOCK}"
    if m in {"edit", "pose", "undress"}:
        return f"{system}\n\nEdit request:\n{user}"
    return f"{system}\n\nUser: {user}"
