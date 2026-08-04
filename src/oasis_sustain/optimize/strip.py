"""
Identifying third-party JavaScript that can simply be deleted.

This is the highest-leverage optimizer in the set and the only one that reaches
zero bytes. A tag manager, an analytics bundle and a consent banner routinely
outweigh everything a site's own code ships, and none of them survive a move to
a static mirror in any useful form.

The cheapest request is the one never made. Deleting work beats optimizing work,
so this runs before anything tries to compress these files.

Matching is by URL substring against a configured list, which is crude on
purpose: it is auditable, it cannot misfire on content, and a false negative
only costs us an unclaimed saving. A false POSITIVE would silently break a site,
so the list holds only well-known third-party services, never generic patterns
that could match a site's own bundle.
"""
from __future__ import annotations

# Kept in sync with the `strippable_js_patterns` list in defaults.json. This
# tuple is the fallback when no config is loaded.
DEFAULT_PATTERNS = (
    # tag managers and analytics
    "googletagmanager.com", "google-analytics.com", "analytics.google.com",
    "googleadservices.com", "googlesyndication.com", "doubleclick.net",
    "connect.facebook.net", "facebook.com/tr", "bat.bing.com",
    "snap.licdn.com", "static.ads-twitter.com",
    # session recording and product analytics
    "hotjar.com", "hotjar.io", "clarity.ms", "fullstory.com",
    "mixpanel.com", "segment.com", "segment.io", "cdn.segment",
    # marketing automation and chat
    "hs-scripts.com", "hsforms", "hubspot", "intercom.io", "intercomcdn",
    # consent management
    "onetrust", "cookielaw.org",
)


def patterns(configured=None) -> tuple[str, ...]:
    if configured:
        return tuple(configured)
    return DEFAULT_PATTERNS


def is_strippable(url: str, configured=None) -> bool:
    """True when this URL is a known third-party service safe to drop."""
    if not url:
        return False
    u = url.lower()
    return any(p in u for p in patterns(configured))


def classify_all(urls, configured=None) -> dict:
    """Split a list of script URLs into strippable and needed.

    Returned so a report can name what would be removed rather than presenting
    an unexplained byte count.
    """
    pats = patterns(configured)
    strippable, needed = [], []
    for u in urls:
        (strippable if is_strippable(u, pats) else needed).append(u)
    return {"strippable": strippable, "needed": needed}
