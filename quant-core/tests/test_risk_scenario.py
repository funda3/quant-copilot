"""
test_risk_scenario — Tests for quant_core.risk.scenario.run_parallel_curve_scenarios_irs

Coverage
--------
1.  Default scenario set returns all 7 expected keys.
2.  Custom shift_bps list produces the correct labels.
3.  The "0bp" scenario exactly reproduces the base NPV from _price_irs_core.
4.  Payer IRS: NPV increases monotonically as the shift increases
    (rising rates lift a payer's NPV because the float leg is worth more).
5.  Receiver IRS: NPV decreases monotonically as the shift increases.
6.  Payer and receiver NPVs are exact negations at every shift level.
7.  Notional scaling: doubling notional doubles every scenario NPV.
8.  Single-shift custom list is accepted and works.
9.  Bootstrapped (non-flat) curve smoke test.
10. Helper unit tests (_scenario_label, _DEFAULT_SHIFTS).
11. No regressions in other quant_core tests (implicit via import chain).

Canonical setup
---------------
* Valuation / start date : 2024-01-01
* Curve     : flat 8 %, 5Y, annual, ACT/365F → 5 pillars at 1Y … 5Y
* Swap      : 5Y annual ACT/365F payer, 8.5 % fixed, notional 1 000 000
"""
from __future__ import annotations

from datetime import date

import pytest

from quant_core.conventions.day_count import DayCount
from quant_core.curves.build_flat import flat_curve
from quant_core.curves.discount_curve import DiscountCurve
from quant_core.instruments.irs import VanillaIRS
from quant_core.pricing.irs_pricer import _price_irs_core  # noqa: PLC2701
from quant_core.risk.scenario import (
    _DEFAULT_SHIFTS,
    _scenario_label,
    run_parallel_curve_scenarios_irs,
)

# ===========================================================================
# Shared fixtures
# ===========================================================================

VAL = date(2024, 1, 1)
_DC = DayCount.ACT_365F


def _5y_curve() -> DiscountCurve:
    """Five annual pillars (1Y … 5Y) at flat 8 %."""
    return flat_curve(VAL, 0.08, 5, "annual", _DC)


def _payer(notional: float = 1_000_000.0) -> VanillaIRS:
    return VanillaIRS(
        valuation_date=VAL,
        start_date=VAL,
        tenor_years=5,
        notional=notional,
        fixed_rate=0.085,
        payment_frequency="annual",
        day_count=_DC,
        pay_receive="payer",
    )


def _receiver(notional: float = 1_000_000.0) -> VanillaIRS:
    return VanillaIRS(
        valuation_date=VAL,
        start_date=VAL,
        tenor_years=5,
        notional=notional,
        fixed_rate=0.085,
        payment_frequency="annual",
        day_count=_DC,
        pay_receive="receiver",
    )


# ===========================================================================
# 1. Default scenario set
# ===========================================================================


class TestDefaultScenarios:
    def test_default_keys_present(self):
        result = run_parallel_curve_scenarios_irs(_payer(), _5y_curve())
        expected = {_scenario_label(s) for s in _DEFAULT_SHIFTS}
        assert set(result.keys()) == expected

    def test_default_key_count(self):
        result = run_parallel_curve_scenarios_irs(_payer(), _5y_curve())
        assert len(result) == len(_DEFAULT_SHIFTS)

    def test_default_key_order_preserved(self):
        result = run_parallel_curve_scenarios_irs(_payer(), _5y_curve())
        assert list(result.keys()) == [_scenario_label(s) for s in _DEFAULT_SHIFTS]

    def test_default_values_are_floats(self):
        result = run_parallel_curve_scenarios_irs(_payer(), _5y_curve())
        assert all(isinstance(v, float) for v in result.values())


# ===========================================================================
# 2. Custom shift sets
# ===========================================================================


class TestCustomShifts:
    def test_custom_shift_set_labels(self):
        custom = [-500, 0, 500]
        result = run_parallel_curve_scenarios_irs(_payer(), _5y_curve(), shift_bps=custom)
        assert set(result.keys()) == {"-500bp", "0bp", "500bp"}

    def test_custom_shift_order_preserved(self):
        custom = [200, -200, 0]
        result = run_parallel_curve_scenarios_irs(_payer(), _5y_curve(), shift_bps=custom)
        assert list(result.keys()) == ["200bp", "-200bp", "0bp"]

    def test_single_shift(self):
        result = run_parallel_curve_scenarios_irs(_payer(), _5y_curve(), shift_bps=[100])
        assert list(result.keys()) == ["100bp"]
        assert isinstance(result["100bp"], float)

    def test_negative_only_shifts(self):
        result = run_parallel_curve_scenarios_irs(_payer(), _5y_curve(), shift_bps=[-50, -25])
        assert set(result.keys()) == {"-50bp", "-25bp"}


