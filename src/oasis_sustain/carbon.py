#!/usr/bin/env python3
"""
Carbon model - Sustainable Web Design v4, one implementation.

WHY THIS FILE EXISTS
This is the only place in the project where a gram of CO2e is computed.

That rule was learned the hard way. The upstream engine carried its own
constants in two separate files (0.81 kWh/GB x 442 g/kWh), which are Sustainable
Web Design **v3** figures, while its documentation cited the current model. SWD
v4 puts full-system intensity at ~0.30 kWh/GB, so every carbon number that tool
published was roughly 2.4x too high. A project whose whole pitch is honesty
cannot have two carbon models, and cannot quietly run an obsolete one.

THE MODEL (Sustainable Web Design v4)
SWD v4 splits energy per GB of data transfer across three system segments, each
with an operational and an embodied component:

                     operational   embodied     total
    datacenter          0.055        0.012       0.067  kWh/GB   (22.3%)
    network             0.059        0.013       0.072  kWh/GB   (24.0%)
    user device         0.080        0.081       0.161  kWh/GB   (53.7%)
    ------------------------------------------------------------
    total               0.194        0.106       0.300  kWh/GB

These are the same segment constants the CO2.js implementation of SWD v4 uses
(`@tgwf/co2`, SustainableWebDesign model). We implement the arithmetic in Python
rather than shelling out to node so the whole tool stays runnable offline with no
dependency install; the constants are declared here so any figure we print can be
checked against the published model by hand.

TWO NUMBERS, ALWAYS
The model figure attributes a full share of network and device energy to every
marginal byte. In reality the network is largely fixed-cost: routers and transit
draw close to the same power whether your page is 1.6 MB or 0.9 MB, so shaving
bytes does not linearly shave network energy. The conservative bound therefore
excludes the network segment entirely (24.0% of the model, derived below, not
hardcoded). Real marginal savings sit somewhere in that range. Every public
figure this tool prints must quote both ends.

GREEN HOSTING
Verified green hosting does not delete the datacenter segment; it changes the
grid intensity applied to the datacenter *operational* share only. Embodied
datacenter energy, the network, and the user's device are unaffected. That is
why the green-hosting bonus here is a modest single-digit percentage and not the
22% the datacenter's total share might suggest.

Usage:
    from oasis_sustain import carbon
    r = carbon.per_view(1_600_000, green_hosted=False)
    r["g_co2e"]              # model figure, grams per view
    r["g_co2e_conservative"] # marginal-honest lower bound
    carbon.model_footer()    # dict for the report footer (model, version, date)
"""
from __future__ import annotations

import datetime as _dt
import json
import os

from . import config

# --- Sustainable Web Design v4 segment constants (kWh per GB transferred) ----
# Source: Sustainable Web Design model v4 (sustainablewebdesign.org), the same
# segment split implemented by CO2.js `@tgwf/co2` v0.16.x.
SEGMENTS = {
    "datacenter":  {"operational": 0.055, "embodied": 0.012},
    "network":     {"operational": 0.059, "embodied": 0.013},
    "user_device": {"operational": 0.080, "embodied": 0.081},
}

MODEL_NAME = "Sustainable Web Design"
MODEL_VERSION = "v4"
# The CO2.js release whose SustainableWebDesign constants this mirrors. Bump
# together with SEGMENTS if the upstream model is revised.
CO2JS_EQUIVALENT = "@tgwf/co2 v0.16.x"

# Global average grid intensity, gCO2e per kWh. Ember Global Electricity Review.
# Override per region with OASIS_GRID_G_PER_KWH or the `grid` argument.
DEFAULT_GRID_G_PER_KWH = 494.0
GRID_SOURCE = "Ember Global Electricity Review, global average"

# Grid intensity attributed to a verified-green datacenter's operational draw.
# Not zero: renewables carry a lifecycle intensity. Conservative round figure.
DEFAULT_GREEN_GRID_G_PER_KWH = 50.0

