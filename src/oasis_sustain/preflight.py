"""
The pre-flight gate: is this job worth doing at all?

This runs before anything is crawled, optimized or deployed, and it is allowed
to say no. The refusal is the product. A tool that will happily mirror any site
you point it at is a tool whose carbon claims mean nothing.

WHAT IT DOES
A cheap sample pass (homepage plus up to four pages, a hard request budget,
ZERO AI) that measures rather than models:

  1. Ownership attestation, robots.txt and login-wall checks   -> may block
  2. Current page weight, split by HTML / CSS / JS / images / fonts
  3. Green-hosting status of the current host AND, when given, of the
     destination, via the Green Web Foundation
  4. Projected optimized weight, MEASURED by running the real optimizers in
     `oasis_sustain.optimize` on the sampled bytes. The same functions the
     pipeline uses to do the actual work, so the projection cannot drift from
     what gets delivered.
  5. Payback = one-time cost / net monthly saving, then a verdict.

WHY IT MUST BE CHEAP
If triage costs as much as the job, the gate is theatre. Full-body GETs are
capped and spent only where bytes must be read; weight accounting uses HEAD
probes, which return headers and no body. On a real site the whole gate
transfers about what a couple of page views do, and it meters itself.

WHY IT USES NO AI
Everything it needs is arithmetic on measured bytes. A model here would add
energy, latency and non-determinism to a decision that has to be reproducible
and defensible to a sceptical client. AI in this project is for advisory prose,
downstream, opt-in and metered. Never here.

HONESTY RULES ENFORCED HERE
  - No annualized claim without operator-supplied traffic. Without it the run
    is placeholder mode and every figure is watermarked ILLUSTRATIVE.
  - Two numbers, always: the model figure and a conservative bound.
  - A declared AI pipeline is shown beside the deterministic alternative.
  - Budget exhaustion is disclosed, because it makes the weight a floor.
"""
from __future__ import annotations

import re
import time
import urllib.parse

from . import carbon, config, fetch, meter
from .optimize import classify, optimize
from .optimize import css as _css
from .optimize import images as _images

VERDICT_PROCEED = ("clear_win", "worthwhile_if_stable")
VERDICT_STOP = ("diminishing_returns", "do_not_do_this_for_carbon")
VERDICT_BLOCKED = ("blocked",)

EXIT_PROCEED, EXIT_ADVISED_AGAINST, EXIT_BLOCKED = 0, 1, 2

# Markers that a page is assembled client-side, so a faithful mirror needs the
# expensive headless path. Doubling the crawl cost is the payback consequence.
SPA_ROOT_RE = re.compile(
    r'<(?:div|main)[^>]+id=["\'](?:root|app|__next|__nuxt|svelte)["\'][^>]*>\s*</',
    re.I)
LOGIN_WALL_RE = re.compile(
    r'(type=["\']password["\']|/wp-login|/account/login|id=["\']login)', re.I)

RES_RE = re.compile(
    r'<(?:link[^>]+href|script[^>]+src|img[^>]+src|source[^>]+srcset)'
    r'\s*=\s*["\']([^"\']+)', re.I)

DYNAMIC_FEATURES = (
    ("forms", r'<form'),
    ("search", r'type=["\']search["\']|/search'),
    ("commerce", r'add-to-cart|/cart|checkout'),
    ("members", r'/account|/login|logout'),
)


# --------------------------------------------------------------- sampling ---

def page_resources(html: str, page_url: str) -> list[str]:
    """Absolute sub-resource URLs a page references, deduped, in document order
    (which correlates with render-blocking importance)."""
    out, seen = [], set()
    for m in RES_RE.findall(html):
        u = m.strip().split()[0] if m.strip() else ""
        if not u or u.startswith(("data:", "blob:", "#", "javascript:", "mailto:")):
            continue
        absu = urllib.parse.urldefrag(urllib.parse.urljoin(page_url, u))[0]
        if absu.startswith("http") and absu not in seen:
            seen.add(absu)
            out.append(absu)
    return out