# ===========================================================================
# 3. Zero-shift base case
# ===========================================================================


class TestBaseCase:
    def test_zero_shift_equals_base_npv(self):
        swap = _payer()
        curve = _5y_curve()
        base_npv, _, _, _ = _price_irs_core(swap, curve)
        result = run_parallel_curve_scenarios_irs(swap, curve, shift_bps=[0])
        assert result["0bp"] == pytest.approx(base_npv, rel=1e-12)

    def test_zero_shift_in_default_set_equals_base_npv(self):
        swap = _payer()
        curve = _5y_curve()
        base_npv, _, _, _ = _price_irs_core(swap, curve)
        result = run_parallel_curve_scenarios_irs(swap, curve)
        assert result["0bp"] == pytest.approx(base_npv, rel=1e-12)

    def test_original_curve_not_mutated(self):
        """The base curve's discount factors are unchanged after scenario run."""
        curve = _5y_curve()
        original_dfs = list(curve.discount_factors)
        run_parallel_curve_scenarios_irs(_payer(), curve)
        assert curve.discount_factors == original_dfs


# ===========================================================================
# 4. Payer monotonicity
# ===========================================================================


class TestPayerMonotonicity:
    """
    For a payer IRS (pay fixed, receive float): higher rates → float leg worth
    more → NPV rises.  Verifies all adjacent shift pairs are strictly
    increasing when shifts are sorted.
    """

    def test_payer_npv_strictly_increasing_with_shift(self):
        result = run_parallel_curve_scenarios_irs(_payer(), _5y_curve())
        sorted_shifts = sorted(_DEFAULT_SHIFTS)
        npvs = [result[_scenario_label(s)] for s in sorted_shifts]
        for i in range(1, len(npvs)):
            assert npvs[i] > npvs[i - 1], (
                f"Payer NPV should strictly increase; "
                f"shift[{sorted_shifts[i - 1]}bp]={npvs[i - 1]:.2f} "
                f">= shift[{sorted_shifts[i]}bp]={npvs[i]:.2f}"
            )

    def test_payer_npv_at_200bp_above_base(self):
        result = run_parallel_curve_scenarios_irs(_payer(), _5y_curve())
        assert result["200bp"] > result["0bp"]

    def test_payer_npv_at_minus200bp_below_base(self):
        result = run_parallel_curve_scenarios_irs(_payer(), _5y_curve())
        assert result["-200bp"] < result["0bp"]


# ===========================================================================
# 5. Receiver monotonicity
# ===========================================================================


class TestReceiverMonotonicity:
    """
    For a receiver IRS (receive fixed, pay float): higher rates → float leg
    liability more expensive → NPV falls.
    """

    def test_receiver_npv_strictly_decreasing_with_shift(self):
        result = run_parallel_curve_scenarios_irs(_receiver(), _5y_curve())
        sorted_shifts = sorted(_DEFAULT_SHIFTS)
        npvs = [result[_scenario_label(s)] for s in sorted_shifts]
        for i in range(1, len(npvs)):
            assert npvs[i] < npvs[i - 1], (
                f"Receiver NPV should strictly decrease; "
                f"shift[{sorted_shifts[i - 1]}bp]={npvs[i - 1]:.2f} "
                f"<= shift[{sorted_shifts[i]}bp]={npvs[i]:.2f}"
            )

    def test_receiver_npv_at_200bp_below_base(self):
        result = run_parallel_curve_scenarios_irs(_receiver(), _5y_curve())
        assert result["200bp"] < result["0bp"]


# ===========================================================================
# 6. Payer / receiver exact negation
# ===========================================================================


class TestPayerReceiverSymmetry:
    def test_payer_receiver_exact_negation_at_every_shift(self):
        curve = _5y_curve()
        payer_result = run_parallel_curve_scenarios_irs(_payer(), curve)
        recv_result = run_parallel_curve_scenarios_irs(_receiver(), curve)
        for label in payer_result:
            assert payer_result[label] == pytest.approx(
                -recv_result[label], abs=1e-9
            ), f"Payer/receiver mismatch at {label}"

    def test_payer_receiver_negation_custom_shifts(self):
        curve = _5y_curve()
        custom = [-100, 0, 100]
        payer_result = run_parallel_curve_scenarios_irs(_payer(), curve, shift_bps=custom)
        recv_result = run_parallel_curve_scenarios_irs(_receiver(), curve, shift_bps=custom)
        for label in payer_result:
            assert payer_result[label] == pytest.approx(-recv_result[label], abs=1e-9)


# ===========================================================================
# 7. Notional scaling
# ===========================================================================


