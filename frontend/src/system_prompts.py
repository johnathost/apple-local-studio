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

SYSTEM_GEN = (
    "System: Create a single photorealistic explicit adult photograph that makes visual sense. "
    "Every person depicted is a consenting adult 18 years or older. "
    "Follow the scene description. Natural skin, realistic lighting, "
    "no text, no watermark, no illustration. "
    f"{QUALITY_LOCK}"
)

SYSTEM_EDIT = (
    "System: You are editing an existing photograph, not drawing a new one. "
    "The input image is the source of truth for identity and framing. "
    "Do not stretch, squash, or widen the image. Keep the original aspect and proportions. "
    "Preserve the same adult person: face, bone structure, skin tone, hair, body type, "
    "and the original lighting and background unless the user asks to change them. "
    "Apply only the requested edits. The result must still be a coherent sex scene, "
    "not a distortion. Photoreal, sharp, natural skin, no plastic look, "
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