# Blended discount for repeat visits arriving with a warm cache. SWD's own
# guidance is that returning views transfer ~2% of a first view; the blend
# depends on the site's new/returning split, so this is a stated assumption,
# not a measurement. Override per site when analytics are available.
DEFAULT_REPEAT_VISIT_FACTOR = 0.85

# Energy per AI prompt, Wh. Used only to price a *declared* AI budget in the
# pre-flight gate and to meter the tool's own advisory calls. Order-of-magnitude
# figures; the gate's conclusions are insensitive to the exact value because the
# AI-vs-deterministic gap is two to three orders of magnitude.
AI_WH_PER_PROMPT = {
    "chat": 0.34,             # median short chat prompt
    "long_context": 2.5,      # large-context prompt
    "heavy": 5.0,             # long-context agentic step
    "agentic_session": 41.0,  # a full coding session
}

# Assumed active draw of the machine running the pipeline, watts. A laptop under
# sustained ffmpeg/Chromium load. Stated so the number can be argued with.
DEFAULT_DEVICE_WATTS = 65.0

GB = 1_000_000_000.0


def _kwh_per_gb() -> float:
    return sum(s["operational"] + s["embodied"] for s in SEGMENTS.values())


def _segment_share(name: str) -> float:
    s = SEGMENTS[name]
    return (s["operational"] + s["embodied"]) / _kwh_per_gb()


#: Fraction of the model that survives in the conservative bound. Derived from
#: the segment table (1 - network share), never hardcoded, so editing SEGMENTS
#: keeps the bound honest.
def marginal_factor() -> float:
    return 1.0 - _segment_share("network")


def grid_intensity(grid: float | None = None) -> float:
    """Resolve grid intensity: explicit arg > config > env > global default."""
    if grid is not None:
        return float(grid)
    try:
        v = config.section("carbon").get("grid_g_per_kwh")
        if v:
            return float(v)
    except Exception:
        pass
    env = os.environ.get("OASIS_GRID_G_PER_KWH")
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    return DEFAULT_GRID_G_PER_KWH


def green_grid_intensity(green_grid: float | None = None) -> float:
    """Grid intensity credited to a verified-green datacenter's operational draw.

    Configurable because it is the single most load-bearing assumption in the
    green-hosting bonus, and it moves savings in the flattering direction. See
    METHODOLOGY.md: the default derives a ~16.5% bonus; setting this to ~245
    reproduces the 9% the original design spec asserted.
    """
    if green_grid is not None:
        return float(green_grid)
    try:
        v = config.section("carbon").get("green_grid_g_per_kwh")
        if v:
            return float(v)
    except Exception:
        pass
    return DEFAULT_GREEN_GRID_G_PER_KWH


def energy_kwh(byte_count: float) -> float:
    """Full-system operational + embodied energy for a transfer, kWh."""
    return (byte_count / GB) * _kwh_per_gb()


def per_view(byte_count: float, green_hosted: bool = False,
             grid: float | None = None,
             green_grid: float | None = None) -> dict:
    """Emissions for one page view of `byte_count` transfer bytes.

    Returns both the model figure and the conservative (marginal) bound. The
    green-hosting adjustment applies the green grid intensity to the datacenter
    operational segment only; every other segment stays on the normal grid.
    """
    g = grid_intensity(grid)
    gg = green_grid_intensity(green_grid)
    gb = byte_count / GB

    total = 0.0
    conservative = 0.0
    for name, seg in SEGMENTS.items():
        dc_green = green_hosted and name == "datacenter"
        op_intensity = gg if dc_green else g
        seg_g = gb * (seg["operational"] * op_intensity + seg["embodied"] * g)
        total += seg_g
        if name != "network":          # conservative bound drops the network
            conservative += seg_g

    return {
        "bytes": int(byte_count),
        "kwh": energy_kwh(byte_count),
        "g_co2e": total,
        "g_co2e_conservative": conservative,
        "green_hosted": bool(green_hosted),
        "grid_g_per_kwh": g,
    }


