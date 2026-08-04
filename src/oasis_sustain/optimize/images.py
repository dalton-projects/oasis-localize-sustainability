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


def declared_widths(html: str, base_url: str = "") -> dict[str, int]:
    """Map each <img>'s resolved URL to the width IT declares.

    Per image, never page-wide. An earlier version took the largest `width`
    attribute anywhere on the page and applied it to every image, which fails
    badly in both directions and was caught on a real site: a page whose only
    width attributes were on small logos yielded a cap of 100px, so the gate
    "resized" a full-bleed hero to 100px wide and reported a 98% saving nobody
    could ever deliver. Overstating a saving is the one failure this project
    exists to prevent.

    Images sized by CSS (the modern norm) declare nothing and are absent from
    this map, so the caller falls back to its configured maximum rather than
    inventing a display size.
    """
    import re
    import urllib.parse

    out: dict[str, int] = {}
    for tag in re.findall(r'<img\b[^>]*>', html, re.I):
        m_src = re.search(r'\bsrc\s*=\s*["\']([^"\']+)', tag, re.I)
        m_w = re.search(r'\bwidth\s*=\s*["\']?(\d+)', tag, re.I)
        if not m_src or not m_w:
            continue
        width = int(m_w.group(1))
        if not (16 <= width <= 4000):        # placeholder or spacer, not a size
            continue
        url = m_src.group(1).strip()
        if base_url:
            url = urllib.parse.urldefrag(
                urllib.parse.urljoin(base_url, url))[0]
        # Same image used twice at different sizes: keep the larger, so we
        # never resize below what some part of the page actually shows.
        out[url] = max(out.get(url, 0), width)
    return out


def rendered_width(html: str) -> int:
    """Largest width declared anywhere on the page, or 0 if none.

    Retained for callers that want a page-level hint. Do NOT use it to size an
    individual image; use `declared_widths` for that. See the note there.
    """
    import re
    widths = [int(w) for w in re.findall(r'\bwidth\s*=\s*["\']?(\d+)', html, re.I)
              if w.isdigit()]
    widths = [w for w in widths if 16 <= w <= 4000]
    return max(widths) if widths else 0
