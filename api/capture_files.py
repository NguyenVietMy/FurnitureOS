"""Bounded real image decode and canonicalization; no raw originals persist."""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from math import ceil
import threading
import warnings
from PIL import Image, ImageOps, ImageFile
from .capture_auth import CaptureError

DECODE_LOCK = threading.BoundedSemaphore(1)
ImageFile.LOAD_TRUNCATED_IMAGES = False

@dataclass(frozen=True)
class CanonicalPhoto:
    data: bytes
    sha256: str
    width: int
    height: int
    input_bytes: int

def normalize_photo(data: bytes, media_type: str) -> CanonicalPhoto:
    if not 0 < len(data) <= 4_000_000:
        raise CaptureError("file-size", "Each photo must be at most 4 MB.", 413)
    expected = {"image/jpeg": "JPEG", "image/png": "PNG"}.get(media_type)
    signature = "JPEG" if data.startswith(b"\xff\xd8\xff") else "PNG" if data.startswith(b"\x89PNG\r\n\x1a\n") else None
    if expected is None or signature != expected:
        raise CaptureError("file-type", "Choose a real JPEG or PNG photo.", 415)
    if not DECODE_LOCK.acquire(timeout=1):
        raise CaptureError("busy", "Another photo is being decoded. Retry shortly.", 409)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            stream = BytesIO(data)
            with Image.open(stream, formats=["JPEG", "PNG"]) as image:
                width, height = image.size
                if image.format != expected or getattr(image,"n_frames",1) != 1:
                    raise ValueError("format or animation")
                if min(width, height) < 320 or max(width, height) > 8192 or width * height > 20_000_000:
                    raise CaptureError("pixel-limit", "Use a photo with at least 320 pixels on its shorter side and at most 20 million pixels.", 422)
                image.verify()
            stream.seek(0)
            with Image.open(stream, formats=["JPEG", "PNG"]) as image:
                image.load()
                oriented = ImageOps.exif_transpose(image)
                rgb = Image.new("RGB", oriented.size, (255, 255, 255))
                if "A" in oriented.getbands():
                    rgb.paste(oriented.convert("RGB"), mask=oriented.getchannel("A"))
                else:
                    rgb.paste(oriented.convert("RGB"))
                scale = min(1.0, 1800 / max(rgb.size), 1200 / min(rgb.size))
                scaled = rgb.resize((max(1, round(rgb.width * scale)), max(1, round(rgb.height * scale))), Image.Resampling.LANCZOS)
                for attempt in range(12):
                    if ceil(scaled.width / 28) * ceil(scaled.height / 28) > 2795:
                        scaled = scaled.resize((int(scaled.width * .9), int(scaled.height * .9)), Image.Resampling.LANCZOS)
                    out = BytesIO()
                    scaled.save(out, format="JPEG", quality=max(40, 90 - 10 * (attempt % 6)), optimize=True)
                    result = out.getvalue()
                    if len(result) <= 400_000:
                        with Image.open(BytesIO(result), formats=["JPEG"]) as check:
                            check.load()
                            final_size = check.size
                        return CanonicalPhoto(result, sha256(result).hexdigest(), *final_size, len(data))
                    if attempt % 6 == 5:
                        scaled = scaled.resize((int(scaled.width * .8), int(scaled.height * .8)), Image.Resampling.LANCZOS)
    except CaptureError:
        raise
    except (Exception, Warning):
        raise CaptureError("invalid-image", "This photo cannot be decoded safely. Export a JPEG or PNG and retry.", 422) from None
    finally:
        DECODE_LOCK.release()
    raise CaptureError("cannot-normalize", "This photo cannot fit the supported image bounds.", 422)
