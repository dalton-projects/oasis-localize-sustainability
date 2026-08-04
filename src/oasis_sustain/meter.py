#!/usr/bin/env python3
"""
Self-metering - what did THIS RUN cost?

The tool exists to tell people whether optimizing a site is worth the carbon. It
has no standing to do that while it silently ignores its own footprint. Every
run must end with an honest "this run used approximately X Wh (Y g CO2e)",
broken down, with the assumptions visible.

WHAT IS METERED
  transfer    bytes pulled off the network (crawl, harvest, audits, greencheck)
  compute     seconds of machine time at a stated wattage
  ai          LLM prompts, by kind, priced from carbon.AI_WH_PER_PROMPT
  browser     headless Chromium launches (counted for visibility, and because a
              launch is the single most reliable proxy for "we did the expensive
              thing when we might not have needed to")

HOW IT WORKS
A run-scoped JSON ledger at reports/run-meter.json. Every stage appends to it,
so the footer at the end covers the whole pipeline rather than one script. It is
append-only within a run and safe to call from anywhere; if the ledger is
missing it is created on first write. Nothing here needs the network.

WHY WALL-CLOCK FOR COMPUTE
Python cannot reliably attribute a subprocess's CPU time on Windows
(os.times() reports zero for children), and most of this pipeline's compute is
in subprocesses: ffmpeg, Chromium, Lighthouse. Wall-clock while a stage is
active, times a stated machine draw, is the assumption we can actually defend
and that a reader can argue with. It overstates for idle-waiting stages (a
crawler blocked on network I/O is not drawing 65 W) and understates for
multi-core saturation, so it is reported as an assumption, never as a
measurement. Where a real CPU-seconds figure is available, pass it explicitly.

Usage (CLI):
    oasis-sustain meter init  --run "<site being processed>"
    python scripts/meter.py add   --stage crawl --bytes 41231234 --seconds 92 \\
                                  --browser-launches 1
    python scripts/meter.py add   --stage a11y  --ai-prompts 12 --ai-kind heavy
    python scripts/meter.py footer                  # human-readable run footer
    python scripts/meter.py footer --json

Usage (library):
    from oasis_sustain import meter
    with meter.stage("crawl", browser_launches=1) as m:
        ...
        m.add_bytes(n)
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
from pathlib import Path

from . import carbon

LEDGER = Path(os.environ.get("OASIS_METER_PATH", "reports/run-meter.json"))

# Set OASIS_METER=0 to disable metering entirely (it is cheap, but a metering
# system that cannot be turned off is its own kind of dishonest).
ENABLED = os.environ.get("OASIS_METER", "1") != "0"


def _blank(run: str = "") -> dict:
    return {"run": run, "started": time.time(), "entries": []}


def _load() -> dict:
    try:
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    except Exception:
        return _blank()


def _save(data: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(data, indent=2), encoding="utf-8")


def init(run: str = "") -> None:
    """Start a fresh ledger. Call once per run, before stage 1."""
    if ENABLED:
        _save(_blank(run))


def record(stage: str, bytes_transferred: int = 0, seconds: float = 0.0,
           ai_prompts: int = 0, ai_kind: str = "heavy",
           browser_launches: int = 0, note: str = "") -> None:
    """Append one metered event. Safe to call repeatedly for the same stage."""
    if not ENABLED:
        return
    data = _load()
    data.setdefault("entries", []).append({
        "stage": stage,
        "bytes": int(bytes_transferred),
        "seconds": round(float(seconds), 2),
        "ai_prompts": int(ai_prompts),
        "ai_kind": ai_kind,
        "browser_launches": int(browser_launches),
        "note": note,
        "at": time.time(),
    })
    _save(data)


class _Stage:
    """Accumulates within a `with meter.stage(...)` block, writes once on exit."""

    def __init__(self, name: str, browser_launches: int = 0, note: str = ""):
        self.name = name
        self.bytes = 0
        self.ai_prompts = 0
        self.ai_kind = "heavy"
        self.browser_launches = browser_launches
        self.note = note
        self._t0 = time.time()

    def add_bytes(self, n: int) -> None:
        self.bytes += int(n or 0)

    def add_ai(self, prompts: int, kind: str = "heavy") -> None:
        self.ai_prompts += int(prompts)
        self.ai_kind = kind

    def add_browser_launch(self, n: int = 1) -> None:
        self.browser_launches += n


@contextlib.contextmanager
def stage(name: str, browser_launches: int = 0, note: str = ""):
    s = _Stage(name, browser_launches, note)
    try:
        yield s
    finally:
        record(name, bytes_transferred=s.bytes, seconds=time.time() - s._t0,
               ai_prompts=s.ai_prompts, ai_kind=s.ai_kind,
               browser_launches=s.browser_launches, note=s.note)


def totals(grid: float | None = None) -> dict:
    """Roll the ledger up into Wh and gCO2e, with a per-stage breakdown."""
    data = _load()
    entries = data.get("entries", [])

    by_stage: dict[str, dict] = {}
    tot_bytes = tot_seconds = tot_prompts = tot_launches = 0
    transfer_g = compute_g_total = ai_g_total = 0.0
    transfer_g_cons = 0.0

    for e in entries:
        st = by_stage.setdefault(e["stage"], {
            "bytes": 0, "seconds": 0.0, "ai_prompts": 0,
            "browser_launches": 0, "wh": 0.0, "g_co2e": 0.0})

        t = carbon.per_view(e["bytes"], grid=grid)
        c = carbon.compute_g(e["seconds"], grid=grid)
        a = carbon.ai_g(e["ai_prompts"], e.get("ai_kind", "heavy"), grid=grid) \
            if e["ai_prompts"] else {"kwh": 0.0, "g_co2e": 0.0}

        transfer_g += t["g_co2e"]
        transfer_g_cons += t["g_co2e_conservative"]
        compute_g_total += c["g_co2e"]
        ai_g_total += a["g_co2e"]

        st["bytes"] += e["bytes"]
        st["seconds"] += e["seconds"]
        st["ai_prompts"] += e["ai_prompts"]
        st["browser_launches"] += e["browser_launches"]
        st["wh"] += (t["kwh"] + c["kwh"] + a["kwh"]) * 1000
        st["g_co2e"] += t["g_co2e"] + c["g_co2e"] + a["g_co2e"]

        tot_bytes += e["bytes"]
        tot_seconds += e["seconds"]
        tot_prompts += e["ai_prompts"]
        tot_launches += e["browser_launches"]

    total_g = transfer_g + compute_g_total + ai_g_total
    total_g_cons = transfer_g_cons + compute_g_total + ai_g_total
    g = carbon.grid_intensity(grid)
    total_wh = (total_g / g) * 1000 if g else 0.0

    return {
        "run": data.get("run", ""),
        "stages": {k: {**v, "wh": round(v["wh"], 3),
                       "g_co2e": round(v["g_co2e"], 3)}
                   for k, v in by_stage.items()},
        "bytes": tot_bytes,
        "seconds": round(tot_seconds, 1),
        "ai_prompts": tot_prompts,
        "browser_launches": tot_launches,
        "wh": round(total_wh, 3),
        "g_co2e": round(total_g, 3),
        "g_co2e_conservative": round(total_g_cons, 3),
        "split_g": {
            "transfer": round(transfer_g, 3),
            "compute": round(compute_g_total, 3),
            "ai": round(ai_g_total, 3),
        },
        "assumptions": {
            "device_watts": carbon.DEFAULT_DEVICE_WATTS,
            "compute_basis": "wall-clock while a stage is active, at the stated "
                             "draw; an assumption, not a measurement",
            "ai_wh_per_prompt": carbon.AI_WH_PER_PROMPT,
        },
        "carbon_model": carbon.model_footer(grid),
    }


def footer_text(grid: float | None = None) -> str:
    """The line every run ends with."""
    t = totals(grid)
    if not t["stages"]:
        return "This run: nothing metered (no ledger entries)."
    parts = [f"transfer {t['split_g']['transfer']:.2f} g"]
    if t["split_g"]["compute"]:
        parts.append(f"compute {t['split_g']['compute']:.2f} g")
    if t["split_g"]["ai"]:
        parts.append(f"AI {t['split_g']['ai']:.2f} g")
    lines = [
        "",
        "  THIS RUN'S OWN FOOTPRINT",
        f"    {t['wh']:.2f} Wh  ~  {t['g_co2e']:.2f} g CO2e "
        f"(conservative {t['g_co2e_conservative']:.2f} g)",
        f"    {' + '.join(parts)}",
        f"    {t['bytes']:,} bytes transferred, {t['seconds']:.0f} s machine time, "
        f"{t['ai_prompts']} AI prompt(s), {t['browser_launches']} browser launch(es)",
    ]
    if t["stages"]:
        worst = sorted(t["stages"].items(), key=lambda kv: -kv[1]["g_co2e"])[:3]
        lines.append("    heaviest stages: " + ", ".join(
            f"{k} {v['g_co2e']:.2f} g" for k, v in worst))
    lines += [
        f"    compute assumes {t['assumptions']['device_watts']:.0f} W "
        f"({t['assumptions']['compute_basis']})",
        f"    {carbon.footer_text(grid)}",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="start a fresh ledger for a run")
    p_init.add_argument("--run", default="")

    p_add = sub.add_parser("add", help="record one metered event")
    p_add.add_argument("--stage", required=True)
    p_add.add_argument("--bytes", type=int, default=0)
    p_add.add_argument("--seconds", type=float, default=0.0)
    p_add.add_argument("--ai-prompts", type=int, default=0)
    p_add.add_argument("--ai-kind", default="heavy",
                       choices=sorted(carbon.AI_WH_PER_PROMPT))
    p_add.add_argument("--browser-launches", type=int, default=0)
    p_add.add_argument("--note", default="")

    p_foot = sub.add_parser("footer", help="print the run footer")
    p_foot.add_argument("--json", action="store_true")
    p_foot.add_argument("--grid", type=float, default=None)

    args = ap.parse_args()
    if args.cmd == "init":
        init(args.run)
        print(f"meter: ledger started at {LEDGER}")
    elif args.cmd == "add":
        record(args.stage, args.bytes, args.seconds, args.ai_prompts,
               args.ai_kind, args.browser_launches, args.note)
    elif args.cmd == "footer":
        if args.json:
            print(json.dumps(totals(args.grid), indent=2))
        else:
            print(footer_text(args.grid))
    return 0


if __name__ == "__main__":
    sys.exit(main())