def sample_pass(sample_urls: list[str], budget: fetch.Budget,
                cfg: dict | None = None) -> dict:
    """Measure the sample and run the real optimizers on it."""
    cfg = cfg or config.load()
    opt = cfg.get("optimizer_trial", {})
    ctx_base = {
        "patterns": opt.get("strippable_js_patterns"),
        "quality": opt.get("image_quality", 65),
        "formats": opt.get("formats", ["avif", "webp"]),
    }
    cap_default = opt.get("image_max_width", 1920)

    before = dict.fromkeys(("html", "css", "js", "images", "fonts", "other"), 0)
    after = dict(before)
    trials, stripped, co_benefits = [], [], []
    dynamic = set()
    needs_headless = login_wall = False
    pages_seen = 0
    # Coverage: how many referenced resources we actually sized, against how
    # many the pages referenced. A count of skips is not enough on its own,
    # because "12 uncounted" means nothing without the denominator.
    referenced = 0
    sized = 0

    for purl in sample_urls:
        body, ctype, wire = budget.get(purl)
        if body is None:
            continue
        pages_seen += 1
        html = body.decode("utf-8", "ignore")

        # Before is what crossed the wire (already compressed by the host);
        # after is what our pipeline would put on the wire.
        r = optimize("html", body, wire_before=wire, url=purl)
        before["html"] += r.before
        after["html"] += r.after

        if SPA_ROOT_RE.search(html):
            needs_headless = True
        if LOGIN_WALL_RE.search(html):
            login_wall = True
        for feat, pat in DYNAMIC_FEATURES:
            if re.search(pat, html, re.I):
                dynamic.add(feat)
        if not re.search(r'<meta[^>]+name=["\']description', html, re.I):
            co_benefits.append(f"missing meta description: {purl}")
        if re.findall(r'<img(?![^>]*\balt=)', html, re.I):
            co_benefits.append(f"images without alt text: {purl}")

        # Per-image declared widths. Images sized by CSS are absent from this
        # map and fall back to cap_default, so we never invent a display size.
        widths = _images.declared_widths(html, purl)
        tokens = _css.html_tokens(html)

        page_res = page_resources(html, purl)
        referenced += len(page_res)
        for rurl in page_res:
            info = budget.head(rurl)
            if not info:
                continue
            kind = classify(rurl, info.get("type", ""))
            size = info.get("bytes")
            if size is None:
                continue
            sized += 1
            if kind == "other" and rurl.lower().endswith(".js"):
                kind = "js"
            before[kind] += size

            # Deleting a request beats compressing it, and costs no budget.
            if kind in ("js", "other"):
                r = optimize(kind, b"", wire_before=size, url=rurl,
                             context=ctx_base)
                if r.after == 0:
                    stripped.append({"url": rurl, "bytes": size,
                                     "reason": r.method})
                    continue

            # Spend a body GET only where a measured trial changes the answer.
            if kind in ("images", "css") and budget.gets_left > 2:
                data, _, rwire = budget.get(
                    rurl, max_bytes=12_000_000 if kind == "images" else 4_000_000)
                if data is not None:
                    cap_w = min(widths.get(rurl, cap_default), cap_default)
                    ctx = {**ctx_base, "max_width": cap_w, "html_tokens": tokens}
                    r = optimize(kind, data, wire_before=rwire or size,
                                 url=rurl, context=ctx)
                    after[kind] += r.after
                    trials.append({"url": rurl, **r.as_dict()})
                    continue

            # Not measured: carry the original size through unchanged. We never
            # model a saving we did not observe.
            after[kind] += size

    return {
        "pages_sampled": pages_seen,
        "before_by_type": before,
        "after_by_type": after,
        "before_bytes": sum(before.values()),
        "after_bytes": sum(after.values()),
        "needs_headless": needs_headless,
        "login_wall": login_wall,
        "dynamic_features": sorted(dynamic),
        "measured_trials": trials[:25],
        "stripped": stripped[:25],
        "stripped_bytes": sum(s["bytes"] for s in stripped),
        "co_benefits": sorted(set(co_benefits))[:12],
        # When the budget runs out mid-page, resources go uncounted and the
        # measured weight is a FLOOR, not a total. Savings are then understated,
        # which is the safe direction, but the reader has to be told.
        "coverage_complete": budget.complete,
        "resources_uncounted": budget.skipped,
        "resources_referenced": referenced,
        "resources_sized": sized,
        "coverage_ratio": (sized / referenced) if referenced else 1.0,
    }


