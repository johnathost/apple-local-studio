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

# Short identity lock for the user-facing edit prompt. Pose/camera are NOT locked.
EDIT_IDENTITY_LOCK = (
    "Same woman as the photo: same face, same skin complexion, same hair. Do not swap identity."
)

SYSTEM_GEN = (
    "System: Create a single photorealistic explicit adult photograph that makes visual sense. "
    "Every person depicted is a consenting adult 18 years or older. "
    "Follow the scene description. Natural skin, realistic lighting, "
    "no text, no watermark, no illustration. "
    f"{QUALITY_LOCK}"
)

SYSTEM_UNDRESS = (
    "System: Undress the woman in the source photograph. "
    "Identity is fully locked: same face, skin complexion, hair, makeup, tattoos, body type. "
    "Keep the original pose, camera, framing, lighting, and background. "
    "Only remove or open the clothing. Do not restage. Do not invent a new person. "
    "Photoreal, natural skin, no text, no watermark. "
    f"{QUALITY_LOCK}"
)

SYSTEM_EDIT = (
    "System: Edit the source photograph of a consenting adult woman. "
    "Identity is locked: same face, same skin complexion, same hair, same body type. "
    "Pose, camera, clothing, and the act are NOT locked. "
    "If a new pose or camera is requested, restage the shot — do not copy the original pose or framing. "
    "Do not stretch or squash the image. Photoreal, natural skin, no text, no watermark. "
    f"{QUALITY_LOCK}"
)

# Used when a pose plate is passed as the second reference image.
SYSTEM_EDIT_POSE = (
    "System: Two reference photos. "
    "Image 1 is the person: keep her face, skin complexion, and hair. "
    "Image 2 is pose and camera only: match that body position, limb placement, and framing. "
    "Do not copy image 2's identity. Do not copy image 1's pose or camera angle. "
    "Photoreal, natural skin, no text, no watermark. "
    f"{QUALITY_LOCK}"
)

# Used as CFG negative when guidance > 1 (mflux only encodes a negative then).
QUALITY_NEGATIVE = (
    "deformed, mutated, extra limbs, extra arms, extra legs, extra fingers, "
    "fused bodies, melted skin, monster, grotesque, bad anatomy, "
    "stretched, squashed, elongated body, wide face, disfigured, "
    "cloned face, extra heads, poorly drawn hands, messy anatomy, "
    "different person, different face, different skin tone, pale-washed skin, "
    "identity swap, new body, swapped face, "
    "text, watermark, cartoon, illustration, 3d render"
)


def system_prompt_for(mode: str) -> str:
    m = (mode or "").strip().lower()
    if m == "undress":
        return SYSTEM_UNDRESS
    if m in {"edit", "pose"}:
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
