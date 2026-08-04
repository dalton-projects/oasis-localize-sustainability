"""
Command line interface.

    oasis-sustain check <url> --i-own-this --monthly-views 5000
    oasis-sustain meter init | add | footer
    oasis-sustain model

Exit codes from `check` carry the verdict, so a pipeline can branch on them
without parsing output:

    0   proceed          clear win, or worthwhile if content is stable
    1   advised against  diminishing returns, or do not do this for carbon
    2   blocked          no ownership attestation, robots.txt, or a login wall

A non-zero exit is not an error. It is the tool doing its job.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, carbon, config, meter, preflight, report


def _add_check(sub):
    p = sub.add_parser(
        "check", help="should this site be optimized at all?",
        description="Cheap sample pass, real optimizers, honest payback maths. "
                    "No AI.")
    p.add_argument("url")
    p.add_argument("--i-own-this", action="store_true", dest="owns",
                   help="attest that you own or control this site (required)")
    p.add_argument("--monthly-views", type=float, default=None,
                   help="from your analytics. Omit for watermarked placeholder "
                        "mode; we do not invent traffic numbers.")
    p.add_argument("--volatility", default="monthly",
                   choices=["daily", "weekly", "monthly", "rarely"],
                   help="roughly how often the site's content changes")
    p.add_argument("--destination", default=None,
                   help="host the site would move TO. Greenchecked; the "
                        "green-hosting bonus is only credited if it verifies.")
    p.add_argument("--pipeline", default="deterministic",
                   choices=["deterministic", "ai"])
    p.add_argument("--ai-prompts", type=int, default=0)
    p.add_argument("--ai-kind", default="heavy",
                   choices=sorted(carbon.AI_WH_PER_PROMPT))
    p.add_argument("--sample", type=int, default=None, dest="sample_size",
                   help="pages to sample, including the homepage")
    p.add_argument("--get-budget", type=int, default=None)
    p.add_argument("--head-budget", type=int, default=None)
    p.add_argument("--grid", type=float, default=None,
                   help="grid intensity gCO2e/kWh for the audience region")
    p.add_argument("--format", default="text", choices=["text", "json", "html"])
    p.add_argument("--out", default=None, help="write the report to a file too")
    p.add_argument("--config", default=None, help="path to a config override")
    p.add_argument("--no-meter", action="store_true",
                   help="do not print this run's own footprint")


def _add_meter(sub):
    p = sub.add_parser("meter", help="this run's own Wh and gCO2e")
    m = p.add_subparsers(dest="meter_cmd", required=True)

    i = m.add_parser("init", help="start a fresh ledger for a run")
    i.add_argument("--run", default="")

    a = m.add_parser("add", help="record one metered event")
    a.add_argument("--stage", required=True)
    a.add_argument("--bytes", type=int, default=0)
    a.add_argument("--seconds", type=float, default=0.0)
    a.add_argument("--ai-prompts", type=int, default=0)
    a.add_argument("--ai-kind", default="heavy",
                   choices=sorted(carbon.AI_WH_PER_PROMPT))
    a.add_argument("--browser-launches", type=int, default=0)
    a.add_argument("--note", default="")

    f = m.add_parser("footer", help="print the run footer")
    f.add_argument("--json", action="store_true")
    f.add_argument("--grid", type=float, default=None)


def _add_model(sub):
    p = sub.add_parser(
        "model", help="print the carbon model, its constants and its sources",
        description="Everything needed to check or challenge any figure this "
                    "tool prints.")
    p.add_argument("--json", action="store_true")
    p.add_argument("--grid", type=float, default=None)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="oasis-sustain",
        description="Is optimizing this website worth the carbon it costs?")
    ap.add_argument("--version", action="version",
                    version=f"oasis-sustain {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    _add_check(sub)
    _add_meter(sub)
    _add_model(sub)
    return ap


def cmd_check(args) -> int:
    if args.config:
        config.set_override(args.config)

    result = preflight.preflight(
        args.url, owns_site=args.owns, monthly_views=args.monthly_views,
        volatility=args.volatility, pipeline=args.pipeline,
        ai_prompts=args.ai_prompts, ai_kind=args.ai_kind,
        sample_size=args.sample_size, get_budget=args.get_budget,
        head_budget=args.head_budget, grid=args.grid,
        destination=args.destination)

    text = report.render(result, args.format)
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"  Written: {args.out}", file=sys.stderr)

    if not args.no_meter and args.format == "text":
        print(meter.footer_text(args.grid))
    return result["exit_code"]


def cmd_meter(args) -> int:
    if args.meter_cmd == "init":
        meter.init(args.run)
        print(f"meter: ledger started at {meter.LEDGER}")
    elif args.meter_cmd == "add":
        meter.record(args.stage, args.bytes, args.seconds, args.ai_prompts,
                     args.ai_kind, args.browser_launches, args.note)
    elif args.meter_cmd == "footer":
        print(json.dumps(meter.totals(args.grid), indent=2) if args.json
              else meter.footer_text(args.grid))
    return 0


def cmd_model(args) -> int:
    f = carbon.model_footer(args.grid)
    if args.json:
        print(json.dumps({
            "footer": f,
            "segments_kwh_per_gb": carbon.SEGMENTS,
            "marginal_factor": carbon.marginal_factor(),
            "green_host_bonus": carbon.green_host_bonus(),
            "ai_wh_per_prompt": carbon.AI_WH_PER_PROMPT,
            "device_watts": carbon.DEFAULT_DEVICE_WATTS,
            "repeat_visit_factor": carbon.DEFAULT_REPEAT_VISIT_FACTOR,
        }, indent=2))
        return 0

    print(f"\n  {f['model']}   ({f['implementation']})\n")
    print("  Energy per GB transferred, by segment (kWh/GB):")
    print(f"    {'segment':<14}{'operational':>13}{'embodied':>11}"
          f"{'total':>9}{'share':>9}")
    for name, seg in carbon.SEGMENTS.items():
        tot = seg["operational"] + seg["embodied"]
        print(f"    {name:<14}{seg['operational']:>13.3f}{seg['embodied']:>11.3f}"
              f"{tot:>9.3f}{carbon._segment_share(name) * 100:>8.1f}%")
    print(f"    {'TOTAL':<14}{'':>13}{'':>11}{carbon._kwh_per_gb():>9.3f}"
          f"{100.0:>8.1f}%")
    print(f"\n  Grid intensity        {f['grid_g_per_kwh']:.0f} gCO2e/kWh "
          f"({f['grid_source']})")
    print(f"  Green datacenter grid {f['green_grid_g_per_kwh']:.0f} gCO2e/kWh "
          f"-> {carbon.green_host_bonus() * 100:.1f}% bonus")
    print(f"  Conservative bound    x{carbon.marginal_factor():.2f}, "
          f"{f['conservative_bound']}")
    print(f"  Device draw           {carbon.DEFAULT_DEVICE_WATTS:.0f} W "
          f"(assumption, not a measurement)")
    print(f"  Repeat-visit factor   {carbon.DEFAULT_REPEAT_VISIT_FACTOR}")
    print("\n  Energy per AI prompt (Wh):")
    for k, v in carbon.AI_WH_PER_PROMPT.items():
        print(f"    {k:<18}{v:>7.2f}")
    print(f"\n  Config sources        {', '.join(f['config_sources'])}")
    print(f"  Computed              {f['computed_on']}\n")
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return {"check": cmd_check, "meter": cmd_meter, "model": cmd_model}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