# --------------------------------------------------------- the payback math --

def payback(sample: dict, *, monthly_views: float, page_count: int,
            recrawls_per_month: float, green_hosted: bool,
            cfg: dict | None = None, ai: dict | None = None,
            grid: float | None = None,
            destination_green: bool = True) -> dict:
    """Recurring saving, one-time cost, payback period.

    `destination_green` gates the green-hosting bonus. The bonus is only real if
    the place we move the site to is actually verified; crediting it against an
    unverified destination would be inventing a saving.
    """
    cfg = cfg or config.load()
    cm = cfg.get("cost_model", {})
    repeat = cfg.get("carbon", {}).get("repeat_visit_factor",
                                       carbon.DEFAULT_REPEAT_VISIT_FACTOR)
    pages = max(1, sample["pages_sampled"])
    w_before = sample["before_bytes"] / pages
    w_after = sample["after_bytes"] / pages

    pv_before = carbon.per_view(w_before, green_hosted=green_hosted, grid=grid)
    pv_after = carbon.per_view(w_after, green_hosted=green_hosted, grid=grid)
    pv_after_green = carbon.per_view(w_after, green_hosted=True, grid=grid)

    # Bonus only when moving OFF a non-green host ONTO a verified green one.
    can_claim_green = (not green_hosted) and destination_green
    green_gain = ((pv_after["g_co2e"] - pv_after_green["g_co2e"])
                  if can_claim_green else 0.0)
    green_gain_cons = ((pv_after["g_co2e_conservative"]
                        - pv_after_green["g_co2e_conservative"])
                       if can_claim_green else 0.0)

    saved_per_view = (pv_before["g_co2e"] - pv_after["g_co2e"]) + green_gain
    saved_per_view_cons = ((pv_before["g_co2e_conservative"]
                            - pv_after["g_co2e_conservative"]) + green_gain_cons)
    saved_month = saved_per_view * monthly_views * repeat
    saved_month_cons = saved_per_view_cons * monthly_views * repeat

    crawl_bytes = page_count * w_before * (2 if sample["needs_headless"] else 1)
    crawl_g = carbon.per_view(crawl_bytes, grid=grid)["g_co2e"]
    compute_g = carbon.compute_g(cm.get("cpu_minutes_once", 15) * 60,
                                 grid=grid)["g_co2e"]
    ai_g = carbon.ai_g(ai["prompts"], ai["kind"], grid=grid)["g_co2e"] if ai else 0.0
    once = crawl_g + compute_g + ai_g + cm.get("deploy_g_co2e", 1.0)

    frac = cm.get("recrawl_change_fraction", 0.1)
    recrawl_g = carbon.per_view(frac * crawl_bytes, grid=grid)["g_co2e"]
    recrawl_compute = carbon.compute_g(
        cm.get("cpu_minutes_per_recrawl", 2) * 60, grid=grid)["g_co2e"]
    monthly_cost = recrawls_per_month * (recrawl_g + recrawl_compute)

    net = saved_month - monthly_cost
    net_cons = saved_month_cons - monthly_cost
    months = (once / net) if net > 0 else float("inf")

    return {
        "w_before_bytes": round(w_before),
        "w_after_bytes": round(w_after),
        "weight_cut_pct": round((1 - w_after / w_before) * 100) if w_before else 0,
        "g_per_view_before": pv_before["g_co2e"],
        "g_per_view_after": pv_after["g_co2e"],
        "g_per_view_before_conservative": pv_before["g_co2e_conservative"],
        "saved_per_view_g": saved_per_view,
        "green_bonus_g_per_view": green_gain,
        "green_bonus_claimed": can_claim_green,
        "one_time_g": once,
        "one_time_breakdown_g": {
            "crawl": round(crawl_g, 3), "compute": round(compute_g, 3),
            "ai": round(ai_g, 3), "deploy": cm.get("deploy_g_co2e", 1.0)},
        "ai_share_of_one_time_pct": round(ai_g / once * 100) if once else 0,
        "monthly_cost_g": monthly_cost,
        "net_monthly_g": net,
        "net_monthly_g_conservative": net_cons,
        "payback_months": months,
        "payback_days": round(months * 30, 1) if net > 0 else None,
        "annual_net_kg": net * 12 / 1000,
        "annual_net_kg_conservative": net_cons * 12 / 1000,
    }


