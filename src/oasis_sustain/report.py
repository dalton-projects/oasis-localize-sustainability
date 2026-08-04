"""
Rendering a gate result for a human.

Three rules govern every output format here:

  1. **Two numbers, never one.** Savings render as a range: the Sustainable Web
     Design model figure and a conservative bound that drops the network
     segment. A point value claims a precision the model does not have.
  2. **The footer travels with the figure.** Model, version, grid intensity and
     date appear wherever a number does, so any claim can be re-derived or
     argued with.
  3. **Placeholder figures are watermarked in the artifact**, not in a caption
     someone might crop out. The HTML version stamps ILLUSTRATIVE across the
     page in CSS.

The HTML report is fully self-contained: no webfonts, no CDN, no analytics, no
external anything. A carbon report that phones out on every open is making the
other side's argument.
"""
from __future__ import annotations

import html as _html
import json

GREEN = "#16b371"
CHAR = "#2d2d2d"


def wrap(text: str, width: int = 68) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


# ------------------------------------------------------------------- text ---

def render_text(r: dict) -> str:
    v = r["verdict"]
    ph = r["inputs"]["placeholder_mode"]
    L = ["", "=" * 72, f"  PRE-FLIGHT: {r['inputs']['url']}", "=" * 72,
         f"  VERDICT: {v['label']}"]
    for line in wrap(v["message"]):
        L.append(f"    {line}")
    for cav in v.get("caveats", []):
        L.append("")
        for line in wrap(cav):
            L.append(f"    {line}")
    L.append("")

    if r.get("blocked_reasons"):
        L.append("  BLOCKED BY:")
        for reason in r["blocked_reasons"]:
            for i, line in enumerate(wrap(reason, 66)):
                L.append(f"    {'- ' if i == 0 else '  '}{line}")
        L += ["", "  No figures are produced for a blocked site, and nothing "
                  "was crawled.", ""]
        # The footer still ships. It names the tool and model version that
        # produced this refusal, which someone disputing the block will want.
        for line in wrap(r["carbon_model"]["_footer_text"]):
            L.append(f"  {line}")
        L.append("")
        return "\n".join(L)

    p, s = r["payback"], r["sample"]
    L.append("  WHAT WE MEASURED (sample pass, no AI)")
    L.append(f"    pages sampled          : {s['pages_sampled']}")
    if s.get("resources_referenced"):
        L.append(f"    resources sized        : {s.get('resources_sized', 0)} of "
                 f"{s['resources_referenced']} referenced "
                 f"({s.get('coverage_ratio', 1) * 100:.0f}% coverage)")
    L.append(f"    weight per view        : {p['w_before_bytes']:,} B -> "
             f"{p['w_after_bytes']:,} B  ({p['weight_cut_pct']}% lighter)")
    L.append(f"    carbon per view        : {p['g_per_view_before']:.3f} g -> "
             f"{p['g_per_view_after']:.3f} g")
    g = r["green"]
    L.append(f"    green hosted already   : {'yes' if g['green'] else 'no'}"
             f"{'' if g.get('checked') else '  (greencheck unreachable)'}")
    dg = r.get("destination_green") or {}
    if p.get("green_bonus_claimed"):
        verified = (" (destination verified)" if dg.get("checked")
                    else " (destination NOT verified, assumed)")
        L.append(f"    green-hosting bonus    : "
                 f"{p['green_bonus_g_per_view']:.4f} g/view, credited{verified}")
    elif not g["green"]:
        L.append("    green-hosting bonus    : NOT credited "
                 "(destination is not verified green)")
    if s.get("stripped_bytes"):
        L.append(f"    third-party JS removed : {s['stripped_bytes']:,} B "
                 f"({len(s['stripped'])} file(s)) - deleted, not compressed")
    if s.get("needs_headless"):
        L.append("    rendering              : client-side; a faithful mirror "
                 "needs the headless path (crawl cost doubled below)")

    if s.get("measured_trials"):
        L += ["", "  OPTIMIZER TRIALS (the real encoders, on your real bytes)"]
        for t in s["measured_trials"][:6]:
            name = t["url"].rsplit("/", 1)[-1][:38]
            L.append(f"    {name:40s} {t['before']:>9,} -> {t['after']:>9,} B  "
                     f"({t['reduction_pct']}%)  {t['method']}")

    L += ["", f"  THE MATH{'  [ILLUSTRATIVE - placeholder traffic]' if ph else ''}"]
    L.append(f"    monthly pageviews      : {r['inputs']['monthly_views']:,.0f}"
             f"{' (PLACEHOLDER)' if ph else ' (operator supplied)'}")
    b = p["one_time_breakdown_g"]
    L.append(f"    one-time cost          : {p['one_time_g'] / 1000:.4f} kg CO2e "
             f"(crawl {b['crawl']:.1f} g, compute {b['compute']:.1f} g, "
             f"AI {b['ai']:.1f} g)")
    L.append(f"    recurring cost         : {p['monthly_cost_g']:.2f} g/month "
             f"({r['inputs']['recrawls_per_month']} delta re-crawl(s)/month)")
    L.append(f"    net monthly saving     : {p['net_monthly_g']:.1f} g "
             f"(conservative {p['net_monthly_g_conservative']:.1f} g)")
    L.append("    payback                : "
             + (f"{p['payback_days']:.1f} days ({p['payback_months']:.2f} months)"
                if p["payback_days"] is not None else "never"))
    L.append(f"    annual net             : "
             f"{p['annual_net_kg_conservative']:.2f} to {p['annual_net_kg']:.2f} "
             f"kg CO2e/year  (conservative to model)")
    L.append(f"    tree equivalent        : {p['annual_net_kg'] / 21:.2f} "
             f"trees/year at 21 kg/tree/yr")

    if r.get("ai_comparison"):
        c = r["ai_comparison"]
        L += ["", "  YOU DECLARED AN AI-ASSISTED PIPELINE. HERE IS THE COMPARISON."]
        L.append(f"    deterministic pipeline : one-time "
                 f"{c['deterministic']['one_time_kg']:.4f} kg, payback "
                 f"{c['deterministic']['payback_days']:.1f} days")
        L.append(f"    AI-assisted ({c['ai_assisted']['prompts']:,} "
                 f"{c['ai_assisted']['kind']} prompts): one-time "
                 f"{c['ai_assisted']['one_time_kg']:.4f} kg "
                 f"(AI = {c['ai_assisted']['ai_share_pct']}% of it), payback "
                 f"{c['ai_assisted']['payback_days']:.1f} days")
        L.append(f"    the AI adds            : {c['added_payback_months']:.1f} "
                 f"months of payback for the SAME end state "
                 f"({c['cost_multiple']:.0f}x the one-time cost)")
        for line in wrap(c["recommendation"], 66):
            L.append(f"    {line}")

    if s.get("dynamic_features"):
        L += ["", "  A MIRROR WILL BREAK THESE (viability, not carbon)"]
        L += [f"    - {f}" for f in s["dynamic_features"]]

    if s.get("co_benefits"):
        L += ["", "  WORTH FIXING REGARDLESS OF THE VERDICT"]
        L += [f"    - {c}" for c in s["co_benefits"][:6]]

    bud = r["budget"]
    L += ["", "  WHAT THIS GATE COST",
          f"    {bud['gets_used']} body GET(s), {bud['heads_used']} HEAD probe(s), "
          f"{bud['bytes']:,} bytes, 0 AI prompts"]
    if not s.get("coverage_complete", True):
        for line in wrap(f"NOTE: the request budget ran out with "
                         f"{s.get('resources_uncounted', 0)} resource(s) "
                         f"uncounted, so the weight above is a FLOOR, not a "
                         f"total. Raise --get-budget/--head-budget for a fuller "
                         f"picture, at proportionally more cost.", 66):
            L.append(f"    {line}")
    L.append("    Sizes come from Content-Length with Accept-Encoding sent, so "
             "they are")
    L.append("    wire bytes wherever the host honours it.")

    L.append("")
    for line in wrap(r["carbon_model"]["_footer_text"]):
        L.append(f"  {line}")
    L.append("")
    return "\n".join(L)