def green_host_bonus(grid: float | None = None,
                     green_grid: float | None = None) -> float:
    """Fraction of per-view emissions removed by moving to verified green hosting.

    Derived from the model, not asserted: only the datacenter operational
    segment changes intensity.
    """
    g = grid_intensity(grid)
    dirty = per_view(GB, green_hosted=False, grid=g, green_grid=green_grid)["g_co2e"]
    clean = per_view(GB, green_hosted=True, grid=g, green_grid=green_grid)["g_co2e"]
    return (dirty - clean) / dirty if dirty else 0.0


def compute_g(seconds: float, watts: float = DEFAULT_DEVICE_WATTS,
              grid: float | None = None) -> dict:
    """Emissions for `seconds` of machine time at a stated draw."""
    kwh = (seconds / 3600.0) * watts / 1000.0
    return {"kwh": kwh, "g_co2e": kwh * grid_intensity(grid), "watts": watts,
            "seconds": seconds}


def ai_g(prompts: int, kind: str = "heavy", grid: float | None = None) -> dict:
    """Emissions for a declared or metered AI prompt budget."""
    wh = AI_WH_PER_PROMPT.get(kind, AI_WH_PER_PROMPT["heavy"]) * prompts
    kwh = wh / 1000.0
    return {"prompts": prompts, "kind": kind, "wh": wh, "kwh": kwh,
            "g_co2e": kwh * grid_intensity(grid)}


def range_str(model_g: float, conservative_g: float, display_unit: str = "g") -> str:
    """Render a two-number claim. Never print a single point value publicly.

    BOTH inputs are in GRAMS, always. `display_unit` only chooses the unit the
    output is rendered in; it does not describe the inputs. So

        range_str(5900, 4500, "kg")  ->  "4.50-5.90 kg"

    and passing kilogram values here would silently understate the claim by a
    factor of a thousand. The parameter is named `display_unit` rather than
    `unit` for exactly that reason: a mis-read here produces a wrong published
    figure, which is the one class of bug this project cannot afford.
    """
    lo, hi = sorted((conservative_g, model_g))
    if display_unit == "kg":
        lo, hi = lo / 1000.0, hi / 1000.0
    fmt = "{:.2f}" if hi < 100 else "{:.0f}"
    return f"{fmt.format(lo)}-{fmt.format(hi)} {display_unit}"


def model_footer(grid: float | None = None) -> dict:
    """Provenance block. Every report that prints a carbon figure must show this."""
    g = grid_intensity(grid)
    return {
        "model": f"{MODEL_NAME} {MODEL_VERSION}",
        "implementation": f"oasis_sustain.carbon (constants mirror {CO2JS_EQUIVALENT})",
        "kwh_per_gb": round(_kwh_per_gb(), 4),
        "grid_g_per_kwh": g,
        "grid_source": (GRID_SOURCE if g == DEFAULT_GRID_G_PER_KWH
                        else "operator-supplied"),
        "green_grid_g_per_kwh": green_grid_intensity(),
        "config_sources": config.sources(),
        "conservative_bound": (
            f"excludes the network segment ({_segment_share('network') * 100:.1f}% "
            f"of the model), which barely scales with marginal bytes"
        ),
        "computed_on": _dt.date.today().isoformat(),
    }


def footer_text(grid: float | None = None) -> str:
    f = model_footer(grid)
    return (f"Model: {f['model']} ({f['kwh_per_gb']} kWh/GB full-system) via "
            f"{f['implementation']}. Grid intensity {f['grid_g_per_kwh']:.0f} "
            f"gCO2e/kWh ({f['grid_source']}). Conservative bound "
            f"{f['conservative_bound']}. Computed {f['computed_on']}.")


if __name__ == "__main__":
    import sys
    b = float(sys.argv[1]) if len(sys.argv) > 1 else 1_600_000
    r = per_view(b)
    print(json.dumps({
        "per_view": r,
        "range": range_str(r["g_co2e"], r["g_co2e_conservative"]),
        "marginal_factor": round(marginal_factor(), 4),
        "green_host_bonus": round(green_host_bonus(), 4),
        "footer": model_footer(),
    }, indent=2))
