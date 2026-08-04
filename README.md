# oasis-sustain

**Is optimizing this website worth the carbon it costs?**

Most web-carbon tooling will produce a number for any URL you give it. This one
is built to say no.

It runs a cheap sample pass, measures what a real optimizer actually achieves on
your real bytes, works out how long the one-time cost takes to pay back, and
returns one of five verdicts. Two of them are refusals.

```console
$ oasis-sustain check https://example.org --i-own-this --monthly-views 300

  VERDICT: DIMINISHING RETURNS
    This pays back, but the whole stake is 0.5 kg/year, about 0.02 of
    one tree. Do it for speed, accessibility or hosting cost if you
    like. Do not sell it as a carbon win.
```

That verdict is the point. Same site at 25,000 views a month is a clear win; at
300 it is not worth claiming, and the tool says so rather than printing a number
you could put in a deck.

---

## Why this exists

An audit of a site-mirroring pipeline found three things:

- Its carbon model was **Sustainable Web Design v3** while its documentation
  cited the current model, so every figure it had ever published was **2.4x too
  high**.
- Its report generator **defaulted to 10,000 monthly views**, so it would print
  a hard annual tree count for sites whose traffic nobody had measured.
- The "worth it?" gate and the self-metering, the two features it described as
  its differentiator, **did not exist**.

This package is those features, built properly and separately, so they can be
used by anything and audited by anyone.

## Install

```console
pip install git+https://github.com/Gabriel-Dalton/oasis-localize-sustainability
```

Python 3.10+. Three dependencies, all permissively licensed: Pillow, Brotli,
tinycss2. No Node, no browser, no API key.

## Use

```console
# The question this tool exists to answer
oasis-sustain check <url> --i-own-this --monthly-views 5000

# No analytics figure? Say so. Every number comes back watermarked ILLUSTRATIVE.
oasis-sustain check <url> --i-own-this

# Verify where you would move it to, so the green-hosting bonus is real
oasis-sustain check <url> --i-own-this --monthly-views 5000 --destination pages.dev

# Planning an AI-assisted rebuild? See it priced against the alternative.
oasis-sustain check <url> --i-own-this --monthly-views 5000 \
    --pipeline ai --ai-prompts 2000 --ai-kind heavy

# A shareable, fully self-contained page
oasis-sustain check <url> --i-own-this --monthly-views 5000 \
    --format html --out report.html

# Every constant and assumption behind every figure
oasis-sustain model
```

### Exit codes

| Code | Meaning |
|---:|---|
| `0` | Proceed. Clear win, or worthwhile if content is stable |
| `1` | Advised against. Diminishing returns, or do not do this for carbon |
| `2` | Blocked. No ownership attestation, robots.txt, or a login wall |

A non-zero exit is not an error. It is the tool doing its job.

---

## What makes it different

### It measures instead of modelling

The projection is not a compression ratio someone guessed. The gate runs the
real encoders on your real bytes:

```
  OPTIMIZER TRIALS (the real encoders, on your real bytes)
    theme.css              1,947 ->      309 B  (84%)  purged 384 unused rule(s) + minify + brotli
    site-logo.png          4,412 ->    2,490 B  (44%)  avif q65, resized to <=1200px
    hero-banner.jpg    1,188,480 ->   21,854 B  (98%)  webp q65, resized to <=1200px
```

Reproduce that yourself in two commands, no account and no real site needed:

```console
python examples/demo_site.py                     # builds and serves a demo site
oasis-sustain check http://127.0.0.1:8207/ --i-own-this --monthly-views 25000
```

The demo is generated at runtime, so the repo carries no image binaries, and it
serves text gzipped because real hosts do. **A synthetic fixture is not a
benchmark**: that 98% is what happens when a 2400px photo is dropped into a
1200px slot, and real sites vary enormously. Measuring each one instead of
applying a ratio is the entire point.

And the optimizers that **measure** are the optimizers that **ship**. The same
functions do the real work later, so the gate can never promise a saving the
pipeline has no code to deliver.

### It always gives two numbers

Savings are quoted as a range: the Sustainable Web Design v4 model figure and a
conservative bound that drops the network segment (24% of the model), because
network energy barely scales with marginal bytes. That 24% is derived from the
model's own segment table at runtime, not hardcoded.

A point value would claim precision the model does not have.

### It will not invent your traffic

There is no default. Without `--monthly-views` you get placeholder mode, and the
HTML report stamps ILLUSTRATIVE across the page in CSS rather than in a caption
that could be cropped out of a screenshot.

### It prices AI honestly

Declare an AI-assisted pipeline and the same site flips verdict:

| Pipeline | One-time cost | Payback |
|---|---:|---:|
| Deterministic | 0.021 kg | **1.2 days** |
| AI-assisted (2,000 heavy prompts) | 4.961 kg (100% is the AI) | **280 days** |

Identical end state. The AI does not change what the optimized site saves; it
only inflates the one-time cost by **238x**, turning a one-day payback into a
nine-month one.

**There is no AI anywhere in the decision path**, by construction and by test.
The verdict is arithmetic on measured bytes, so it is reproducible and
defensible to a sceptical client.

### It meters itself

```
  THIS RUN'S OWN FOOTPRINT
    0.50 Wh  ~  0.25 g CO2e (conservative 0.21 g)
    transfer 0.18 g + compute 0.07 g
    1,197,518 bytes transferred, 8 s machine time, 0 AI prompt(s)
    compute assumes 65 W (an assumption, not a measurement)
```

A quarter of a gram to identify a 44 kg annual saving on the demo site: well
under a thousandth of one year's benefit. A tool that audits other people's
energy and hides its own has no standing.

### Every figure is traceable

The model version, grid-intensity assumption and date ship with every number, in
every format, including on refusals. `METHODOLOGY.md` documents every constant,
every assumption, and every place this deliberately differs from the sources it
cites, including one where our figure is **less** conservative than the spec it
came from.

---

## Building this cost 3.94 Wh

Measured with the tool, across development of v1.0: **3.94 Wh, about 1.95 g
CO2e** (conservative 1.72 g), from 6.4 MB transferred and 112 seconds of machine
time. No AI prompts in any metered stage.

That excludes the assistant time spent writing the code, which is the honest
caveat: the number covers what the *tool* did, not what it took to build it. We
would rather publish a partial number with its boundary stated than none at all.

Choices made to keep it small:

- CI is one job on two platforms with one Python version. A 3-OS x 4-version
  matrix would burn twelve runners to learn nearly the same thing twelve times.
- The test suite is fully offline, so it can run on every save without a
  request.
- The whole product makes exactly two kinds of network call: fetching the
  sample, and the Green Web Foundation greencheck.

## Development

```console
pip install -e ".[dev]"
pytest          # 111 tests, fully offline
ruff check src tests
```

The suite includes a **honesty regression gate**: it fails if any renderer drops
the two-number range, omits the model footer, loses the ILLUSTRATIVE watermark,
or introduces an external request into the HTML report. Those four things were
all missing upstream. Tests are how they stay fixed.

## Licence

Apache-2.0. See [`LICENSE`](./LICENSE).

Built for [Oasis of Change](https://oasisofchange.com). Companion to the Oasis
Localize site-mirroring engine, which calls this to decide whether to run at all.
