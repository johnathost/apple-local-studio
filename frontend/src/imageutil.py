"""Shared image sniffing and size caps (frontend uploads + backend refs)."""

from __future__ import annotations

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_REF_IMAGES = 4

# Back-compat aliases used by the backend request checks.
MAX_REF_BYTES = MAX_IMAGE_BYTES


def sniffed_image_suffix(data: bytes) -> str | None:
    """Return a safe suffix if `data` starts with PNG / JPEG / WebP magic."""
    if len(data) >= 8 and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if len(data) >= 3 and data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    return None
