"""
The optimizers, and the two rules that keep them honest.

Rule 1: wire bytes on both sides. Never compare a compressed before against an
        uncompressed after.
Rule 2: never return a result larger than the input.

Offline. Fixtures are generated in-process so the suite carries no binaries.
"""
import io

import pytest

from oasis_sustain import optimize
from oasis_sustain.optimize import css, html, images, strip

# --- fixtures ---------------------------------------------------------------

def photo_bytes(w=2400, h=1600, fmt="JPEG", quality=92) -> bytes:
    """A smooth gradient, which is what real photographs mostly are and what
    lossy codecs are built for."""
    from PIL import Image
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = ((x * 255) // w, (y * 255) // h, ((x + y) * 255) // (w + h))
    buf = io.BytesIO()
    im.save(buf, format=fmt, quality=quality)
    return buf.getvalue()


def tiny_png() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (1, 1), (128, 64, 32)).save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def noise_png(w=600, h=400) -> bytes:
    """Pixel noise stored losslessly. Lossy codecs are built for smooth content
    and blow UP on noise, so this is a genuine 'nothing beats the source' case
    rather than a contrived one."""
    import random

    from PIL import Image
    rng = random.Random(7)
    im = Image.new("RGB", (w, h))
    im.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256))
                for _ in range(w * h)])
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


SAMPLE_HTML = b"""<!doctype html><html><head><title>t</title>
<!-- a comment that should go -->
</head><body><div class="hero used"><p id="lead">hello</p></div>


</body></html>"""

SAMPLE_CSS = """
.hero { display: grid; gap: 1rem; }
.used { color: #123456; }
#lead { font-size: 2rem; }
.never-appears-anywhere { color: red; }
.also-unused { border: 1px solid blue; }
@media (min-width: 40em) { .hero { gap: 2rem; } }
@font-face { font-family: X; src: url(x.woff2); }
"""


# --- rule 2: never larger than the input ------------------------------------

def test_noisy_image_keeps_the_source_rather_than_growing():
    """Lossy re-encoding noise produces a BIGGER file. The upstream engine
    shipped exactly that and reported it as '-297% smaller'."""
    data = noise_png()
    r = optimize.optimize("images", data, context={"quality": 90})
    assert r.after <= r.before
    assert r.reduction_pct >= 0


def test_central_guard_catches_any_backend_that_grows_a_file():
    """Rule 2 is enforced in optimize(), not left to each backend to remember.
    A source served far smaller than we can re-encode it must come back
    untouched, with the reason stated."""
    r = optimize.optimize("images", photo_bytes(), wire_before=100)
    assert r.after == 100
    assert r.reduction_pct == 0
    assert any("already optimal" in n for n in r.notes)
    assert "source kept" in r.method


def test_no_optimizer_can_ever_report_a_negative_saving():
    for kind, data in (("images", noise_png()),
                       ("images", tiny_png()),
                       ("css", b"a{}"),
                       ("html", b"<p>hi</p>"),
                       ("js", b"x=1"),
                       ("other", b"\x00\x01\x02")):
        r = optimize.optimize(kind, data)
        assert r.after <= r.before, f"{kind} grew: {r.before} -> {r.after}"
        assert r.saved >= 0
        assert r.reduction_pct >= 0


def test_incompressible_payload_is_left_alone():
    import os
    noise = os.urandom(40_000)          # brotli cannot beat random data
    r = optimize.optimize("other", noise)
    assert r.after <= r.before


# --- rule 1: wire bytes on both sides ---------------------------------------

def test_wire_before_overrides_raw_length():
    """`before` must be what crossed the network, not the decompressed size."""
    raw = SAMPLE_HTML * 40
    r = optimize.optimize("html", raw, wire_before=1234)
    assert r.before == 1234


def test_text_after_is_compressed_not_raw():
    """A brotli-sized after against a brotli-sized before is a fair comparison;
    a raw after would invent a saving."""
    raw = SAMPLE_CSS.encode() * 50
    r = optimize.optimize("css", raw)
    assert r.after < len(raw)
    import brotli
    assert r.after <= len(brotli.compress(raw, quality=5)) * 1.2


# --- images -----------------------------------------------------------------

def test_photo_shrinks_substantially():
    r = optimize.optimize("images", photo_bytes(), context={"quality": 65})
    assert r.reduction_pct > 50


def test_resizing_to_rendered_width_beats_encoding_alone():
    """Not shipping a 2400px original into an 800px slot is the bigger win."""
    data = photo_bytes()
    full = optimize.optimize("images", data, context={"max_width": 2400})
    small = optimize.optimize("images", data, context={"max_width": 800})
    assert small.after < full.after


def test_avif_is_actually_produced_when_requested():
    """AVIF sat in the upstream config for months and was never emitted."""
    data = photo_bytes()
    r = optimize.optimize("images", data, context={"formats": ["avif"],
                                                   "quality": 40})
    assert "avif" in r.method
    assert r.after < r.before


def test_smallest_format_wins():
    data = photo_bytes()
    both = optimize.optimize("images", data,
                             context={"formats": ["avif", "webp"], "quality": 50})
    webp = optimize.optimize("images", data,
                             context={"formats": ["webp"], "quality": 50})
    assert both.after <= webp.after


def test_non_image_bytes_do_not_crash_the_image_path():
    r = optimize.optimize("images", b"this is definitely not an image")
    assert r.after <= r.before


def test_rendered_width_reads_the_markup():
    assert images.rendered_width('<img width="800"><img width="1200">') == 1200
    assert images.rendered_width("<img>") == 0          # 0 means "unknown"
    assert images.rendered_width('<img width="99999">') == 0   # implausible


