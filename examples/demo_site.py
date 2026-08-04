#!/usr/bin/env python3
"""
Generate and serve a synthetic demo site, so the README's numbers are
reproducible by anyone and belong to nobody.

    python examples/demo_site.py            # serves on http://127.0.0.1:8207
    oasis-sustain check http://127.0.0.1:8207/ --i-own-this --monthly-views 25000

Everything is generated at runtime rather than committed, so the repository
carries no image binaries. It is deliberately shaped like a small CMS site:

  - an oversized PNG logo dropped into a 280px slot, which is the most common
    real-world waste and the one resizing fixes outright
  - a photographic hero far larger than its display width
  - a builder theme stylesheet where most rules belong to widgets this page
    never uses, which is what the CSS purge finds
  - two third-party scripts (a tag manager and a session recorder), which the
    optimizer deletes rather than compresses

The server gzips text, because real hosts do. Serving text uncompressed would
make our brotli "after" look far better than it is, and comparing a raw before
against a compressed after is precisely the manufactured saving this project
exists to argue against.

A synthetic fixture is not a benchmark. Real sites vary enormously, which is why
the tool measures each one rather than applying a ratio.
"""
from __future__ import annotations

import functools
import gzip
import http.server
import io
import os
import random
import sys
import tempfile
from pathlib import Path

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8207

WIDGETS = [
    "carousel", "lightbox", "accordion", "megamenu", "pricing-table",
    "testimonial", "countdown", "parallax", "tabs", "modal", "tooltip",
    "breadcrumb", "pagination", "gallery", "video-embed", "social-bar",
    "newsletter", "search-overlay", "cart", "product-grid", "review-stars",
    "booking-widget", "map-embed", "chat-bubble",
]

PAGE_CSS = """\
:root { --brand: #1a5c44; --ink: #22282a; }
body { margin: 0; font-family: system-ui, sans-serif; color: var(--ink); }
.masthead { display: flex; align-items: center; gap: 1.5rem; padding: 2rem; }
.masthead__logo { max-width: 280px; height: auto; }
.hero { display: grid; place-items: center; min-height: 60vh; }
.hero__image { width: 100%; height: auto; object-fit: cover; }
.hero__title { font-size: clamp(2rem, 5vw, 3.5rem); margin: 0; }
.card-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr)); gap: 1.5rem; padding: 2rem; }
.card { border: 1px solid #dde5e1; border-radius: 12px; padding: 1.25rem; }
.card__title { margin: 0 0 .5rem; color: var(--brand); }
.footer { padding: 3rem 2rem; background: #f4f7f5; }
"""

INDEX_HTML = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Riverbend Community Garden</title>
<meta name="description" content="A volunteer-run community garden and seed library.">
<link rel="stylesheet" href="/assets/theme.css">
<script async src="https://www.googletagmanager.com/gtag/js?id=G-DEMO"></script>
<script async src="https://static.hotjar.com/c/hotjar-000000.js"></script>
</head>
<body>
<header class="masthead">
  <img class="masthead__logo" src="/assets/site-logo.png" width="280"
       alt="Riverbend Community Garden">
</header>
<main>
  <section class="hero">
    <img class="hero__image" src="/assets/hero-banner.jpg" width="1200"
         alt="Raised beds in early summer">
    <h1 class="hero__title">Grow with us</h1>
  </section>
  <div class="card-grid">
    <article class="card"><h2 class="card__title">Seed library</h2>
      <p>Borrow, grow, return.</p></article>
    <article class="card"><h2 class="card__title">Work parties</h2>
      <p>Second Saturday, every month.</p></article>
    <article class="card"><h2 class="card__title">Plot waitlist</h2>
      <p>Currently about four months.</p></article>
  </div>
</main>
<footer class="footer"><p>Riverbend Community Garden</p></footer>
</body>
</html>
"""


def build(root: Path) -> None:
    from PIL import Image, ImageFilter

    assets = root / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text(INDEX_HTML, encoding="utf-8")

    # Theme stylesheet: a handful of used rules, then hundreds of widget rules
    # this page never touches.
    unused = []
    for widget in WIDGETS:
        for i in range(1, 9):
            unused.append(f".sqs-{widget}__part-{i} {{ position: relative; "
                          f"padding: {i}px; margin: {i}px 0; "
                          f"border-color: #cfd8d3; }}")
            unused.append(f".sqs-{widget}__part-{i}--active {{ opacity: 1; "
                          f"transform: translateY(0); }}")
    (assets / "theme.css").write_text(PAGE_CSS + "\n".join(unused) + "\n",
                                      encoding="utf-8")

    rng = random.Random(3)

    # Hero: textured, so a lossy codec cannot cheat the way it can on a smooth
    # gradient. Stored at 2400px wide but displayed at 1200.
    w, h = 2400, 1400
    hero = Image.new("RGB", (w, h))
    px = hero.load()
    for y in range(h):
        for x in range(w):
            leaf = 55 + int(70 * (((x * 7) ^ (y * 13)) % 32) / 32)
            px[x, y] = (leaf + rng.randint(-28, 28),
                        90 + int(60 * (y / h)) + rng.randint(-30, 30),
                        45 + rng.randint(-22, 22))
    hero.filter(ImageFilter.GaussianBlur(0.4)).save(
        assets / "hero-banner.jpg", quality=88)

    # Logo: flat colour, stored at 1600px, displayed at 280.
    logo = Image.new("RGBA", (1600, 500), (255, 255, 255, 0))
    lp = logo.load()
    for y in range(500):
        for x in range(1600):
            if 60 < y < 440 and (x // 90) % 2 == 0 and 80 < x < 1520:
                lp[x, y] = (26, 92, 68, 255)
    logo.save(assets / "site-logo.png")


TEXTY = ("text/", "javascript", "json", "xml")


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_head(self):
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            path = os.path.join(path, "index.html")
        if not os.path.isfile(path):
            self.send_error(404)
            return None
        body = Path(path).read_bytes()
        ctype = self.guess_type(path)
        gz = (any(t in ctype for t in TEXTY)
              and "gzip" in self.headers.get("Accept-Encoding", ""))
        if gz:
            body = gzip.compress(body, 6)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if gz:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        return io.BytesIO(body)


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="oasis-demo-"))
    print(f"building demo site in {root} ...")
    build(root)
    total = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
    print(f"built, {total:,} bytes on disk\n")
    print(f"  serving  http://127.0.0.1:{PORT}/   (text served gzipped)\n")
    print(f"  oasis-sustain check http://127.0.0.1:{PORT}/ \\")
    print("      --i-own-this --monthly-views 25000\n")
    print("  Ctrl-C to stop.")
    handler = functools.partial(Handler, directory=str(root))
    try:
        http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler).serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
