# Methodology

Every constant, every assumption, and every place we deliberately differ from
the sources we cite. If a figure this tool prints cannot be traced back to
something on this page, that is a bug.

Run `oasis-sustain model` to print the live version of all of this, including
which config files contributed.

---

## 1. The carbon model

**Sustainable Web Design v4**, implemented in `src/oasis_sustain/carbon.py`.

SWD v4 splits energy per gigabyte of data transfer across three system segments,
each with an operational and an embodied component:

| Segment | Operational | Embodied | Total | Share |
|---|---:|---:|---:|---:|
| Datacenter | 0.055 | 0.012 | 0.067 kWh/GB | 22.3% |
| Network | 0.059 | 0.013 | 0.072 kWh/GB | 24.0% |
| User device | 0.080 | 0.081 | 0.161 kWh/GB | 53.7% |
| **Total** | 0.194 | 0.106 | **0.300 kWh/GB** | 100% |

These are the same segment constants the CO2.js implementation of SWD v4 uses
(`@tgwf/co2`, `SustainableWebDesign` model).

### Why this is not a CO2.js wrapper

We implement the arithmetic in Python rather than shelling out to Node. Two
reasons, both about keeping the tool honest and small:

1. **It stays runnable offline with no install.** The only two network calls in
   the entire product are fetching the sample and the Green Web Foundation
   greencheck. Adding a Node runtime to compute multiplication would be a strange
   thing for a project about unnecessary energy use to do.
2. **The constants are visible.** They sit in one table in one file, so anyone
   can check a printed figure against the published model by hand.

The trade-off is real and worth stating: if CO2.js revises its constants, we do
not get that automatically. `CO2JS_EQUIVALENT` in `carbon.py` records which
release we mirror, and it must be bumped alongside `SEGMENTS`.

### Grid intensity

Default **494 gCO2e/kWh**, the global average from the Ember Global Electricity
Review. Override per region with `--grid`, `OASIS_GRID_G_PER_KWH`, or
`carbon.grid_g_per_kwh` in config. When overridden, the footer says
"operator-supplied" instead of naming Ember, so a regional figure is never
mistaken for the published global one.

---

## 2. Two numbers, always

The model attributes a full share of network and device energy to every marginal
byte. That is not how the network behaves. Routers, transit and last-mile
equipment draw close to the same power whether a page is 1.6 MB or 0.9 MB, so
shaving bytes does not linearly shave network energy.

So every public figure is a **range**:

- **Model figure** - the full SWD v4 result.
- **Conservative bound** - the same result with the network segment removed
  (24.0% of the model), i.e. multiplied by **0.76**.

That 0.76 is *derived from the segment table at runtime*, not written down as a
literal. If the segment constants ever change, the bound follows automatically.
A test pins this (`test_marginal_factor_is_derived_not_hardcoded`).

Reality sits somewhere in the range. Quoting either end alone overstates our
confidence, so the tool quotes both, everywhere, including in the JSON output.

---

## 3. Green hosting, and where we differ from the original spec

Verified green hosting does **not** delete the datacenter segment. It changes
the grid intensity applied to the datacenter *operational* share only. Embodied
datacenter energy, the network, and the user's device are all unaffected by who
powers the server.

```
bonus = (datacenter operational share) x (1 - green_grid / grid)
      = (0.055 / 0.300)                x (1 - 50 / 494)
      = 0.183                          x 0.899
      = 16.5%
```

**The original Oasis Localize design spec asserted a flat 9%.** We derive 16.5%
instead, and that difference deserves to be called out rather than buried,
because **it makes savings look larger**, which is the direction that warrants
the most scepticism.

Two ways to take the conservative line if you prefer it:

| You want | Set |
|---|---|
| The derived model figure (default) | `green_grid_g_per_kwh: 50` -> 16.5% |
| The design spec's asserted figure | `green_grid_g_per_kwh: 245` -> ~9% |

The green-hosting bonus is also printed as its **own line item** in every
report, so a reader can subtract it without recomputing anything.

