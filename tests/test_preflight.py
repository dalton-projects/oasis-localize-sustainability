"""
The decision math, and the honesty rules that constrain it.

The design spec's worked examples (section 8) are the acceptance criteria: if
these verdicts ever change, either the model changed or something is wrong, and
either way a human needs to look.

Offline. No network, no browser, no AI.
"""
import pytest

from oasis_sustain import config, preflight

MB = 1_000_000


def fake_sample(before_bytes, after_bytes, pages=5, headless=False,
                complete=True):
    """A sample_pass() result with known weights, so the decision math can be
    exercised without touching the network."""
    return {
        "pages_sampled": pages,
        "before_bytes": before_bytes * pages,
        "after_bytes": after_bytes * pages,
        "before_by_type": {}, "after_by_type": {},
        "needs_headless": headless, "login_wall": False,
        "dynamic_features": [], "measured_trials": [], "stripped": [],
        "stripped_bytes": 0, "co_benefits": [],
        "coverage_complete": complete, "resources_uncounted": 0 if complete else 7,
    }


def run(before, after, views, pages, recrawls, green, ai=None, headless=False,
        destination_green=True):
    cfg = config.load()
    s = fake_sample(before, after, headless=headless)
    base = dict(sample=s, monthly_views=views, page_count=pages,
                recrawls_per_month=recrawls, green_hosted=green, cfg=cfg,
                grid=None, destination_green=destination_green)
    p = preflight.payback(**base, ai=ai)
    v = preflight.decide(p, s, green, cfg, placeholder=False,
                         recrawls_per_month=recrawls)
    return p, v, base


# === design spec section 8: the worked examples =============================

def test_reference_site_deterministic_is_a_clear_win():
    """Spec: 0.021 kg one-time, ~1.3 days payback, clear win."""
    p, v, _ = run(1.6 * MB, 0.9 * MB, 5000, 50, 1, green=False)
    assert v["key"] == "clear_win"
    assert p["one_time_g"] / 1000 == pytest.approx(0.021, abs=0.002)
    assert p["payback_days"] == pytest.approx(1.3, abs=0.5)


def test_ai_rebuild_does_not_change_what_the_site_saves():
    """The AI changes the one-time cost only. That is the entire argument."""
    det, _, _ = run(1.6 * MB, 0.9 * MB, 5000, 50, 1, green=False)
    ai, _, _ = run(1.6 * MB, 0.9 * MB, 5000, 50, 1, green=False,
                   ai={"prompts": 2000, "kind": "heavy"})
    assert ai["net_monthly_g"] == pytest.approx(det["net_monthly_g"], rel=1e-9)


def test_ai_rebuild_one_time_cost_matches_the_spec():
    """Spec: 4.96 kg one-time, ~10 months payback, AI is ~100% of the cost."""
    p, _, _ = run(1.6 * MB, 0.9 * MB, 5000, 50, 1, green=False,
                  ai={"prompts": 2000, "kind": "heavy"})
    assert p["one_time_g"] / 1000 == pytest.approx(4.96, abs=0.01)
    assert p["ai_share_of_one_time_pct"] >= 99
    assert 8 < p["payback_months"] < 12


def test_ai_comparison_shows_the_deterministic_row_beside_it():
    _, _, base = run(1.6 * MB, 0.9 * MB, 5000, 50, 1, green=False)
    c = preflight.ai_comparison(base, {"prompts": 2000, "kind": "heavy"})
    assert c["cost_multiple"] > 100
    assert c["added_payback_months"] > 8
    assert c["deterministic"]["payback_days"] < c["ai_assisted"]["payback_days"]


def test_tiny_traffic_is_diminishing_returns():
    """Spec: 500 views/mo -> 0.6 kg/yr, not worth selling as a carbon win."""
    p, v, _ = run(1.6 * MB, 0.9 * MB, 500, 30, 1, green=False)
    assert v["key"] == "diminishing_returns"
    assert p["annual_net_kg"] == pytest.approx(0.6, abs=0.15)


def test_already_lean_and_green_is_refused():
    _, v, _ = run(0.09 * MB, 0.08 * MB, 5000, 20, 1, green=True)
    assert v["key"] == "do_not_do_this_for_carbon"
    assert "already" in v["label"].lower()


def test_heavy_high_traffic_site_is_a_clear_win():
    """Spec: 100k views/mo -> 287/219 kg/yr."""
    p, v, _ = run(3.0 * MB, 1.2 * MB, 100_000, 200, 4, green=False, headless=True)
    assert v["key"] == "clear_win"
    assert 200 < p["annual_net_kg"] < 400
    assert p["annual_net_kg_conservative"] < p["annual_net_kg"]


def test_headless_rendering_doubles_the_crawl_cost():
    plain, _, _ = run(3.0 * MB, 1.2 * MB, 100_000, 200, 4, green=False,
                      headless=False)
    spa, _, _ = run(3.0 * MB, 1.2 * MB, 100_000, 200, 4, green=False,
                    headless=True)
    assert spa["one_time_breakdown_g"]["crawl"] == pytest.approx(
        2 * plain["one_time_breakdown_g"]["crawl"])


def test_churn_that_outruns_the_saving_is_refused():
    _, v, _ = run(2.0 * MB, 1.1 * MB, 150, 400, 30, green=False)
    assert v["key"] == "do_not_do_this_for_carbon"


