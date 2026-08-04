"""
CSS optimization: drop provably unused rules, minify, then measure on the wire.

DELIBERATELY CONSERVATIVE
Any rule we cannot prove unused is kept. At-rules (@media, @font-face,
@supports, @keyframes), :root, and anything whose selector has no class or id
hook survive untouched. This under-claims the saving, and that is the correct
direction to be wrong in: an understated saving is a disappointment, an
overstated one is the thing this project exists to prevent.

The matching is token-based rather than a real selector engine, which is how
PurgeCSS works too: collect the class, id and tag vocabulary present in the
sampled markup, and drop a rule only when every hook in its selector is absent.
"""
from __future__ import annotations

import re

_BROTLI_QUALITY = 5          # what a CDN realistically serves, not max effort

NAME_RE = re.compile(r'[.#]([A-Za-z0-9_-]+)')
CLASS_ATTR_RE = re.compile(r'class\s*=\s*["\']([^"\']+)["\']', re.I)
ID_ATTR_RE = re.compile(r'id\s*=\s*["\']([^"\'\s]+)["\']', re.I)
TAG_RE = re.compile(r'<([a-zA-Z][a-zA-Z0-9-]*)')


def html_tokens(html: str) -> set[str]:
    """Class / id / tag vocabulary actually present in the markup."""
    toks: set[str] = set()
    for cls in CLASS_ATTR_RE.findall(html):
        toks.update(cls.split())
    toks.update(ID_ATTR_RE.findall(html))
    toks.update(t.lower() for t in TAG_RE.findall(html))
    return toks


def minify(css_text: str) -> str:
    """Whitespace-only minification. No value rewriting, no shorthand folding:
    those need a real CSS engine to do safely, and a wrong one silently changes
    how the page looks."""
    out = re.sub(r'/\*[\s\S]*?\*/', '', css_text)
    out = re.sub(r'\s+', ' ', out)
    out = re.sub(r'\s*([{}:;,])\s*', r'\1', out)
    return out.strip()


def purge(css_text: str, tokens: set[str]) -> tuple[str, int, int]:
    """Drop rules whose every class/id hook is absent from the markup.

    Returns (css, rules_kept, rules_dropped). If tinycss2 is unavailable or the
    stylesheet will not parse, nothing is dropped.
    """
    try:
        import tinycss2
    except ImportError:
        return css_text, 0, 0
    try:
        rules = tinycss2.parse_stylesheet(css_text, skip_comments=True,
                                          skip_whitespace=True)
    except Exception:
        return css_text, 0, 0

    kept, dropped = [], 0
    for rule in rules:
        if rule.type != "qualified-rule":
            kept.append(rule.serialize())          # at-rules always survive
            continue
        try:
            prelude = tinycss2.serialize(rule.prelude)
        except Exception:
            kept.append(rule.serialize())
            continue
        names = set(NAME_RE.findall(prelude))
        if names and not (names & tokens):
            dropped += 1                           # every hook absent: safe
            continue
        kept.append(rule.serialize())
    return "".join(kept), len(kept), dropped


def optimize(data: bytes, ctx: dict):
    """Return (after_bytes, method, optimized_bytes), measured brotli-compressed."""
    try:
        text = data.decode("utf-8", "ignore")
    except Exception:
        return len(data), "skipped: undecodable", data

    tokens = ctx.get("html_tokens") or set()
    dropped = 0
    if tokens:
        text, _, dropped = purge(text, tokens)
    text = minify(text)
    out = text.encode("utf-8")

    try:
        import brotli
        out = brotli.compress(out, quality=_BROTLI_QUALITY)
        how = "brotli"
    except Exception:
        how = "uncompressed (brotli unavailable)"

    method = (f"purged {dropped} unused rule(s) + minify + {how}"
              if dropped else f"minify + {how}")
    return len(out), method, out
