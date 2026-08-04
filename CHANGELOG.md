# Changelog

## 1.0.0 - 2026-08-03

First release. The honesty layer for the Oasis Localize site-mirroring engine,
extracted so it stands on its own and can be audited by anyone.

### The gate

- `oasis-sustain check` - cheap sample pass (homepage plus up to four pages,
  hard request budget, zero AI) returning one of five verdicts, two of which are
  refusals. Exit codes carry the verdict so a pipeline can branch on them.
- Runs the **real optimizers** on the sampled bytes rather than modelling a
  compression ratio. The functions that measure are the functions that ship.
- Ownership attestation, robots.txt (Disallow honoured, Crawl-delay applied) and
  login-wall detection, any of which can block a run before a single figure is
  produced.
- Green Web Foundation greencheck on the source **and** on the destination. The
  green-hosting bonus is refused when the destination does not verify.

### The carbon model

- Sustainable Web Design **v4** (0.30 kWh/GB full-system), one implementation,
  mirroring the `@tgwf/co2` segment constants. Replaces the SWD **v3** constants
  the upstream engine carried in two separate files, which inflated every
  published figure by 2.42x.
- **Two numbers, always.** Model figure plus a conservative bound that drops the
  network segment. The 0.76 factor is derived from the segment table at runtime,
  so revising the model revises the bound.
- Model version, grid-intensity assumption and date ship with every figure, in
  every format, including on refusals.

### Self-metering

- `oasis-sustain meter` - per-run ledger of bytes transferred, machine seconds,
  AI prompts by kind and browser launches, reported as Wh and gCO2e with the
  assumptions printed alongside.

### Deterministic optimizers

- Images: AVIF **and** WebP, resized to the width the markup actually declares,
  smaller wins. (The upstream engine had AVIF in its config from the start and
  never emitted one.)
- CSS: token-based unused-rule purge, minify, brotli. Conservative by design;
  at-rules and hook-less selectors always survive.
- HTML: comment and whitespace minify, brotli.
- JS: third-party removal reaching zero bytes. **No minification win claimed**,
  because production bundles arrive minified and asserting an unmeasured saving
  is the overselling this project exists to prevent.
- Two invariants enforced centrally: wire bytes on both sides of every
  comparison, and never return a result larger than the input.

### Honesty rules, enforced by tests

- No annualized claim without operator-supplied traffic. No default. Placeholder
  mode watermarks the HTML in CSS, not in a croppable caption.
- A declared AI pipeline is always shown beside the deterministic alternative.
- Budget exhaustion is disclosed, because it makes the measured weight a floor.
- The HTML report makes **no external requests**. No webfonts, no CDN.
- 111 offline tests, including the design spec's worked examples and a
  regression gate on each rule above.

### Known limitations

- Font subsetting and JS bundling are not implemented, so no saving is claimed
  for either.
- Compute is wall-clock at a stated wattage, not measured CPU time. Python
  cannot reliably attribute subprocess CPU on Windows, and it is labelled an
  assumption everywhere it is printed.
- Delta re-crawl cost assumes 10% of pages change. It becomes a measurement once
  the engine implements ETag-based delta crawls.
