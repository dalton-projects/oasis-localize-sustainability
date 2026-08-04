"""
Network access: budgeted, paced, polite, and honest about what it cost.

Everything that touches the network in this project goes through here, so there
is exactly one place to audit for how many requests we make, how fast, and
whether we asked permission first.

THE BUDGET IS THE POINT
A triage pass that costs as much as the job it is triaging has defeated itself.
So requests are capped and the cap is enforced by refusing to spend, not by
hoping. Two separate budgets, because they cost wildly different amounts:

  GET   full body. Capped hard (default 20). Spent only where bytes must
        actually be read, i.e. to run a real optimizer on real content.
  HEAD  headers only, no body. Capped separately and more generously, because
        a HEAD is a few hundred bytes where the body could be megabytes.

Both counts are reported. When either runs out the caller is told, so the report
can say the measured weight is a floor rather than quietly presenting a partial
figure as a total.

DECOMPRESSION IS NOT OPTIONAL
urllib does not transparently decompress. Read a gzip response and parse it and
every regex returns nothing, which reads as "this page has no stylesheets"
rather than as an error. That bug is silent and it biases every measurement
downward. So: count the WIRE bytes (what actually crossed the network, which is
what the carbon model wants) and hand back the PLAINTEXT (what the parser wants).
"""
from __future__ import annotations

import gzip
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import zlib

from . import config

DEFAULT_UA = ("OasisSustain/1.0 (+https://github.com/Gabriel-Dalton/"
              "oasis-localize-sustainability)")


def user_agent() -> str:
    return config.section("politeness").get("user_agent") or DEFAULT_UA


def decompress(raw: bytes, encoding: str | None) -> bytes:
    """Undo Content-Encoding for parsing.

    Returns the input unchanged if the encoding is absent, unknown, or the
    payload does not actually decode. Never raises: a body we cannot decompress
    is still a body we can count.
    """
    enc = (encoding or "").strip().lower()
    try:
        if enc == "gzip":
            return gzip.decompress(raw)
        if enc == "br":
            import brotli
            return brotli.decompress(raw)
        if enc == "deflate":
            try:
                return zlib.decompress(raw)
            except zlib.error:
                return zlib.decompress(raw, -zlib.MAX_WBITS)
    except Exception:
        return raw
    return raw