def decide(p: dict, sample: dict, green_hosted: bool, cfg: dict | None = None,
           placeholder: bool = False, recrawls_per_month: float = 1) -> dict:
    """Evaluated in order, first match wins.

    On volatility: re-crawl churn is ALREADY priced into the recurring cost
    term, so gating the verdict on it as well would count the same churn twice
    and understate genuinely good jobs. What high churn changes is forecast
    confidence, not the arithmetic, so it attaches a caveat rather than a
    different verdict.
    """
    cfg = cfg or config.load()
    t = cfg.get("thresholds", {})
    lean = t.get("already_efficient_g_per_view", 0.1)
    tree_kg = cfg.get("equivalents", {}).get("tree_kg_co2_per_year", 21)

    if p["g_per_view_before"] < lean and green_hosted:
        key = "do_not_do_this_for_carbon"
        label = "SKIP - already efficient and green-hosted"
        msg = ("This site is already light and already on verified green "
               "hosting. A mirror would cost more carbon than it saves. If you "
               "want improvements, take the content and accessibility fixes "
               "below.")
    elif p["net_monthly_g"] <= 0:
        key = "do_not_do_this_for_carbon"
        label = "DO NOT DO THIS FOR CARBON"
        msg = ("Re-crawl overhead meets or exceeds the saving. This never pays "
               "back. Do not claim a carbon win for this site.")
    elif (p["payback_months"] > t.get("max_payback_months", 12)
          or p["annual_net_kg"] < t.get("min_annual_kg", 2)):
        key = "diminishing_returns"
        label = "DIMINISHING RETURNS"
        msg = (f"This pays back, but the whole stake is "
               f"{p['annual_net_kg']:.1f} kg/year, about "
               f"{p['annual_net_kg'] / tree_kg:.2f} of one tree. Do it for "
               f"speed, accessibility or hosting cost if you like. Do not sell "
               f"it as a carbon win.")
    elif p["payback_months"] <= t.get("clear_win_months", 3):
        key = "clear_win"
        label = "CLEAR WIN"
        msg = (f"Pays back in about {p['payback_days']:.0f} days, then saves "
               f"roughly {p['annual_net_kg_conservative']:.1f}-"
               f"{p['annual_net_kg']:.1f} kg CO2e/year. Proceed.")
    else:
        key = "worthwhile_if_stable"
        label = "WORTHWHILE IF CONTENT IS STABLE"
        msg = (f"Pays back in about {p['payback_months']:.1f} months. Worth it "
               f"while the content stays put; re-crawl churn on a fast-changing "
               f"site would erode it.")

    caveats = []
    if recrawls_per_month > 4 and key in ("clear_win", "worthwhile_if_stable"):
        caveats.append(
            f"Churn caveat: at {recrawls_per_month:.0f} re-crawls/month the "
            f"re-crawl cost is already in the math, but a site changing this "
            f"fast may not hold the weight we measured today. Re-run the gate "
            f"if the site is redesigned.")
    # Scale check, anchored to the tree-equivalent rather than an arbitrary
    # multiple of the pass threshold. A project can pay back in a day and still
    # be worth less than one tree per year, and saying so is the difference
    # between a proportionate claim and a press release.
    if key == "clear_win" and p["annual_net_kg"] < tree_kg:
        caveats.append(
            f"Scale caveat: this pays back quickly, but the whole annual stake "
            f"is {p['annual_net_kg']:.1f} kg, under one tree-equivalent "
            f"({tree_kg} kg/yr). Bundle it with the speed, accessibility and "
            f"hosting-cost work rather than selling it as a carbon project on "
            f"its own.")
    if not sample.get("coverage_complete", True):
        caveats.append(
            f"Coverage caveat: the request budget ran out with "
            f"{sample.get('resources_uncounted', 0)} resource(s) uncounted, so "
            f"the weight measured is a floor. The real page is heavier and the "
            f"real saving larger than stated.")
    if placeholder and key != "blocked":
        msg += (" ILLUSTRATIVE ONLY: no traffic figure was supplied, so this "
                "verdict rests on a placeholder and must not be quoted.")
    return {"key": key, "label": label, "message": msg, "caveats": caveats}