### The destination must be verified

The payback model credits this bonus for *migrating* a site. That bonus is only
real if the place the site moves **to** is actually green. The gate therefore
greenchecks the destination as well as the source:

```
oasis-sustain check https://site.example --i-own-this \
    --monthly-views 5000 --destination pages.dev
```

Without `--destination` the bonus is credited on the stated assumption that the
target host is GWF-verified, and the report says so in those words. If a
destination is given and does **not** verify, the bonus is refused outright.

### When greencheck is unreachable

We assume **not green**. That overstates what a migration would deliver, which
means the verdict errs in the user's favour rather than ours. Stated in the
report whenever it happens.

---

## 4. Measuring the "after"

The projection is not a modelled compression ratio. The gate runs the **real
optimizers** on the site's **real bytes**, and the pipeline that later does the
work calls the same functions. The projection cannot drift from the delivery.

| Kind | What runs | Notes |
|---|---|---|
| Images | Pillow, AVIF and WebP, resized to the largest width the markup declares | Smaller of the two wins. Resizing usually beats re-encoding. |
| CSS | Token-based unused-rule purge, whitespace minify, brotli | Conservative: at-rules and hook-less selectors always survive |
| HTML | Comment and whitespace minify, brotli | Small next to images; we say so rather than padding with it |
| JS | Third-party removal, then brotli | **No minification claimed.** See below |
| Fonts | Nothing yet | Subsetting is not implemented, so no saving is claimed |

### Two rules that keep the measurement honest

1. **Wire bytes on both sides.** `before` is what actually crossed the network,
   already compressed by the host. `after` is therefore also measured
   compressed. Comparing a gzipped before against a raw after would manufacture
   a saving out of nothing.
2. **Never larger than the input.** "Already optimal" is a real and common
   outcome, especially for noisy images where lossy codecs *grow* the file.
   Enforced centrally in `optimize()`, not left to each backend to remember.

### Why we do not claim a JavaScript minification win

Production bundles arrive already minified. Asserting an esbuild saving we have
not measured is precisely the overselling this project exists to prevent. All we
measure on JS is the compression the host applies anyway, plus the bytes we can
**delete** entirely.

### Deleting beats optimizing

The largest single saving on most sites is removing third-party scripts: tag
managers, analytics, session recorders, consent banners. These reach **zero**
bytes, which no compressor can match, and none of them survive a move to a
static mirror in useful form anyway.

Matching is by URL substring against a named list (`optimize/strip.py`). Crude
on purpose: it is auditable, it cannot misfire on file contents, and a false
negative only costs an unclaimed saving. A false **positive** would silently
break a site, so the list contains only well-known third-party services and
never generic patterns that could match first-party code.

---

## 5. The payback model

```
Recurring saving   S = V x [ (W_before - W_after) x I  +  W_after x green_bonus ]
One-time cost      C = crawl + compute + AI + deploy
Recurring cost     R = recrawls x (delta crawl + CI)
Net monthly        N = S - R
Payback            P = C / N            (infinite when N <= 0)
```

| Term | Default | Basis |
|---|---|---|
| `V` repeat-visit factor | 0.85 | Blended discount for warm-cache returning views. **An assumption**, not a measurement; the true blend depends on the site's new/returning split |
| Crawl cost | pages x W_before | Doubled when the page proves client-rendered, because a faithful mirror then needs the headless path |
| Compute | 15 CPU-min once, 2 per re-crawl, at 65 W | Wall-clock at a stated draw. See below |
| Delta re-crawl | 10% of pages change | Stated assumption. Becomes a measurement once the pipeline implements ETag-based delta crawls |
| Deploy | 1 g CO2e | Order-of-magnitude placeholder |
| Tree equivalent | 21 kg CO2/tree/year | Oasis of Change's own planting figure |

### AI energy per prompt

| Kind | Wh |
|---|---:|
| Short chat prompt | 0.34 |
| Long-context prompt | 2.5 |
| Heavy agentic step | 5.0 |
| Full agentic session | 41 |