class Budget:
    """A hard request budget with global pacing.

    Refuses to spend past its caps rather than exceeding them quietly. Tracks
    wire bytes so the run can meter itself.
    """

    def __init__(self, gets: int = 20, heads: int = 60, delay: float | None = None,
                 ua: str | None = None, timeout: int = 20):
        pol = config.section("politeness")
        smp = config.section("sample")
        self.gets_left = gets
        self.heads_left = heads
        self.gets_used = 0
        self.heads_used = 0
        self.bytes = 0
        self.skipped = 0
        self.delay = float(pol.get("min_delay_s", 0.5) if delay is None else delay)
        self.ua = ua or user_agent()
        self.timeout = timeout or int(smp.get("per_request_timeout_s", 20))
        self._last = 0.0

    # -- pacing --------------------------------------------------------------

    def _wait(self) -> None:
        if self.delay <= 0:
            return
        gap = time.monotonic() - self._last
        if gap < self.delay:
            time.sleep(self.delay - gap)
        self._last = time.monotonic()

    def raise_delay_to(self, seconds: float | None) -> None:
        """Honour a robots.txt Crawl-delay. Only ever slows us down."""
        if seconds:
            self.delay = max(self.delay, float(seconds))

    # -- requests ------------------------------------------------------------

    def get(self, url: str, max_bytes: int = 8_000_000):
        """Full-body GET.

        Returns (decoded_body, content_type, wire_bytes) or (None, reason, 0).
        """
        if self.gets_left <= 0:
            self.skipped += 1
            return None, "budget-exhausted", 0
        self.gets_left -= 1
        self.gets_used += 1
        self._wait()
        req = urllib.request.Request(url, headers={
            "User-Agent": self.ua,
            "Accept-Encoding": "gzip, br",
            "Accept": "*/*",
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read(max_bytes)
                self.bytes += len(raw)
                return (decompress(raw, r.headers.get("content-encoding")),
                        r.headers.get("content-type", ""), len(raw))
        except Exception as e:
            return None, f"{type(e).__name__}: {str(e)[:80]}", 0

    def head(self, url: str):
        """Headers-only probe for size accounting. Near-zero transfer.

        Returns a dict with bytes/type/etag/last_modified, or None. A server
        that refuses HEAD returns None; callers must not treat that as "not an
        asset", only as "unknown".
        """
        if self.heads_left <= 0:
            self.skipped += 1
            return None
        self.heads_left -= 1
        self.heads_used += 1
        self._wait()
        req = urllib.request.Request(url, method="HEAD", headers={
            "User-Agent": self.ua, "Accept-Encoding": "gzip, br"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                self.bytes += 400          # rough header exchange, both ways
                cl = r.headers.get("content-length")
                return {
                    "bytes": int(cl) if cl and cl.isdigit() else None,
                    "type": r.headers.get("content-type", ""),
                    "etag": r.headers.get("etag"),
                    "last_modified": r.headers.get("last-modified"),
                }
        except Exception:
            return None

    # -- reporting -----------------------------------------------------------

    @property
    def complete(self) -> bool:
        """False if anything was skipped for want of budget, which means every
        weight figure derived from this pass is a floor, not a total."""
        return self.skipped == 0

    def summary(self) -> dict:
        return {"gets_used": self.gets_used, "heads_used": self.heads_used,
                "bytes": self.bytes, "skipped_over_budget": self.skipped,
                "complete_coverage": self.complete, "delay_s": self.delay,
                "user_agent": self.ua, "ai_prompts": 0}


# --- robots.txt -------------------------------------------------------------

def check_robots(base_url: str, budget: Budget) -> dict:
    """Fetch and parse robots.txt.

    A missing or unparseable robots.txt is permission by omission, not a
    blocker. A present one that disallows us is a hard stop: whatever the ethics
    of mirroring a site you own, a tool that claims to read robots.txt and does
    not is lying to its operator.
    """
    url = urllib.parse.urljoin(base_url, "/robots.txt")
    body, _, _ = budget.get(url, max_bytes=500_000)
    if body is None:
        return {"present": False, "allowed": True, "crawl_delay": None}

    rp = urllib.robotparser.RobotFileParser()
    try:
        rp.parse(body.decode("utf-8", "ignore").splitlines())
    except Exception:
        return {"present": True, "allowed": True, "crawl_delay": None,
                "note": "robots.txt present but unparseable; proceeding politely"}

    ua = budget.ua
    try:
        allowed = bool(rp.can_fetch(ua, base_url))
    except Exception:
        allowed = True
    delay = None
    try:
        delay = rp.crawl_delay(ua)
    except Exception:
        pass
    budget.raise_delay_to(delay)
    return {"present": True, "allowed": allowed, "crawl_delay": delay,
            "parser": rp}


# --- sitemap ----------------------------------------------------------------

LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)


def sitemap_pages(base_url: str, domain: str, budget: Budget,
                  limit: int = 5000) -> list[str]:
    """Authoritative page list from /sitemap.xml, one or two requests.

    Extracts <loc> with a regex rather than an XML parser on purpose. A sitemap
    is untrusted third-party input, and a real XML parser will happily expand an
    XXE reference or a billion-laughs bomb on our behalf.
    """
    body, _, _ = budget.get(urllib.parse.urljoin(base_url, "/sitemap.xml"),
                            max_bytes=20_000_000)
    if body is None:
        return []
    text = body.decode("utf-8", "ignore")

    urls: list[str] = []
    nested: list[str] = []
    for loc in LOC_RE.findall(text):
        u = urllib.parse.urldefrag(loc.strip())[0]
        if u.lower().endswith(".xml") and "sitemap" in u.lower():
            nested.append(u)
        elif urllib.parse.urlparse(u).netloc == domain:
            urls.append(u)

    # One level of nesting only. The gate does not walk an entire sitemap index.
    for sm in nested[:1]:
        body, _, _ = budget.get(sm, max_bytes=20_000_000)
        if not body:
            continue
        for loc in LOC_RE.findall(body.decode("utf-8", "ignore")):
            u = urllib.parse.urldefrag(loc.strip())[0]
            if (urllib.parse.urlparse(u).netloc == domain
                    and not u.lower().endswith(".xml")):
                urls.append(u)

    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
        if len(out) >= limit:
            break
    return out


def pick_sample(home: str, pages: list[str], n: int) -> list[str]:
    """Homepage always, then an even spread so the sample is not all blog posts."""
    rest = [p for p in pages if p.rstrip("/") != home.rstrip("/")]
    if not rest or n <= 1:
        return [home]
    step = max(1, len(rest) // max(1, n - 1))
    return [home] + rest[::step][: n - 1]


# --- Green Web Foundation ---------------------------------------------------

GREENCHECK = "https://api.thegreenwebfoundation.org/api/v3/greencheck/"


def greencheck(domain: str, budget: Budget) -> dict:
    """Green Web Foundation lookup.

    One of exactly two network calls this project makes beyond fetching the
    sample. When it is unreachable we assume NOT green, which overstates the
    saving a migration would deliver, so the verdict stays conservative in the
    user's favour rather than ours.
    """
    if not domain:
        return {"green": False, "checked": False, "domain": domain,
                "note": "no domain to check"}
    body, _, _ = budget.get(GREENCHECK + domain, max_bytes=200_000)
    if body is None:
        return {"green": False, "checked": False, "domain": domain,
                "note": "greencheck unreachable; assuming NOT green, which "
                        "overstates a migration's benefit rather than "
                        "understating it"}
    try:
        import json
        d = json.loads(body.decode("utf-8", "ignore"))
        return {"green": bool(d.get("green")), "checked": True,
                "domain": domain,
                "hosted_by": d.get("hosted_by") or d.get("hostedby")}
    except Exception:
        return {"green": False, "checked": False, "domain": domain,
                "note": "greencheck response unparseable"}
