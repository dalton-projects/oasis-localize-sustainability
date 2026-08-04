"""
The honesty regression gate.

The upstream review found two-number reporting and the model footer missing from
every output path, and an HTML report that fetched a webfont from Google on
every open. Tests are how those stay fixed. If a renderer ever drops the range,
the footer, or the ILLUSTRATIVE watermark, CI fails.

Offline. Results are constructed in-process; nothing here touches the network.
"""
import json
import re

import pytest

from oasis_sustain import config, preflight, report

MB = 1_000_000


def build_result(*, placeholder=False, ai=None, blocked=False,
                 destination_green=True, complete=True):
    """A full gate result without a network round trip."""
    if blocked:
        return {
            "inputs": {"url": "https://site.test", "monthly_views": 5000.0,
                       "placeholder_mode": False, "volatility": "monthly",
                       "recrawls_per_month": 1, "pipeline": "deterministic",
                       "sample_size": 5, "destination": None},
            "carbon_model": {"_footer_text": "Model: Sustainable Web Design v4 ..."},
            "blocked_reasons": ["ownership not attested."],
            "verdict": {"key": "blocked", "label": "BLOCKED", "caveats": [],
                        "message": "Nothing was crawled."},
            "budget": {"gets_used": 0, "heads_used": 0, "bytes": 0,
                       "skipped_over_budget": 0, "complete_coverage": True},
            "exit_code": 2,
        }

    cfg = config.load()
    s = {
        "pages_sampled": 5,
        "before_bytes": int(1.6 * MB * 5), "after_bytes": int(0.9 * MB * 5),
        "before_by_type": {}, "after_by_type": {},
        "needs_headless": False, "login_wall": False,
        "dynamic_features": ["forms"],
        "measured_trials": [{"url": "https://site.test/hero.png", "kind": "images",
                             "before": 504944, "after": 55792, "saved": 449152,
                             "reduction_pct": 89, "method": "avif q65", "notes": []}],
        "stripped": [{"url": "https://googletagmanager.com/gtm.js", "bytes": 90000,
                      "reason": "removed: third-party tracker"}],
        "stripped_bytes": 90000,
        "co_benefits": ["missing meta description: https://site.test"],
        "coverage_complete": complete,
        "resources_uncounted": 0 if complete else 12,
    }
    base = dict(sample=s, monthly_views=5000, page_count=50,
                recrawls_per_month=1, green_hosted=False, cfg=cfg, grid=None,
                destination_green=destination_green)
    p = preflight.payback(**base, ai=ai)
    r = {
        "inputs": {"url": "https://site.test", "monthly_views": 5000.0,
                   "placeholder_mode": placeholder, "volatility": "monthly",
                   "recrawls_per_month": 1,
                   "pipeline": "ai" if ai else "deterministic",
                   "sample_size": 5, "destination": None},
        "carbon_model": {"_footer_text":
                         "Model: Sustainable Web Design v4 (0.3 kWh/GB "
                         "full-system). Grid intensity 494 gCO2e/kWh. "
                         "Computed 2026-08-03."},
        "green": {"green": False, "checked": True},
        "destination_green": {"green": destination_green, "checked": True},
        "sitemap_pages": 50, "sample": s, "payback": p,
        "verdict": preflight.decide(p, s, False, cfg, placeholder, 1),
        "budget": {"gets_used": 20, "heads_used": 60, "bytes": 3_208_594,
                   "skipped_over_budget": 0 if complete else 12,
                   "complete_coverage": complete},
        "exit_code": 0,
    }
    if ai:
        r["ai_comparison"] = preflight.ai_comparison(base, ai)
    return r


ALL_FORMATS = ["text", "json", "html"]


# --- rule 1: two numbers, never one -----------------------------------------

@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_every_format_reports_a_range_not_a_point_value(fmt):
    out = report.render(build_result(), fmt)
    r = build_result()["payback"]
    lo = f"{r['annual_net_kg_conservative']:.1f}"
    hi = f"{r['annual_net_kg']:.1f}"
    assert lo in out and hi in out, f"{fmt} lost one end of the range"


def test_json_carries_both_bounds_as_fields():
    d = json.loads(report.render(build_result(), "json"))
    p = d["payback"]
    assert p["annual_net_kg_conservative"] < p["annual_net_kg"]
    assert p["net_monthly_g_conservative"] < p["net_monthly_g"]


