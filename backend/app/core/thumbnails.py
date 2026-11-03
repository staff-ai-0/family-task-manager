"""Small, dependency-light thumbnail helper for user-uploaded proof/receipt images.

Thumbnails are generated at upload time (CPU-bound Pillow work — always call
``make_webp_thumbnail`` inside ``run_in_threadpool`` from async request paths) and
stored on disk *alongside* the original with a deterministic name so the
authenticated serving route can find them from the original filename alone
(no extra DB column). List / approval views request the thumb; detail views keep
the full image.

Design notes:
- Output is always WebP (~200px longest side, quality 80) — small and universally
  decodable by every browser this app targets.
- ``make_webp_thumbnail`` NEVER raises: a corrupt / unsupported / truncated image
  returns ``None`` so the caller can persist the original and move on. Callers
  MUST treat ``None`` as "no thumbnail" and fall back to the full image.
- Filenames are content-addressed UUIDs, so the derived thumb name is stable and
  the bytes are immutable — serve them with a long, immutable Cache-Control.
"""
from __future__ import annotations

import io
import os

# Longest-side target for a generated thumbnail, in pixels.
THUMB_MAX_DIM = 200
# WebP encode quality (0-100). 80 is visually clean for small thumbs while
# keeping the byte size tiny.
THUMB_QUALITY = 80
# Suffix that turns an original filename into its thumbnail sibling.
THUMB_SUFFIX = ".thumb.webp"


def thumb_filename(original_filename: str) -> str:
    """Deterministic thumbnail filename for an original upload filename.

    ``"abc123.jpg"`` -> ``"abc123.thumb.webp"``. Only the stem is kept, so the
    same original always maps to the same thumb regardless of source extension.
    """
    stem, _ext = os.path.splitext(original_filename)
    return f"{stem}{THUMB_SUFFIX}"


def make_webp_thumbnail(
    data: bytes,
    *,
    max_dim: int = THUMB_MAX_DIM,
    quality: int = THUMB_QUALITY,
) -> bytes | None:
    """Return WebP thumbnail bytes for ``data``, or ``None`` if it can't be made.

    CPU-bound — call via ``starlette.concurrency.run_in_threadpool`` from async
    code. Never raises: any decode/encode failure (corrupt bytes, truncated
    upload, unsupported format, decompression-bomb guard) yields ``None``.
    """
    try:
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(data)) as im:
            # Honour EXIF orientation so phone photos aren't sideways, then drop
            # the rest of the metadata (thumbnails don't need it).
            im = ImageOps.exif_transpose(im)
            # Downscale in place (keeps aspect ratio; never upscales).
            im.thumbnail((max_dim, max_dim))
            # WebP supports alpha, but flatten palette/CMYK/other odd modes onto
            # a sensible base so the encoder always succeeds.
            if im.mode in ("RGBA", "LA"):
                im = im.convert("RGBA")
            elif im.mode == "P":
                im = im.convert("RGBA" if "transparency" in im.info else "RGB")
            elif im.mode != "RGB":
                im = im.convert("RGB")

            out = io.BytesIO()
            im.save(out, format="WEBP", quality=quality, method=4)
            return out.getvalue()
    except Exception:
        # Malformed / unsupported / truncated image — caller keeps the original
        # and simply serves that when no thumb exists.
        return None


# Longest side sent to a vision model. 1280px is plenty to tell whether a bed
# is made; a raw 12MP phone photo (4–11MB) only slows the call down.
VISION_MAX_DIM = 1280
VISION_QUALITY = 85


def downscale_for_vision(
    data: bytes,
    *,
    max_dim: int = VISION_MAX_DIM,
    quality: int = VISION_QUALITY,
) -> tuple[bytes, str] | None:
    """Return ``(jpeg_bytes, "image/jpeg")`` shrunk for a vision-model call.

    Same contract as ``make_webp_thumbnail``: CPU-bound (use
    ``run_in_threadpool``), never raises, ``None`` means "send the original".
    EXIF orientation is applied so the model sees the photo upright.
    """
    try:
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(data)) as im:
            im = ImageOps.exif_transpose(im)
            im.thumbnail((max_dim, max_dim))  # keeps aspect ratio, never upscales
            if im.mode != "RGB":
                im = im.convert("RGB")
            out = io.BytesIO()
            im.save(out, format="JPEG", quality=quality, optimize=True)
            return out.getvalue(), "image/jpeg"
    except Exception:
        return None
