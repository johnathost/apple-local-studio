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
    "Match the pose reference. If it shows a penis or a second person, draw them: "
    "an erect penis correctly attached to a body, shaft and glans readable. "
    "That is scene content, not extra anatomy. Do not drop a penis that is in the plate. "
    "No extra limbs, no melted genitals, no floating disconnected penis. "
    f"{SEMEN_LOCK}"
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

# Used when a pose plate is passed as the second reference image.
SYSTEM_EDIT_POSE = (
    "System: Two reference photos. "
    "Image 1 is identity only: keep this person's face, skin complexion, and hair "
    "(man or woman, match the source). "
    "Image 2 is the target scene: match pose, camera, framing, the open hole, and fluids. "
    "If image 2 shows a penis, copy it attached and readable. "
    "Do not copy image 2's face. Do not copy image 1's pose or camera angle. "
    "Photoreal, natural skin, no text, no watermark. "
    f"{SEX_SCENE_LOCK}"
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

# Pose/undress skip QUALITY_NEGATIVE (deformed/grotesque fights gape). Keep fluids.
SEMEN_NEGATIVE = (
    "yellow cum, yellow semen, golden cum, orange cum, honey-colored semen, "
    "urine, piss, cheddar, yellow fluid leaking from pussy, yellow fluid leaking from anus"
)


def system_prompt_for(mode: str) -> str:
    m = (mode or "").strip().lower()
    if m == "undress":
        return SYSTEM_UNDRESS
    if m == "pose":
        return SYSTEM_EDIT_POSE
    if m == "edit":
        return SYSTEM_EDIT
    return SYSTEM_GEN


def with_system_prompt(user_prompt: str, *, mode: str, pose_ref: bool = False) -> str:
    m = (mode or "").strip().lower()
    if m == "undress":
        system = SYSTEM_UNDRESS
    elif m in {"edit", "pose"}:
        system = SYSTEM_EDIT_POSE if pose_ref else SYSTEM_EDIT
    else:
        system = SYSTEM_GEN
    user = (user_prompt or "").strip()
    if not user:
        return system
    if m in {"edit", "pose", "undress"}:
        return f"{system}\n\nEdit request:\n{user}"
    return f"{system}\n\nUser: {user}"