class TestNotionalScaling:
    def test_doubling_notional_doubles_every_scenario_npv(self):
        curve = _5y_curve()
        result_1m = run_parallel_curve_scenarios_irs(_payer(1_000_000.0), curve)
        result_2m = run_parallel_curve_scenarios_irs(_payer(2_000_000.0), curve)
        for label in result_1m:
            assert result_2m[label] == pytest.approx(
                2.0 * result_1m[label], rel=1e-9
            ), f"Notional scaling failed at {label}"

    def test_ten_times_notional_scales_every_scenario_npv(self):
        curve = _5y_curve()
        result_1m = run_parallel_curve_scenarios_irs(_payer(1_000_000.0), curve)
        result_10m = run_parallel_curve_scenarios_irs(_payer(10_000_000.0), curve)
        for label in result_1m:
            assert result_10m[label] == pytest.approx(
                10.0 * result_1m[label], rel=1e-9
            ), f"Notional scaling (×10) failed at {label}"


# ===========================================================================
# 9. Bootstrapped curve smoke test
# ===========================================================================


class TestBootstrappedCurve:
    @pytest.fixture()
    def bs_curve(self) -> DiscountCurve:
        from quant_core.curves.bootstrap_mixed import (
            bootstrap_discount_curve_from_market_records,
        )
        from quant_core.marketdata.normalize_rates import normalize_market_quotes
        from quant_core.schemas.market_inputs import (
            DepositQuote,
            FRAQuote,
            ParSwapQuote,
        )

        deposits = [
            DepositQuote(tenor_months=1, rate=0.078),
            DepositQuote(tenor_months=3, rate=0.079),
            DepositQuote(tenor_months=6, rate=0.080),
        ]
        fras = [
            FRAQuote(start_months=6, end_months=9, rate=0.081),
            FRAQuote(start_months=9, end_months=12, rate=0.0815),
        ]
        swaps = [
            ParSwapQuote(tenor_years=2, par_rate=0.082),
            ParSwapQuote(tenor_years=3, par_rate=0.083),
            ParSwapQuote(tenor_years=5, par_rate=0.085),
        ]
        records = normalize_market_quotes(deposits=deposits, fras=fras, swaps=swaps)
        return bootstrap_discount_curve_from_market_records(
            valuation_date=date(2024, 1, 15),
            records=records,
            payment_frequency="annual",
            day_count=DayCount.ACT_365F,
        )

    def test_bootstrapped_scenario_returns_expected_keys(self, bs_curve):
        swap = VanillaIRS(
            valuation_date=date(2024, 1, 15),
            start_date=date(2024, 1, 15),
            tenor_years=5,
            notional=1_000_000.0,
            fixed_rate=0.085,
            payment_frequency="annual",
            day_count=DayCount.ACT_365F,
            pay_receive="payer",
        )
        result = run_parallel_curve_scenarios_irs(swap, bs_curve)
        expected = {_scenario_label(s) for s in _DEFAULT_SHIFTS}
        assert set(result.keys()) == expected

    def test_bootstrapped_scenario_payer_monotone(self, bs_curve):
        swap = VanillaIRS(
            valuation_date=date(2024, 1, 15),
            start_date=date(2024, 1, 15),
            tenor_years=5,
            notional=1_000_000.0,
            fixed_rate=0.085,
            payment_frequency="annual",
            day_count=DayCount.ACT_365F,
            pay_receive="payer",
        )
        result = run_parallel_curve_scenarios_irs(swap, bs_curve)
        sorted_shifts = sorted(_DEFAULT_SHIFTS)
        npvs = [result[_scenario_label(s)] for s in sorted_shifts]
        for i in range(1, len(npvs)):
            assert npvs[i] > npvs[i - 1]


# ===========================================================================
# 10. Helper unit tests
# ===========================================================================


class TestHelpers:
    def test_scenario_label_negative(self):
        assert _scenario_label(-200) == "-200bp"

    def test_scenario_label_zero(self):
        assert _scenario_label(0) == "0bp"

    def test_scenario_label_positive(self):
        assert _scenario_label(100) == "100bp"

    def test_scenario_label_large_negative(self):
        assert _scenario_label(-1000) == "-1000bp"

    def test_default_shifts_sorted(self):
        assert _DEFAULT_SHIFTS == sorted(_DEFAULT_SHIFTS)

    def test_default_shifts_contains_zero(self):
        assert 0 in _DEFAULT_SHIFTS

    def test_default_shifts_contains_negatives(self):
        assert any(s < 0 for s in _DEFAULT_SHIFTS)

    def test_default_shifts_contains_positives(self):
        assert any(s > 0 for s in _DEFAULT_SHIFTS)
