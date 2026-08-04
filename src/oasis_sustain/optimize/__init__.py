"""
Deterministic optimizers. The ones that MEASURE are the ones that SHIP.

This is the load-bearing idea of the whole project. The pre-flight gate does not
model a compression ratio and hope; it runs these functions on the site's real
bytes and reports what they actually achieved. The pipeline that later does the
real work calls the SAME functions. So the projection and the delivery cannot
drift apart, and the gate can never promise a saving the pipeline has no code to
produce.

(The upstream engine had exactly that gap: its gate measured CSS-purge and image
savings while its pipeline contained no CSS purge at all, only ffmpeg.)

TWO RULES EVERY OPTIMIZER OBEYS
1. **Wire bytes on both sides.** `before` is what crossed the network, already
   compressed by the host. `after` must therefore also be a wire figure, which
   for text means brotli-compressed. Comparing a gzipped before against a raw
   after invents a saving that does not exist.
2. **Never return a result larger than the input.** "Already optimal" is a real
   and common outcome. An optimizer that emits a bigger file and reports a
   negative reduction is making the page worse while claiming to improve it.
   Enforced centrally in `optimize()` so no backend can forget.

No AI. These are exact, reproducible transformations; a model here would cost
energy, add non-determinism, and make the number impossible to defend.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import css as _css
from . import html as _html
from . import images as _images
from . import strip as _strip

__all__ = ["optimize", "OptimizeResult", "KINDS", "classify"]

KINDS = ("html", "css", "js", "images", "fonts", "other")


@dataclass
class OptimizeResult:
    """What an optimizer achieved, in wire bytes, with its method named."""
    kind: str
    before: int
    after: int
    method: str
    data: bytes | None = None          # optimized bytes, when the caller wants them
    notes: list[str] = field(default_factory=list)

    @property
    def saved(self) -> int:
        return max(0, self.before - self.after)

    @property
    def reduction_pct(self) -> int:
        return round((1 - self.after / self.before) * 100) if self.before else 0

    def as_dict(self) -> dict:
        return {"kind": self.kind, "before": self.before, "after": self.after,
                "saved": self.saved, "reduction_pct": self.reduction_pct,
                "method": self.method, "notes": self.notes}


def classify(url: str, content_type: str = "") -> str:
    """Bucket a resource by content-type first, extension second."""
    import os
    import urllib.parse
    c = (content_type or "").lower()
    p = urllib.parse.urlparse(url).path.lower()
    ext = os.path.splitext(p)[1]
    if "css" in c or ext == ".css":
        return "css"
    if "javascript" in c or ext in (".js", ".mjs"):
        return "js"
    if c.startswith("font/") or "font" in c or ext in (
            ".woff", ".woff2", ".ttf", ".otf", ".eot"):
        return "fonts"
    if c.startswith("image/") or ext in (
            ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg", ".ico"):
        return "images"
    if "html" in c or ext in (".html", ".htm"):
        return "html"
    return "other"


def optimize(kind: str, data: bytes, *, wire_before: int | None = None,
             url: str = "", context: dict | None = None,
             want_data: bool = False) -> OptimizeResult:
    """Run the right optimizer for `kind` and report the result in wire bytes.

    `wire_before` is what actually crossed the network. Pass it whenever it is
    known (a HEAD content-length, or the length of the compressed response);
    `len(data)` is only correct when the response was not content-encoded.

    `context` carries what a backend needs to do its job properly:
        html_tokens   set of class/id/tag names present, for the CSS purge
        max_width     largest width the markup actually displays, for images
        quality       encoder quality level
        formats       image formats to try, smallest wins
        patterns      URL substrings identifying strippable third-party JS
    """
    ctx = context or {}
    before = int(wire_before if wire_before is not None else len(data))

    if kind == "images":
        after, method, out = _images.optimize(data, ctx)
    elif kind == "css":
        after, method, out = _css.optimize(data, ctx)
    elif kind == "html":
        after, method, out = _html.optimize(data, ctx)
    elif kind in ("js", "other"):
        if _strip.is_strippable(url, ctx.get("patterns")):
            # Deleting a request beats compressing it. This is the only
            # optimizer that can reach zero, and it is usually the best one.
            return OptimizeResult(kind, before, 0, "removed: third-party tracker",
                                  b"" if want_data else None,
                                  ["the cheapest request is the one never made"])
        after, method, out = _html.compress_only(data)
    else:
        return OptimizeResult(kind, before, before, "not optimized",
                              data if want_data else None)

    notes = []
    if after >= before:
        # Rule 2. Keep the original rather than shipping a larger file.
        notes.append("already optimal: no encoder beat the source, original kept")
        after, method, out = before, f"{method} (source kept)", data
    return OptimizeResult(kind, before, int(after), method,
                          out if want_data else None, notes)
