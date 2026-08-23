"""Shared image sniffing, size caps, and pose-plate fit (frontend + backend)."""

from __future__ import annotations

from pathlib import Path

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_REF_IMAGES = 2

# Back-compat aliases used by the backend request checks.
MAX_REF_BYTES = MAX_IMAGE_BYTES

# Skip recode when identity already matches the plate canvas.
_ASPECT_EPS = 0.03
# When cropping a tall photo to a wide plate, keep the face: most cut is from the feet.
_TOP_BIAS = 0.15


def sniffed_image_suffix(data: bytes) -> str | None:
    """Return a safe suffix if `data` starts with PNG / JPEG / WebP magic."""
    if len(data) >= 8 and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if len(data) >= 3 and data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    return None


def cover_crop_box(
    src_w: int,
    src_h: int,
    target_aspect: float,
    *,
    top_bias: float = _TOP_BIAS,
) -> tuple[int, int, int, int]:
    """Pixel box that covers `target_aspect` without stretching.

    Too tall (phone portrait vs crotch-cam): keep the top (face), crop the feet.
    Too wide: crop left/right, centered.
    """
    src_w = max(int(src_w), 1)
    src_h = max(int(src_h), 1)
    if target_aspect <= 0:
        return (0, 0, src_w, src_h)
    src_aspect = src_w / src_h
    if src_aspect >= target_aspect:
        crop_w = min(src_w, max(1, int(round(src_h * target_aspect))))
        left = max(0, (src_w - crop_w) // 2)
        return (left, 0, left + crop_w, src_h)
    crop_h = min(src_h, max(1, int(round(src_w / target_aspect))))
    extra = src_h - crop_h
    bias = max(0.0, min(float(top_bias), 1.0))
    top = min(extra, max(0, int(round(extra * bias))))
    return (0, top, src_w, top + crop_h)


def fit_identity_to_plate(identity: Path, plate: Path, dest: Path) -> Path:
    """Cover-crop Photo 1 to Photo 2's aspect. Same path if already close enough."""
    from PIL import Image, ImageOps

    identity = Path(identity)
    plate = Path(plate)
    dest = Path(dest)
    if not identity.is_file() or not plate.is_file():
        return identity
    try:
        with Image.open(identity) as raw:
            src = ImageOps.exif_transpose(raw)
            src.load()
            src = src.convert("RGB")
        with Image.open(plate) as pl:
            pw, ph = pl.size
    except Exception:
        return identity
    if pw < 16 or ph < 16 or src.size[0] < 16 or src.size[1] < 16:
        return identity
    sw, sh = src.size
    target_aspect = pw / ph
    if abs((sw / sh) - target_aspect) / target_aspect <= _ASPECT_EPS:
        return identity
    if dest.is_file() and dest.stat().st_size > 32:
        return dest

    cropped = src.crop(cover_crop_box(sw, sh, target_aspect))
    cw, ch = cropped.size
    plong = max(pw, ph)
    clong = max(cw, ch)
    if clong > plong * 1.05:
        scale = plong / clong
        nw = max(16, int(round(cw * scale)))
        nh = max(16, int(round(ch * scale)))
        cropped = cropped.resize((nw, nh), Image.Resampling.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cropped.save(dest, format="PNG", optimize=True)
    return dest


def prepare_pose_ref_images(
    uploads: Path,
    ref_images: list[str],
    *,
    system_mode: str | None,
) -> list[str]:
    """For pose restage, fit identity to the plate canvas. Undress/gen unchanged."""
    names = [Path(n).name for n in (ref_images or []) if n]
    if (system_mode or "").strip().lower() != "pose" or len(names) < 2:
        return names
    uploads = Path(uploads)
    ident = uploads / names[0]
    plate = uploads / names[-1]
    try:
        if ident.resolve() == plate.resolve():
            return names
    except OSError:
        return names
    dest = uploads / f"fit-{ident.stem}-{plate.stem}.png"
    try:
        fitted = fit_identity_to_plate(ident, plate, dest)
    except Exception:
        return names
    out = list(names)
    out[0] = fitted.name
    return out
