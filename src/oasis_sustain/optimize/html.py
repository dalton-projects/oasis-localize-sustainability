"""
HTML minification and transfer sizing.

Whitespace-safe only. Comments go (except conditional comments, which are
functional), runs of blank lines collapse, and inter-tag whitespace shrinks
without being eliminated, because in inline contexts a space between tags is
rendered content and removing it moves the text.

The saving here is small next to images, and most of it comes from compression
rather than minification. That is fine and worth saying out loud: HTML minifying
is not where the win is, and a tool that leads with it is padding its numbers.
"""
from __future__ import annotations

import re

_BROTLI_QUALITY = 5

COMMENT_RE = re.compile(r'<!--(?!\[if)[\s\S]*?-->')
BLANKS_RE = re.compile(r'\n\s*\n+')
INTERTAG_RE = re.compile(r'>\s{2,}<')


def minify(text: str) -> str:
    out = COMMENT_RE.sub('', text)
    out = BLANKS_RE.sub('\n', out)
    # Collapse to a single space rather than nothing: between inline elements
    # that space is rendered, and deleting it changes the page.
    out = INTERTAG_RE.sub('> <', out)
    return out


def compress_only(data: bytes):
    """Transfer size with no transformation.

    Used for JavaScript. We deliberately do NOT claim a minification win on JS:
    production bundles arrive already minified, and asserting an esbuild saving
    we have not measured is exactly the overselling this project exists to
    prevent. All we measure is the compression the host will apply anyway.
    """
    try:
        import brotli
        out = brotli.compress(data, quality=_BROTLI_QUALITY)
        return len(out), "brotli (no transform: already minified)", out
    except Exception:
        return len(data), "not compressed (brotli unavailable)", data


def optimize(data: bytes, ctx: dict):
    """Return (after_bytes, method, optimized_bytes), measured brotli-compressed."""
    try:
        text = data.decode("utf-8", "ignore")
    except Exception:
        return compress_only(data)

    out = minify(text).encode("utf-8")
    try:
        import brotli
        out = brotli.compress(out, quality=_BROTLI_QUALITY)
        return len(out), "minify + brotli", out
    except Exception:
        return len(out), "minify (brotli unavailable)", out