def ai_comparison(base_args: dict, ai: dict) -> dict:
    """The AI does not change what the optimized site saves. It only inflates
    the one-time cost, which is the whole argument in one table."""
    det = payback(**{**base_args, "ai": None})
    with_ai = payback(**{**base_args, "ai": ai})
    added = (with_ai["payback_months"] - det["payback_months"]
             if det["payback_months"] != float("inf") else float("inf"))
    return {
        "deterministic": {
            "one_time_kg": det["one_time_g"] / 1000,
            "payback_days": det["payback_days"],
            "payback_months": det["payback_months"]},
        "ai_assisted": {
            "one_time_kg": with_ai["one_time_g"] / 1000,
            "payback_days": with_ai["payback_days"],
            "payback_months": with_ai["payback_months"],
            "ai_share_pct": with_ai["ai_share_of_one_time_pct"],
            "prompts": ai["prompts"], "kind": ai["kind"]},
        "added_payback_months": added,
        "cost_multiple": (with_ai["one_time_g"] / det["one_time_g"]
                          if det["one_time_g"] else 0),
        "recommendation": (
            "Identical end state. The deterministic pipeline reaches the same "
            "bytes and costs a fraction of the carbon up front. Use AI only for "
            "the advisory write-up (about 3 prompts, negligible)."),
    }


# ------------------------------------------------------------ the gate API ---