# ------------------------------------------------------------------- json ---

def render_json(r: dict) -> str:
    return json.dumps(r, indent=2, default=str)


# ------------------------------------------------------------------- html ---

def render_html(r: dict) -> str:
    """A self-contained page. No webfonts, no CDN, no external requests."""
    v = r["verdict"]
    ph = r["inputs"]["placeholder_mode"]
    e = _html.escape
    blocked = bool(r.get("blocked_reasons"))

    tone = {"clear_win": GREEN, "worthwhile_if_stable": "#b8860b",
            "diminishing_returns": "#c1670c",
            "do_not_do_this_for_carbon": "#b3261e",
            "blocked": "#5f6368"}.get(v["key"], CHAR)

    watermark = ""
    if ph and not blocked:
        watermark = """
  body::before{content:"ILLUSTRATIVE";position:fixed;inset:0;display:flex;
    align-items:center;justify-content:center;font-size:min(18vw,220px);
    font-weight:700;color:rgba(45,45,45,.07);pointer-events:none;z-index:99;
    transform:rotate(-24deg);letter-spacing:.05em}"""

    body = [f'<h1>{e(r["inputs"]["url"])}</h1>',
            f'<div class="verdict" style="border-color:{tone};color:{tone}">'
            f'{e(v["label"])}</div>',
            f'<p class="msg">{e(v["message"])}</p>']
    for cav in v.get("caveats", []):
        body.append(f'<p class="caveat">{e(cav)}</p>')

    if blocked:
        body.append("<ul class='blocked'>"
                    + "".join(f"<li>{e(x)}</li>" for x in r["blocked_reasons"])
                    + "</ul>")
        body.append("<p class='msg'>No figures are produced for a blocked "
                    "site, and nothing was crawled.</p>")
    else:
        p, s = r["payback"], r["sample"]
        cards = [
            ("Weight per view",
             f"{p['w_before_bytes'] / 1000:,.0f} kB &rarr; "
             f"{p['w_after_bytes'] / 1000:,.0f} kB", f"{p['weight_cut_pct']}% lighter"),
            ("Carbon per view",
             f"{p['g_per_view_before']:.3f} &rarr; {p['g_per_view_after']:.3f} g",
             "Sustainable Web Design v4"),
            ("Payback",
             (f"{p['payback_days']:.0f} days" if p["payback_days"] is not None
              else "never"),
             f"one-time {p['one_time_g'] / 1000:.4f} kg CO2e"),
            ("Annual net saving",
             f"{p['annual_net_kg_conservative']:.1f} to {p['annual_net_kg']:.1f} kg",
             f"conservative to model &middot; "
             f"{p['annual_net_kg'] / 21:.2f} trees/yr"),
        ]
        body.append('<div class="grid">' + "".join(
            f'<div class="card"><div class="label">{lab}</div>'
            f'<div class="big">{val}</div><div class="sub">{sub}</div></div>'
            for lab, val, sub in cards) + '</div>')

        if s.get("measured_trials"):
            rows = "".join(
                f"<tr><td>{e(t['url'].rsplit('/', 1)[-1][:44])}</td>"
                f"<td>{t['before']:,}</td><td>{t['after']:,}</td>"
                f"<td>{t['reduction_pct']}%</td><td>{e(t['method'])}</td></tr>"
                for t in s["measured_trials"][:10])
            body.append(
                "<h2>Optimizer trials</h2><p class='msg'>The real encoders, run "
                "on your real bytes. Not a modelled ratio.</p>"
                "<div class='scroll'><table><thead><tr><th>Resource</th>"
                "<th>Before</th><th>After</th><th>Cut</th><th>Method</th></tr>"
                f"</thead><tbody>{rows}</tbody></table></div>")

        if r.get("ai_comparison"):
            c = r["ai_comparison"]
            body.append(
                "<h2>Declared AI pipeline</h2>"
                "<div class='scroll'><table><thead><tr><th>Pipeline</th>"
                "<th>One-time cost</th><th>Payback</th></tr></thead><tbody>"
                f"<tr><td>Deterministic</td>"
                f"<td>{c['deterministic']['one_time_kg']:.4f} kg</td>"
                f"<td>{c['deterministic']['payback_days']:.1f} days</td></tr>"
                f"<tr><td>AI-assisted "
                f"({c['ai_assisted']['prompts']:,} {e(c['ai_assisted']['kind'])} "
                f"prompts)</td>"
                f"<td>{c['ai_assisted']['one_time_kg']:.4f} kg "
                f"({c['ai_assisted']['ai_share_pct']}% is AI)</td>"
                f"<td>{c['ai_assisted']['payback_days']:.1f} days</td></tr>"
                "</tbody></table></div>"
                f"<p class='msg'>Same end state. The AI adds "
                f"{c['added_payback_months']:.1f} months of payback and "
                f"{c['cost_multiple']:.0f}x the one-time cost. "
                f"{e(c['recommendation'])}</p>")

        if s.get("co_benefits"):
            body.append("<h2>Worth fixing regardless</h2><ul>" + "".join(
                f"<li>{e(x)}</li>" for x in s["co_benefits"][:8]) + "</ul>")

        bud = r["budget"]
        body.append(
            f"<h2>What this gate cost</h2><p class='msg'>{bud['gets_used']} body "
            f"GET(s), {bud['heads_used']} HEAD probe(s), {bud['bytes']:,} bytes, "
            f"0 AI prompts.</p>")

    body.append(f'<footer>{e(r["carbon_model"]["_footer_text"])}</footer>')

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pre-flight: {e(r['inputs']['url'])}</title>
<style>
  :root{{color-scheme:light dark}}
  *{{box-sizing:border-box}}
  body{{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:{CHAR};
    background:#fbfdfb;margin:0;padding:clamp(20px,4vw,48px);line-height:1.6}}
  h1{{font-size:clamp(20px,3vw,30px);margin:0 0 14px;word-break:break-word}}
  h2{{font-size:18px;margin:32px 0 8px}}
  .verdict{{display:inline-block;border:2px solid;border-radius:999px;
    padding:6px 18px;font-weight:700;letter-spacing:.02em;margin-bottom:14px}}
  .msg{{max-width:70ch;margin:0 0 10px}}
  .caveat{{max-width:70ch;background:#fff7e6;border-left:3px solid #e0a75e;
    padding:10px 14px;border-radius:0 8px 8px 0;font-size:14px}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));
    gap:16px;margin:22px 0;max-width:1000px}}
  .card{{background:#fff;border:1px solid #e6ece8;border-radius:14px;padding:18px}}
  .label{{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:#5f6b64}}
  .big{{font-size:22px;font-weight:700;margin:6px 0 2px}}
  .sub{{font-size:13px;color:#5f6b64}}
  .scroll{{overflow-x:auto;max-width:100%}}
  table{{border-collapse:collapse;font-size:13px;min-width:520px}}
  th,td{{text-align:left;padding:7px 12px;border-bottom:1px solid #e6ece8;
    white-space:nowrap}}
  th{{font-weight:600;color:#5f6b64}}
  ul{{max-width:70ch}} .blocked li{{color:#b3261e}}
  footer{{margin-top:36px;padding-top:14px;border-top:1px solid #e6ece8;
    font-size:12px;color:#5f6b64;max-width:80ch}}
  @media(prefers-color-scheme:dark){{
    body{{background:#141816;color:#e6ece8}}
    .card{{background:#1c2220;border-color:#2b3330}}
    th,td{{border-color:#2b3330}} .sub,.label,th,footer{{color:#9fb0a8}}
    .caveat{{background:#2a2418;border-color:#8a6d3b}}
  }}{watermark}
</style></head><body>
{''.join(body)}
</body></html>"""


RENDERERS = {"text": render_text, "json": render_json, "html": render_html}


def render(result: dict, fmt: str = "text") -> str:
    return RENDERERS.get(fmt, render_text)(result)