# --- css --------------------------------------------------------------------

def test_purge_drops_only_provably_unused_rules():
    tokens = css.html_tokens(SAMPLE_HTML.decode())
    out, kept, dropped = css.purge(SAMPLE_CSS, tokens)
    assert dropped == 2                       # .never-appears-anywhere, .also-unused
    assert ".hero" in out and ".used" in out and "#lead" in out


def test_purge_never_touches_at_rules():
    tokens = {"nothing-matches"}
    out, _, _ = css.purge(SAMPLE_CSS, tokens)
    assert "@media" in out and "@font-face" in out


def test_purge_keeps_rules_with_no_class_or_id_hook():
    out, _, dropped = css.purge("body { margin: 0 } a { color: blue }", set())
    assert dropped == 0
    assert "body" in out and "a" in out


def test_html_tokens_collects_classes_ids_and_tags():
    t = css.html_tokens(SAMPLE_HTML.decode())
    assert {"hero", "used", "lead", "div", "p"} <= t


def test_purge_reports_what_it_removed():
    r = optimize.optimize("css", SAMPLE_CSS.encode(),
                          context={"html_tokens": css.html_tokens(
                              SAMPLE_HTML.decode())})
    assert "purged 2 unused rule" in r.method


def test_unparseable_css_is_left_alone_rather_than_mangled():
    out, _, dropped = css.purge("}{ this is not css {{{", set())
    assert dropped == 0


# --- html -------------------------------------------------------------------

def test_minify_strips_comments_but_keeps_conditional_ones():
    assert "should go" not in html.minify("<!-- should go -->x")
    assert "[if IE]" in html.minify("<!--[if IE]>x<![endif]-->")


def test_minify_leaves_one_space_between_tags():
    """Deleting inter-tag whitespace entirely moves rendered inline text."""
    assert html.minify("<b>a</b>     <i>b</i>") == "<b>a</b> <i>b</i>"


# --- strip ------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://www.googletagmanager.com/gtm.js?id=GTM-XYZ",
    "https://static.hotjar.com/c/hotjar-123.js",
    "https://cdn.cookielaw.org/consent/otSDKStub.js",
])
def test_known_third_party_scripts_are_strippable(url):
    assert strip.is_strippable(url)


@pytest.mark.parametrize("url", [
    "https://example.com/assets/app.bundle.js",
    "https://example.com/js/main.js",
    "https://cdn.example.com/vendor/jquery.min.js",
])
def test_first_party_scripts_are_never_stripped(url):
    """A false positive here silently breaks a site, so this list must stay
    specific to named third-party services."""
    assert not strip.is_strippable(url)


def test_stripping_reaches_zero_bytes():
    r = optimize.optimize("js", b"var _gtm = 1;" * 500,
                          url="https://www.googletagmanager.com/gtm.js")
    assert r.after == 0
    assert r.reduction_pct == 100
    assert "removed" in r.method


def test_needed_js_is_compressed_not_claimed_as_minified():
    """We do not assert an esbuild win we have not measured."""
    r = optimize.optimize("js", b"function a(){return 1}" * 200,
                          url="https://example.com/app.js")
    assert r.after < r.before
    assert "no transform" in r.method


def test_classify_all_splits_and_names_both_sides():
    out = strip.classify_all(["https://googletagmanager.com/gtm.js",
                              "https://example.com/app.js"])
    assert len(out["strippable"]) == 1 and len(out["needed"]) == 1


# --- classification ---------------------------------------------------------

@pytest.mark.parametrize("url,ctype,want", [
    ("https://x.com/a.css", "", "css"),
    ("https://x.com/a", "text/css; charset=utf-8", "css"),
    ("https://x.com/a.js", "", "js"),
    ("https://x.com/a.woff2", "", "fonts"),
    ("https://x.com/a.png", "", "images"),
    ("https://x.com/a", "image/avif", "images"),
    ("https://x.com/page/", "text/html", "html"),
    ("https://x.com/data.bin", "", "other"),
])
def test_classify(url, ctype, want):
    assert optimize.classify(url, ctype) == want


def test_result_serializes_for_the_report():
    d = optimize.optimize("html", SAMPLE_HTML).as_dict()
    assert set(d) >= {"kind", "before", "after", "saved", "reduction_pct", "method"}


# --- per-image widths (regression: page-wide max oversold savings) ----------

WIDTH_HTML = """
<img src="/logo.png" width="100" alt="logo">
<img src="/hero.jpg" alt="hero">
<img src="/card.jpg" width="600" alt="card">
"""


def test_declared_widths_are_per_image_not_page_wide():
    """A page whose only width attribute sits on a 100px logo must NOT cause a
    full-bleed hero to be 'resized' to 100px. That bug reported a 98% saving
    nobody could deliver, on a real site."""
    w = images.declared_widths(WIDTH_HTML, "https://site.test/page/")
    assert w["https://site.test/logo.png"] == 100
    assert w["https://site.test/card.jpg"] == 600
    # Sized by CSS: absent, so the caller falls back to its configured maximum
    # rather than inheriting the logo's 100px.
    assert "https://site.test/hero.jpg" not in w


def test_declared_widths_keep_the_larger_when_an_image_repeats():
    w = images.declared_widths(
        '<img src="/a.png" width="200"><img src="/a.png" width="800">',
        "https://site.test/")
    assert w["https://site.test/a.png"] == 800


def test_declared_widths_ignore_spacer_and_absurd_values():
    w = images.declared_widths(
        '<img src="/s.gif" width="1"><img src="/x.png" width="99999">',
        "https://site.test/")
    assert w == {}