def preflight(url: str, *, owns_site: bool = False,
              monthly_views: float | None = None, volatility: str = "monthly",
              pipeline: str = "deterministic", ai_prompts: int = 0,
              ai_kind: str = "heavy", sample_size: int | None = None,
              get_budget: int | None = None, head_budget: int | None = None,
              grid: float | None = None, destination: str | None = None,
              cfg: dict | None = None) -> dict:
    """Run the gate. Returns the full result dict; never raises on a bad site.

    `destination` is the host the site would move TO. When given it is
    greenchecked, and the green-hosting bonus is only credited if it verifies.
    """
    t0 = time.time()
    cfg = cfg or config.load()
    smp = cfg.get("sample", {})
    budget = fetch.Budget(
        gets=get_budget or smp.get("get_budget", 20),
        heads=head_budget or smp.get("head_budget", 60),
        timeout=smp.get("per_request_timeout_s", 20))

    base = url if url.startswith("http") else "https://" + url
    domain = urllib.parse.urlparse(base).netloc
    placeholder = monthly_views is None
    views = 5000.0 if placeholder else float(monthly_views)
    recrawls = cfg.get("volatility_recrawls_per_month", {}).get(volatility, 1)

    result = {
        "inputs": {
            "url": base, "monthly_views": views, "placeholder_mode": placeholder,
            "volatility": volatility, "recrawls_per_month": recrawls,
            "pipeline": pipeline,
            "sample_size": sample_size or smp.get("max_pages", 5),
            "destination": destination,
        },
        "carbon_model": {**carbon.model_footer(grid),
                         "_footer_text": carbon.footer_text(grid)},
    }

    def blocked(reasons):
        result["blocked_reasons"] = reasons
        result["verdict"] = {
            "key": "blocked", "label": "BLOCKED", "caveats": [],
            "message": "Nothing was crawled and no figures were produced."}
        result["budget"] = budget.summary()
        result["exit_code"] = EXIT_BLOCKED
        _meter_run(budget, t0)
        return result

    if not owns_site:
        return blocked(["ownership not attested. We do not mirror sites you do "
                        "not own or control."])

    robots = {"present": False, "allowed": True, "crawl_delay": None}
    if cfg.get("politeness", {}).get("respect_robots", True):
        robots = fetch.check_robots(base, budget)
        robots.pop("parser", None)
        if not robots["allowed"]:
            result["robots"] = robots
            return blocked([f"robots.txt disallows {budget.ua} on {base}"])
    result["robots"] = robots

    pages = fetch.sitemap_pages(base, domain, budget)
    page_count = len(pages) if pages else 25       # stated fallback, no sitemap
    n = sample_size or smp.get("max_pages", 5)
    sample_urls = fetch.pick_sample(base, pages, n) if pages else [base]

    green = fetch.greencheck(domain, budget)
    dest_green = {"green": True, "checked": False, "domain": None,
                  "note": "no destination given; the green-hosting bonus is "
                          "credited on the assumption the target host is "
                          "GWF-verified. Pass a destination to verify it."}
    if destination:
        dest_domain = urllib.parse.urlparse(
            destination if destination.startswith("http")
            else "https://" + destination).netloc
        dest_green = fetch.greencheck(dest_domain, budget)

    s = sample_pass(sample_urls, budget, cfg)
    result["sitemap_pages"] = page_count
    result["green"] = green
    result["destination_green"] = dest_green
    result["sample"] = s

    if s["login_wall"] and s["pages_sampled"] <= 1:
        return blocked(["the sampled pages are behind a login wall"])
    if s["before_bytes"] == 0:
        return blocked(["could not measure any bytes; the site was unreachable"])

    ai = ({"prompts": ai_prompts, "kind": ai_kind}
          if pipeline == "ai" and ai_prompts > 0 else None)
    base_args = {
        "sample": s, "monthly_views": views, "page_count": page_count,
        "recrawls_per_month": recrawls, "green_hosted": green["green"],
        "cfg": cfg, "grid": grid,
        "destination_green": bool(dest_green.get("green", True)),
    }
    p = payback(**base_args, ai=ai)

    result["payback"] = p
    result["verdict"] = decide(p, s, green["green"], cfg, placeholder, recrawls)
    if ai:
        result["ai_comparison"] = ai_comparison(base_args, ai)
    result["budget"] = budget.summary()
    result["exit_code"] = (EXIT_PROCEED
                           if result["verdict"]["key"] in VERDICT_PROCEED
                           else EXIT_ADVISED_AGAINST)
    _meter_run(budget, t0)
    return result


def _meter_run(budget: fetch.Budget, t0: float) -> None:
    """The gate meters itself like every other stage."""
    try:
        meter.record("preflight", bytes_transferred=budget.bytes,
                     seconds=time.time() - t0, ai_prompts=0,
                     browser_launches=0, note="sample pass, zero AI")
    except Exception:
        pass
