"""
The carbon model must reproduce published Sustainable Web Design v4 figures.

These are the numbers every other claim in the project rests on, so they are
pinned here rather than left to drift. Offline; no network, no browser, no AI.
"""
import pytest

from oasis_sustain import carbon

MB = 1_000_000


# --- the published model ----------------------------------------------------

def test_full_system_intensity_is_swd_v4():
    """SWD v4 totals 0.30 kWh/GB across datacenter, network and device."""
    assert carbon._kwh_per_gb() == pytest.approx(0.30, abs=1e-9)


def test_segment_shares_sum_to_one():
    total = sum(carbon._segment_share(n) for n in carbon.SEGMENTS)
    assert total == pytest.approx(1.0, abs=1e-9)


def test_network_segment_is_about_a_quarter():
    """The conservative bound drops this segment, so its size is load-bearing."""
    assert carbon._segment_share("network") == pytest.approx(0.24, abs=1e-9)


def test_reference_page_weight():
    """1.6 MB is the design spec's reference page weight: 0.237 g per view.

    The spec quotes three decimals, so match to that precision rather than
    pinning float noise.
    """
    assert round(carbon.per_view(1.6 * MB)["g_co2e"], 3) == 0.237


def test_default_grid_intensity():
    assert carbon.grid_intensity() == 494.0


def test_energy_scales_linearly_with_bytes():
    assert carbon.energy_kwh(2 * MB) == pytest.approx(2 * carbon.energy_kwh(MB))


# --- two numbers, always ----------------------------------------------------

def test_marginal_factor_is_derived_not_hardcoded():
    """Editing SEGMENTS must move the bound. If this ever becomes a literal,
    the bound stops being honest the moment the model is revised."""
    assert carbon.marginal_factor() == pytest.approx(0.76, abs=1e-9)
    assert carbon.marginal_factor() == pytest.approx(
        1 - carbon._segment_share("network"), abs=1e-12)


def test_conservative_bound_is_below_the_model():
    r = carbon.per_view(1.6 * MB)
    assert r["g_co2e_conservative"] < r["g_co2e"]
    assert r["g_co2e_conservative"] / r["g_co2e"] == pytest.approx(0.76, abs=1e-9)


def test_range_str_renders_both_ends():
    s = carbon.range_str(5.9, 4.5)
    assert "4.50" in s and "5.90" in s and "g" in s


def test_range_str_orders_low_to_high_either_way():
    assert carbon.range_str(4.5, 5.9) == carbon.range_str(5.9, 4.5)


def test_range_str_inputs_are_always_grams():
    """display_unit renders, it does not describe the input. Passing kilograms
    would understate a published claim a thousandfold, so pin the contract."""
    assert carbon.range_str(5900, 4500, "kg") == "4.50-5.90 kg"
    assert carbon.range_str(5900, 4500) == "4500-5900 g"


# --- green hosting ----------------------------------------------------------

def test_green_hosting_reduces_emissions():
    dirty = carbon.per_view(MB, green_hosted=False)["g_co2e"]
    clean = carbon.per_view(MB, green_hosted=True)["g_co2e"]
    assert clean < dirty


def test_green_bonus_is_derived_and_modest():
    """Only the datacenter OPERATIONAL segment changes intensity, so the bonus
    is far smaller than the datacenter's 22.3% total share. A bonus anywhere
    near that share would mean the adjustment is being applied too broadly."""
    bonus = carbon.green_host_bonus()
    assert 0.0 < bonus < carbon._segment_share("datacenter")
    assert bonus == pytest.approx(0.1648, abs=1e-3)


def test_green_grid_is_configurable():
    """~245 g/kWh reproduces the 9% the original design spec asserted."""
    assert carbon.green_host_bonus(green_grid=245.0) == pytest.approx(0.09, abs=0.01)


def test_green_grid_of_zero_still_leaves_embodied_energy():
    """Even perfectly clean power does not zero the datacenter: embodied energy
    for the hardware is unaffected by what feeds it."""
    assert carbon.per_view(MB, green_hosted=True, green_grid=0.0)["g_co2e"] > 0


# --- compute and AI ---------------------------------------------------------

def test_compute_scales_with_time_and_watts():
    a = carbon.compute_g(3600, watts=65)
    assert a["kwh"] == pytest.approx(0.065)
    assert carbon.compute_g(3600, watts=130)["kwh"] == pytest.approx(2 * a["kwh"])


def test_ai_prompt_kinds_are_ordered_by_cost():
    w = carbon.AI_WH_PER_PROMPT
    assert w["chat"] < w["long_context"] < w["heavy"] < w["agentic_session"]


def test_ai_cost_scales_with_prompt_count():
    assert carbon.ai_g(100, "heavy")["wh"] == pytest.approx(
        10 * carbon.ai_g(10, "heavy")["wh"])


def test_unknown_ai_kind_falls_back_rather_than_crashing():
    assert carbon.ai_g(1, "no-such-kind")["g_co2e"] > 0


# --- provenance -------------------------------------------------------------

def test_footer_carries_everything_needed_to_challenge_a_figure():
    f = carbon.model_footer()
    assert f["model"] == "Sustainable Web Design v4"
    assert f["kwh_per_gb"] == pytest.approx(0.30)
    assert f["grid_g_per_kwh"] == 494.0
    assert f["grid_source"]
    assert f["computed_on"]                    # date
    assert "network" in f["conservative_bound"]
    assert f["config_sources"]                 # which files contributed


def test_footer_text_is_quotable_in_one_line():
    t = carbon.footer_text()
    for needed in ("Sustainable Web Design v4", "kWh/GB", "gCO2e/kWh", "Computed"):
        assert needed in t


def test_footer_marks_an_operator_supplied_grid_as_such():
    assert carbon.model_footer(grid=100.0)["grid_source"] == "operator-supplied"