# --- rule 2: the footer travels with the figure -----------------------------

@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_every_format_carries_the_model_footer(fmt):
    out = report.render(build_result(), fmt)
    assert "Sustainable Web Design v4" in out


@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_blocked_results_still_carry_the_footer(fmt):
    assert "Sustainable Web Design v4" in report.render(
        build_result(blocked=True), fmt)


# --- rule 3: placeholder figures are watermarked ----------------------------

def test_text_placeholder_is_marked_illustrative():
    out = report.render(build_result(placeholder=True), "text")
    assert "ILLUSTRATIVE" in out


def test_html_placeholder_is_watermarked_in_the_artifact_not_a_caption():
    """A caption can be cropped out of a screenshot. A CSS watermark cannot."""
    out = report.render(build_result(placeholder=True), "html")
    assert 'content:"ILLUSTRATIVE"' in out


def test_html_without_placeholder_has_no_watermark():
    assert 'content:"ILLUSTRATIVE"' not in report.render(build_result(), "html")


# --- the HTML report must not phone home ------------------------------------

@pytest.mark.parametrize("kwargs", [{}, {"placeholder": True},
                                    {"blocked": True},
                                    {"ai": {"prompts": 2000, "kind": "heavy"}}])
def test_html_makes_no_external_requests(kwargs):
    """No webfonts, no CDN, no analytics. A carbon report that fetches a font
    on every open is arguing against itself."""
    out = report.render(build_result(**kwargs), "html")
    external = re.findall(r'(?:src|href)\s*=\s*["\'](https?://[^"\']+)', out)
    assert external == [], f"external references: {external}"
    assert "@import" not in out


def test_html_escapes_untrusted_site_content():
    """URLs and resource names come from the audited site, which we do not
    control."""
    r = build_result()
    r["inputs"]["url"] = '<script>alert(1)</script>'
    out = report.render(r, "html")
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out


def test_html_wide_tables_scroll_rather_than_breaking_the_page():
    out = report.render(build_result(), "html")
    assert "overflow-x:auto" in out


# --- the AI comparison ------------------------------------------------------

@pytest.mark.parametrize("fmt", ["text", "html"])
def test_declared_ai_pipeline_shows_the_deterministic_row_beside_it(fmt):
    out = report.render(build_result(ai={"prompts": 2000, "kind": "heavy"}), fmt)
    assert "eterministic" in out
    assert "2,000" in out


def test_no_ai_section_when_the_pipeline_is_deterministic():
    assert "AI-assisted" not in report.render(build_result(), "text")


# --- disclosures ------------------------------------------------------------

def test_incomplete_coverage_is_disclosed_in_the_text_report():
    out = report.render(build_result(complete=False), "text")
    assert "FLOOR" in out or "floor" in out


def test_unverified_destination_is_stated_not_silently_dropped():
    out = report.render(build_result(destination_green=False), "text")
    assert "NOT credited" in out


def test_gate_cost_is_always_shown():
    out = report.render(build_result(), "text")
    assert "WHAT THIS GATE COST" in out
    assert "0 AI prompts" in out


def test_stripped_third_party_js_is_named_not_just_counted():
    out = report.render(build_result(), "text")
    assert "third-party JS removed" in out


# --- plumbing ---------------------------------------------------------------

def test_unknown_format_falls_back_to_text_rather_than_crashing():
    assert report.render(build_result(), "nonsense").startswith("\n===")


def test_wrap_never_exceeds_the_width():
    text = "word " * 80
    assert all(len(line) <= 40 for line in report.wrap(text, 40))


# --- CLI output-file format -------------------------------------------------

def test_out_file_format_follows_the_extension(tmp_path):
    """`--out result.json` must contain JSON, not the terminal rendering.
    Writing display text into a .json file breaks any pipeline reading it and
    nobody notices until it fails downstream."""
    from oasis_sustain import cli
    assert cli.OUT_FORMAT_BY_SUFFIX[".json"] == "json"
    assert cli.OUT_FORMAT_BY_SUFFIX[".html"] == "html"
    assert cli.OUT_FORMAT_BY_SUFFIX[".txt"] == "text"


def test_json_render_is_parseable():
    json.loads(report.render(build_result(), "json"))
