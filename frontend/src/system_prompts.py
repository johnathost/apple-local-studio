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

# Always prepended to edit prompts so identity cannot drift even if keep-chips are cleared.
EDIT_IDENTITY_LOCK = (
    "Keep this exact person from the source photograph: the same face, the same bone structure, "
    "the same skin complexion, undertone, and skin texture, and the same body shape and proportions. "
    "Do not replace her, do not age or youthen her, do not change ethnicity, "
    "do not lighten or darken her skin, do not give her a new body or a new face."
)

SYSTEM_GEN = (
    "System: Create a single photorealistic explicit adult photograph that makes visual sense. "
    "Every person depicted is a consenting adult 18 years or older. "
    "Follow the scene description. Natural skin, realistic lighting, "
    "no text, no watermark, no illustration. "
    f"{QUALITY_LOCK}"
)

SYSTEM_EDIT = (
    "System: You are editing an existing photograph, not drawing a new one. "
    "The input image is the source of truth for WHO this person is and how she is framed. "
    "Do not stretch, squash, or widen the image. Keep the original aspect and proportions. "
    f"{EDIT_IDENTITY_LOCK} "
    "You may change pose, clothing, camera, and the sex act only as requested. "
    "The result must still be clearly the same adult woman in a coherent scene, "
    "not a distortion or a different person. Photoreal, sharp, natural skin, no plastic look, "
    "no text, no watermark, no illustration. "
    "Every person depicted is a consenting adult 18 years or older. "
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
    return SYSTEM_EDIT if (mode or "").strip().lower() == "edit" else SYSTEM_GEN


def with_system_prompt(user_prompt: str, *, mode: str) -> str:
    system = system_prompt_for(mode)
    user = (user_prompt or "").strip()
    if not user:
        return system
    if (mode or "").strip().lower() == "edit":
        return f"{system}\n\nEdit request:\n{user}"
    return f"{system}\n\nUser: {user}"
