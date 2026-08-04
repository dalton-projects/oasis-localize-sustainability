"""
Image optimization: AVIF and WebP, at the dimensions the page actually displays.

The single largest deterministic saving available on a typical site is not
choosing a cleverer codec. It is not shipping a 4000px original into an 800px
slot. Resizing to the rendered width usually beats re-encoding by a wide margin,
and the two compound.

Both configured formats are tried and the smaller wins. The upstream engine had
AVIF listed in its config since the beginning and never produced a single one,
because the code path only ever wrote WebP: a 20-30% saving left on the table on
every site it shipped.
"""
from __future__ import annotations

import io

DEFAULT_FORMATS = ("avif", "webp")
DEFAULT_QUALITY = 65
DEFAULT_MAX_WIDTH = 1920


def _prepare(im, max_width: int):
    """Resize to the display width and normalise the mode for encoding."""
    if im.width > max_width:
        height = max(1, round(im.height * max_width / im.width))
        from PIL import Image
        im = im.resize((max_width, height), Image.LANCZOS)
    if im.mode == "P":
        im = im.convert("RGBA" if "transparency" in im.info else "RGB")
    elif im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGB")
    return im


def optimize(data: bytes, ctx: dict):
    """Return (after_bytes, method, optimized_bytes).

    Falls back to the input untouched whenever Pillow is missing, the payload is
    not a decodable raster, or no encoder beats the source. SVG and ICO are left
    alone: re-rastering a vector is a fidelity loss, not an optimization.
    """
    try:
        from PIL import Image
    except ImportError:
        return len(data), "skipped: Pillow not installed", data

    formats = tuple(ctx.get("formats") or DEFAULT_FORMATS)
    quality = int(ctx.get("quality") or DEFAULT_QUALITY)
    max_width = int(ctx.get("max_width") or DEFAULT_MAX_WIDTH)

    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:
        return len(data), "skipped: not a decodable raster image", data

    if getattr(im, "format", "") in ("SVG",):
        return len(data), "skipped: vector", data

    try:
        im = _prepare(im, max_width)
    except Exception:
        return len(data), "skipped: could not resize", data

    best_size, best_fmt, best_bytes = len(data), None, data
    for fmt in formats:
        buf = io.BytesIO()
        try:
            if fmt == "avif":
                im.save(buf, format="AVIF", quality=quality)
            elif fmt == "webp":
                im.save(buf, format="WEBP", quality=quality, method=6)
            else:
                continue
        except Exception:
            continue                       # codec unavailable in this build
        if buf.tell() < best_size:
            best_size, best_fmt, best_bytes = buf.tell(), fmt, buf.getvalue()

    if best_fmt is None:
        return len(data), f"no encoder beat the source ({'/'.join(formats)})", data
    return (best_size,
            f"{best_fmt} q{quality}, resized to <={max_width}px",
            best_bytes)


def rendered_width(html: str) -> int:
    """Largest width the markup actually declares, capped to something sane.

    Returns 0 when the page declares nothing, so the caller can fall back to a
    configured maximum rather than guessing small and over-claiming the saving.
    """
    import re
    widths = [int(w) for w in re.findall(r'\bwidth\s*=\s*["\']?(\d+)', html, re.I)
              if w.isdigit()]
    widths = [w for w in widths if 16 <= w <= 4000]
    return max(widths) if widths else 0