def test_high_churn_attaches_a_caveat_rather_than_a_different_verdict():
    """Re-crawl cost is already in the arithmetic. Gating on volatility too
    would double-count it."""
    p, v, _ = run(2.0 * MB, 1.1 * MB, 3000, 100, 30, green=False)
    assert p["monthly_cost_g"] > 50
    assert any("Churn caveat" in c for c in v["caveats"])


# === honesty rules ==========================================================

def test_placeholder_mode_watermarks_the_verdict():
    p, _, _ = run(1.6 * MB, 0.9 * MB, 5000, 50, 1, green=False)
    v = preflight.decide(p, fake_sample(1.6 * MB, 0.9 * MB), False,
                         config.load(), placeholder=True)
    assert "ILLUSTRATIVE" in v["message"]


def test_incomplete_coverage_is_disclosed_as_a_floor():
    cfg = config.load()
    s = fake_sample(1.6 * MB, 0.9 * MB, complete=False)
    p = preflight.payback(sample=s, monthly_views=5000, page_count=50,
                          recrawls_per_month=1, green_hosted=False, cfg=cfg)
    v = preflight.decide(p, s, False, cfg)
    assert any("floor" in c for c in v["caveats"])


def test_conservative_bound_always_sits_below_the_model():
    p, _, _ = run(1.6 * MB, 0.9 * MB, 5000, 50, 1, green=False)
    assert p["annual_net_kg_conservative"] < p["annual_net_kg"]
    assert p["net_monthly_g_conservative"] < p["net_monthly_g"]


def test_a_clear_win_worth_under_one_tree_says_so():
    """The spec's own reference row is a clear win at ~6 kg/yr and still
    carries the caveat: a fast payback on a tiny stake is not a carbon project.
    Anchored to the tree-equivalent, which is the unit the reports use."""
    p, v, _ = run(1.6 * MB, 0.9 * MB, 5000, 50, 1, green=False)
    assert v["key"] == "clear_win"
    assert p["annual_net_kg"] < 21
    assert any("Scale caveat" in c for c in v["caveats"])


def test_a_genuinely_large_win_carries_no_scale_caveat():
    _, v, _ = run(3.0 * MB, 1.2 * MB, 100_000, 200, 4, green=False)
    assert v["key"] == "clear_win"
    assert not any("Scale caveat" in c for c in v["caveats"])


# === the green-hosting bonus ================================================

def test_no_green_bonus_when_already_green_hosted():
    p, _, _ = run(1.6 * MB, 0.9 * MB, 5000, 50, 1, green=True)
    assert p["green_bonus_g_per_view"] == 0.0
    assert p["green_bonus_claimed"] is False


def test_green_bonus_is_credited_when_moving_to_a_verified_host():
    p, _, _ = run(1.6 * MB, 0.9 * MB, 5000, 50, 1, green=False,
                  destination_green=True)
    assert p["green_bonus_g_per_view"] > 0
    assert p["green_bonus_claimed"] is True


def test_green_bonus_is_refused_when_the_destination_is_not_verified():
    """The payback model credits a bonus for migrating. If the destination is
    not actually verified green, that bonus is invented."""
    p, _, _ = run(1.6 * MB, 0.9 * MB, 5000, 50, 1, green=False,
                  destination_green=False)
    assert p["green_bonus_g_per_view"] == 0.0
    assert p["green_bonus_claimed"] is False


def test_unverified_destination_lowers_the_claimed_saving():
    good, _, _ = run(1.6 * MB, 0.9 * MB, 5000, 50, 1, green=False,
                     destination_green=True)
    bad, _, _ = run(1.6 * MB, 0.9 * MB, 5000, 50, 1, green=False,
                    destination_green=False)
    assert bad["annual_net_kg"] < good["annual_net_kg"]


# === plumbing ===============================================================

def test_page_resources_resolves_and_dedupes():
    html = ('<link href="/a.css"><script src="https://cdn.x/b.js"></script>'
            '<img src="/a.css"><img src="data:image/png;base64,xx">')
    out = preflight.page_resources(html, "https://site.test/page/")
    assert "https://site.test/a.css" in out
    assert "https://cdn.x/b.js" in out
    assert len(out) == 2                      # deduped, data: URI skipped


def test_exit_codes_map_to_verdicts():
    assert preflight.EXIT_PROCEED == 0
    assert preflight.EXIT_ADVISED_AGAINST == 1
    assert preflight.EXIT_BLOCKED == 2
    assert set(preflight.VERDICT_PROCEED) == {"clear_win", "worthwhile_if_stable"}


def test_gate_without_ownership_attestation_is_blocked_before_any_request():
    """Must not touch the network at all. If this test ever needs one, the
    ownership check has moved too late."""
    r = preflight.preflight("https://example.invalid", owns_site=False)
    assert r["verdict"]["key"] == "blocked"
    assert r["exit_code"] == preflight.EXIT_BLOCKED
    assert r["budget"]["gets_used"] == 0
    assert "payback" not in r                 # no figures produced


def test_config_defaults_are_packaged_and_complete():
    cfg = config.load()
    for key in ("thresholds", "sample", "politeness", "carbon", "cost_model",
                "volatility_recrawls_per_month", "optimizer_trial"):
        assert key in cfg, f"missing config section: {key}"
    assert cfg["thresholds"]["clear_win_months"] == 3
    assert cfg["thresholds"]["max_payback_months"] == 12