Order-of-magnitude figures. The gate's conclusions are insensitive to their
precision, because the gap between an AI-assisted and a deterministic pipeline
is two to three orders of magnitude, not a few percent.

### Why compute is wall-clock, not CPU time

Python cannot reliably attribute a subprocess's CPU time on Windows
(`os.times()` reports zero for children), and nearly all of a real pipeline's
compute is in subprocesses: ffmpeg, Chromium, Lighthouse. Wall-clock while a
stage is active, times a stated machine draw, is the assumption we can actually
defend and that a reader can argue with.

It **overstates** for stages idling on network I/O and **understates** for
multi-core saturation. It is reported as an assumption every time it is printed,
never as a measurement.

---

## 6. The verdicts

Evaluated in order, first match wins. Thresholds are config
(`thresholds` in `defaults.json`), not code.

| Verdict | Condition | Exit |
|---|---|---:|
| **Blocked** | no ownership attestation, robots.txt disallow, or a login wall | 2 |
| **Do not do this for carbon** | already lean *and* green-hosted, or net monthly saving <= 0 | 1 |
| **Diminishing returns** | payback > 12 months, or annual net < 2 kg | 1 |
| **Clear win** | payback <= 3 months | 0 |
| **Worthwhile if content is stable** | everything else that pays back | 0 |

A non-zero exit is not an error. It is the tool doing its job.

### On volatility

The original spec gated the "worthwhile if stable" verdict on
`volatility <= monthly`. We deliberately do not, because re-crawl churn is
**already priced into the recurring cost term**. Gating on it as well would
count the same churn twice and understate genuinely good jobs.

What high churn actually changes is *forecast confidence*: a site that rewrites
itself weekly may not hold the weight we measured today. So it attaches a
caveat, not a different verdict.

### Caveats that attach automatically

- **Scale** - a clear win worth under one tree-equivalent per year (21 kg) says
  so. A fast payback on a tiny stake is not a carbon project.
- **Churn** - more than 4 re-crawls a month.
- **Coverage** - the request budget ran out, so the measured weight is a
  **floor** and the real saving is larger than stated.

---

## 7. What the gate costs

Two separate budgets, because they cost wildly different amounts:

| | Default cap | Cost |
|---|---:|---|
| Body GETs | 20 | Full payload. Spent only where bytes must be read to run an optimizer |
| HEAD probes | 60 | Headers only, a few hundred bytes each. Used for weight accounting |

Both are hard: the gate **refuses to spend** past them rather than quietly
exceeding them. Both counts and the total bytes appear in every report, and when
either runs out the report says the weight is a floor.

Measured on a 1.4 MB/view CMS site with 4 pages sampled, the whole gate cost
about **1 g CO2e** against an identified annual saving of 4 to 5 kg: roughly
0.02% of one year's benefit.

The gate uses **zero AI**, by construction and by test.

---

## 8. Traffic figures

**No annualized claim is produced without operator-supplied traffic.** There is
no default. Omitting `--monthly-views` puts the run in placeholder mode, where
every derived figure is watermarked ILLUSTRATIVE, and in the HTML report that
watermark is stamped across the page in CSS rather than written in a caption
that could be cropped out of a screenshot.

This exists because the upstream engine's report generator defaulted to 10,000
monthly views and printed a hard annual tree count for sites whose traffic
nobody had measured.

---

## 9. Sources

- Sustainable Web Design model v4, `sustainablewebdesign.org`
- CO2.js (`@tgwf/co2`), The Green Web Foundation, for the segment constants
- Green Web Foundation greencheck API v3, for hosting verification
- Ember Global Electricity Review, for global average grid intensity
- Oasis of Change, for the 21 kg CO2/tree/year planting figure

### Deliberately not used

| Tool | Why not |
|---|---|
| EcoIndex CLI | CC BY-NC-ND: non-commercial and no-derivatives |
| GreenFrame | Elastic License |

Both are good tools. Neither licence is compatible with an Apache-2.0 project
that clients may use commercially.
