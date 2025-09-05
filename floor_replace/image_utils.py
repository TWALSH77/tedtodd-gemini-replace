import io
from typing import Tuple

from PIL import Image


def normalize_image_bytes(
    image_bytes: bytes,
    target_long_side: int = 3000,
    out_format: str = "JPEG",
    quality: int = 92,
) -> Tuple[bytes, str, Tuple[int, int]]:
    """
    Downscale very large images and re-encode to a compact format suitable for API upload.
    USED BY: server.generate_floor | DEPENDS ON: Pillow
    @param {bytes} image_bytes - raw input bytes
    @param {int} target_long_side - max dimension for width/height
    @param {str} out_format - 'JPEG' preferred for photographs
    @param {int} quality - JPEG quality
    @returns {(bytes, str, (int,int))} - (normalized_bytes, mime_type, (width,height))
    """
    with Image.open(io.BytesIO(image_bytes)) as im:
        im = im.convert("RGB")
        w, h = im.size
        long_side = max(w, h)
        if long_side > target_long_side:
            scale = target_long_side / float(long_side)
            new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
            im = im.resize(new_size, Image.LANCZOS)
        buf = io.BytesIO()
        if out_format.upper() == "JPEG":
            im.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True, subsampling=1)
            mime = "image/jpeg"
        else:
            im.save(buf, format=out_format)
            mime = f"image/{out_format.lower()}"
        return buf.getvalue(), mime, im.size





