"""
Tests for quant_core curves layer — V2 Step 3.

Covers:
  - quant_core.curves.discount_curve  (DiscountCurve construction, df, zero_rate)
  - quant_core.curves.build_flat      (flat_curve builder)

All expected values are computed by hand and cross-checked analytically.

Conventions reminder:
  flat_curve uses simple discounting:  df(t) = 1 / (1 + r * tau)
  zero_rate uses continuous compounding: df(t) = exp(-r_c * tau)
  Therefore zero_rate on a flat simple-rate curve will NOT equal the input rate
  — it equals -log(df) / tau, which is slightly different from the simple rate.
  Tests verify this relationship explicitly rather than checking equality to the
  raw input rate.
"""
from __future__ import annotations

import math
from datetime import date

import pytest

from quant_core.conventions.day_count import DayCount, accrual_fraction
from quant_core.curves.build_flat import flat_curve
from quant_core.curves.discount_curve import DiscountCurve


# ===========================================================================
# Helpers
# ===========================================================================

def _make_simple_curve(
    val: tuple,
    pillars: list[tuple],
    dfs: list[float],
) -> DiscountCurve:
    """Convenience wrapper so tests aren't cluttered with date() calls."""
    return DiscountCurve(
        date(*val),
        [date(*p) for p in pillars],
        dfs,
    )


# ===========================================================================
# DiscountCurve — construction validation
# ===========================================================================

class TestDiscountCurveConstruction:
    """Invalid inputs must raise ValueError with a clear message."""

    def test_empty_pillars_raises(self):
        with pytest.raises(ValueError, match="empty"):
            DiscountCurve(date(2024, 1, 1), [], [])

    def test_mismatched_lengths_raises(self):
        with pytest.raises(ValueError, match="length"):
            DiscountCurve(
                date(2024, 1, 1),
                [date(2025, 1, 1)],
                [0.95, 0.90],
            )

    def test_non_increasing_pillars_raises(self):
        with pytest.raises(ValueError, match="strictly increasing"):
            DiscountCurve(
                date(2024, 1, 1),
                [date(2025, 1, 1), date(2025, 1, 1)],
                [0.95, 0.90],
            )

    def test_pillar_before_valuation_date_raises(self):
        with pytest.raises(ValueError, match="after"):
            DiscountCurve(
                date(2024, 6, 1),
                [date(2024, 6, 1)],   # same day — not after
                [0.99],
            )

    def test_pillar_equal_valuation_date_raises(self):
        with pytest.raises(ValueError, match="after"):
            DiscountCurve(
                date(2024, 1, 1),
                [date(2024, 1, 1)],
                [1.0],
            )

    def test_zero_discount_factor_raises(self):
        with pytest.raises(ValueError, match="positive"):
            DiscountCurve(
                date(2024, 1, 1),
                [date(2025, 1, 1)],
                [0.0],
            )

    def test_negative_discount_factor_raises(self):
        with pytest.raises(ValueError, match="positive"):
            DiscountCurve(
                date(2024, 1, 1),
                [date(2025, 1, 1)],
                [-0.5],
            )

    def test_valid_single_pillar_constructs(self):
        curve = DiscountCurve(
            date(2024, 1, 1),
            [date(2025, 1, 1)],
            [0.925],
        )
        assert curve.valuation_date == date(2024, 1, 1)
        assert len(curve.pillar_dates) == 1

    def test_valid_multi_pillar_constructs(self):
        curve = _make_simple_curve(
            (2024, 1, 1),
            [(2025, 1, 1), (2026, 1, 1), (2027, 1, 1)],
            [0.95, 0.90, 0.85],
        )
        assert len(curve.pillar_dates) == 3
        assert curve.discount_factors == [0.95, 0.90, 0.85]

    def test_pillar_dates_returns_copy(self):
        curve = _make_simple_curve(
            (2024, 1, 1),
            [(2025, 1, 1)],
            [0.95],
        )
        copy = curve.pillar_dates
        copy.append(date(2030, 1, 1))
        assert len(curve.pillar_dates) == 1   # internal list not mutated

    def test_discount_factors_returns_copy(self):
        curve = _make_simple_curve(
            (2024, 1, 1),
            [(2025, 1, 1)],
            [0.95],
        )
        copy = curve.discount_factors
        copy[0] = 0.0
        assert curve.discount_factors[0] == 0.95  # internal list not mutated


# ===========================================================================
# DiscountCurve — df() exact pillar lookup
# ===========================================================================

class TestDfExactPillar:
    """Querying at an exact pillar must return the stored value exactly."""

    def setup_method(self):
        self.curve = _make_simple_curve(
            (2024, 1, 1),
            [(2025, 1, 1), (2026, 1, 1), (2027, 1, 1)],
            [0.95, 0.90, 0.85],
        )

    def test_first_pillar(self):
        assert self.curve.df(date(2025, 1, 1)) == pytest.approx(0.95)

    def test_middle_pillar(self):
        assert self.curve.df(date(2026, 1, 1)) == pytest.approx(0.90)

    def test_last_pillar(self):
        assert self.curve.df(date(2027, 1, 1)) == pytest.approx(0.85)


# ===========================================================================
# DiscountCurve — df() log-linear interpolation
# ===========================================================================

class TestDfInterpolation:
    """Between-pillar interpolation uses log-linear."""

    def setup_method(self):
        # Two pillars exactly 365 days apart; df goes from 0.95 to 0.90.
        self.val = date(2024, 1, 1)
        self.p1 = date(2025, 1, 1)
        self.p2 = date(2026, 1, 1)
        self.df1 = 0.95
        self.df2 = 0.90
        self.curve = DiscountCurve(self.val, [self.p1, self.p2], [self.df1, self.df2])

    def _expected_log_linear(self, target: date) -> float:
        d_lo = self.p1.toordinal()
        d_hi = self.p2.toordinal()
        d_t  = target.toordinal()
        frac = (d_t - d_lo) / (d_hi - d_lo)
        log_df = math.log(self.df1) + frac * (math.log(self.df2) - math.log(self.df1))
        return math.exp(log_df)

    def test_midpoint(self):
        # Find the exact mid-ordinal.
        mid_ord = (self.p1.toordinal() + self.p2.toordinal()) // 2
        mid_date = date.fromordinal(mid_ord)
        expected = self._expected_log_linear(mid_date)
        assert self.curve.df(mid_date) == pytest.approx(expected, rel=1e-10)

    def test_one_third_point(self):
        d_lo = self.p1.toordinal()
        d_hi = self.p2.toordinal()
        one_third = date.fromordinal(d_lo + (d_hi - d_lo) // 3)
        expected = self._expected_log_linear(one_third)
        assert self.curve.df(one_third) == pytest.approx(expected, rel=1e-10)

    def test_result_is_strictly_between_pillar_dfs(self):
        # Any interpolated df must stay between the two bounding dfs.
        d_lo = self.p1.toordinal()
        d_hi = self.p2.toordinal()
        for offset in [30, 60, 90, 180, 270]:
            t = date.fromordinal(d_lo + offset)
            if t >= self.p2:
                continue
            d = self.curve.df(t)
            assert self.df2 < d < self.df1, f"df({t}) = {d} not in ({self.df2}, {self.df1})"

    def test_interpolated_df_never_extrapolates_above_first(self):
        # With positive rate: df at first pillar should be >=  any interpolated point
        d_lo = self.p1.toordinal()
        d_hi = self.p2.toordinal()
        t = date.fromordinal(d_lo + 1)
        assert self.curve.df(t) <= self.df1

    def test_three_pillar_second_segment(self):
        # Interpolation in the second segment of a 3-pillar curve.
        curve = _make_simple_curve(
            (2024, 1, 1),
            [(2025, 1, 1), (2026, 1, 1), (2027, 1, 1)],
            [0.95, 0.90, 0.85],
        )
        p2 = date(2026, 1, 1)
        p3 = date(2027, 1, 1)
        # Pick a date halfway between 2026-01-01 and 2027-01-01
        d_lo = p2.toordinal()
        d_hi = p3.toordinal()
        mid = date.fromordinal((d_lo + d_hi) // 2)
        frac = (mid.toordinal() - d_lo) / (d_hi - d_lo)
        expected = math.exp(
            math.log(0.90) + frac * (math.log(0.85) - math.log(0.90))
        )
        assert curve.df(mid) == pytest.approx(expected, rel=1e-10)


# ===========================================================================
# DiscountCurve — df() boundary errors
# ===========================================================================

class TestDfBoundaryErrors:
    """Requests outside the pillar range must raise ValueError."""

    def setup_method(self):
        self.curve = _make_simple_curve(
            (2024, 1, 1),
            [(2025, 1, 1), (2027, 1, 1)],
            [0.95, 0.85],
        )

    def test_before_first_pillar_raises(self):
        with pytest.raises(ValueError, match="before the first pillar"):
            self.curve.df(date(2024, 6, 1))

    def test_on_valuation_date_raises(self):
        with pytest.raises(ValueError, match="before the first pillar"):
            self.curve.df(date(2024, 1, 1))

    def test_after_last_pillar_raises(self):
        with pytest.raises(ValueError, match="after the last pillar"):
            self.curve.df(date(2028, 1, 1))

    def test_one_day_after_last_pillar_raises(self):
        with pytest.raises(ValueError, match="after the last pillar"):
            self.curve.df(date(2027, 1, 2))


# ===========================================================================
# DiscountCurve — zero_rate()
# ===========================================================================

class TestZeroRate:
    """Zero rates derived from stored discount factors."""

    def setup_method(self):
        # Build a 3-year annual curve with known, hand-computed dfs.
        # Using ACT/365F: tau = 365/365 = 1, 730/365 = 2, 1095/365 = 3
        # for simplicity we use exact calendar years so tau is ~1, ~2, ~3.
        self.val = date(2024, 1, 1)
        self.curve = DiscountCurve(
            self.val,
            [date(2025, 1, 1), date(2026, 1, 1), date(2027, 1, 1)],
            [0.95, 0.90, 0.85],
        )

    def test_zero_rate_formula_on_first_pillar(self):
        # r_c = -log(0.95) / tau(2024-01-01, 2025-01-01, ACT/365F)
        tau = accrual_fraction(self.val, date(2025, 1, 1), DayCount.ACT_365F)
        expected = -math.log(0.95) / tau
        assert self.curve.zero_rate(date(2025, 1, 1), DayCount.ACT_365F) == pytest.approx(expected, rel=1e-10)

    def test_zero_rate_formula_on_last_pillar(self):
        tau = accrual_fraction(self.val, date(2027, 1, 1), DayCount.ACT_365F)
        expected = -math.log(0.85) / tau
        assert self.curve.zero_rate(date(2027, 1, 1), DayCount.ACT_365F) == pytest.approx(expected, rel=1e-10)

    def test_zero_rate_different_day_count(self):
        # Different day_count changes tau and therefore zero_rate.
        r_365f = self.curve.zero_rate(date(2025, 1, 1), DayCount.ACT_365F)
        r_360  = self.curve.zero_rate(date(2025, 1, 1), DayCount.ACT_360)
        # tau_360 > tau_365f for same period, so r_360 < r_365f
        assert r_360 != pytest.approx(r_365f)

    def test_zero_rate_valuation_date_raises(self):
        with pytest.raises(ValueError, match="Year fraction"):
            self.curve.zero_rate(self.val, DayCount.ACT_365F)

    def test_zero_rate_before_first_pillar_raises(self):
        # df() will raise; zero_rate should propagate that.
        with pytest.raises(ValueError):
            self.curve.zero_rate(date(2024, 6, 1), DayCount.ACT_365F)

    def test_zero_rate_is_positive_for_sub_one_dfs(self):
        # All stored dfs < 1 → all zero rates > 0.
        for d in [date(2025, 1, 1), date(2026, 1, 1), date(2027, 1, 1)]:
            assert self.curve.zero_rate(d, DayCount.ACT_365F) > 0


# ===========================================================================
# flat_curve — construction and pillar counts
# ===========================================================================

class TestFlatCurveConstruction:
    """flat_curve builds a valid DiscountCurve with the right pillar layout."""

    def test_annual_1y_has_1_pillar(self):
        c = flat_curve(date(2024, 1, 1), 0.08, 1, "annual")
        assert len(c.pillar_dates) == 1

    def test_annual_5y_has_5_pillars(self):
        c = flat_curve(date(2024, 1, 1), 0.08, 5, "annual")
        assert len(c.pillar_dates) == 5

    def test_semiannual_5y_has_10_pillars(self):
        c = flat_curve(date(2024, 1, 1), 0.08, 5, "semiannual")
        assert len(c.pillar_dates) == 10

    def test_quarterly_5y_has_20_pillars(self):
        c = flat_curve(date(2024, 1, 1), 0.08, 5, "quarterly")
        assert len(c.pillar_dates) == 20

    def test_monthly_1y_has_12_pillars(self):
        c = flat_curve(date(2024, 1, 1), 0.08, 1, "monthly")
        assert len(c.pillar_dates) == 12

    def test_last_pillar_is_maturity(self):
        from quant_core.utils.date_utils import add_months
        val = date(2024, 3, 20)
        c = flat_curve(val, 0.08, 5, "quarterly")
        assert c.pillar_dates[-1] == add_months(val, 60)

    def test_returns_discount_curve_instance(self):
        c = flat_curve(date(2024, 1, 1), 0.08, 2)
        assert isinstance(c, DiscountCurve)

    def test_invalid_rate_raises(self):
        with pytest.raises(ValueError, match="-1"):
            flat_curve(date(2024, 1, 1), -1.5, 1)

    def test_invalid_frequency_raises(self):
        with pytest.raises(ValueError):
            flat_curve(date(2024, 1, 1), 0.08, 1, "weekly")

    def test_invalid_tenor_raises(self):
        with pytest.raises(ValueError):
            flat_curve(date(2024, 1, 1), 0.08, 0)


# ===========================================================================
# flat_curve — discount factor correctness
# ===========================================================================

class TestFlatCurveDfs:
    """Each pillar df must match the simple-discounting formula exactly."""

    def setup_method(self):
        self.val = date(2024, 1, 1)
        self.rate = 0.08
        self.dc = DayCount.ACT_365F
        self.curve = flat_curve(self.val, self.rate, 5, "annual", self.dc)

    def test_first_pillar_df_exact(self):
        tau = accrual_fraction(self.val, date(2025, 1, 1), self.dc)
        expected = 1.0 / (1.0 + self.rate * tau)
        assert self.curve.df(date(2025, 1, 1)) == pytest.approx(expected, rel=1e-12)

    def test_fifth_pillar_df_exact(self):
        tau = accrual_fraction(self.val, date(2029, 1, 1), self.dc)
        expected = 1.0 / (1.0 + self.rate * tau)
        assert self.curve.df(date(2029, 1, 1)) == pytest.approx(expected, rel=1e-12)

    def test_dfs_are_strictly_decreasing_for_positive_rate(self):
        dfs = self.curve.discount_factors
        for i in range(1, len(dfs)):
            assert dfs[i] < dfs[i - 1], f"df[{i}] = {dfs[i]} >= df[{i-1}] = {dfs[i-1]}"

    def test_all_dfs_positive(self):
        for df in self.curve.discount_factors:
            assert df > 0

    def test_all_dfs_less_than_one_for_positive_rate(self):
        for df in self.curve.discount_factors:
            assert df < 1.0

    def test_different_day_counts_produce_different_dfs(self):
        curve_365f = flat_curve(self.val, self.rate, 1, "annual", DayCount.ACT_365F)
        curve_360  = flat_curve(self.val, self.rate, 1, "annual", DayCount.ACT_360)
        # tau differs under the two conventions so dfs must differ
        assert curve_365f.discount_factors[0] != pytest.approx(curve_360.discount_factors[0])

    def test_zero_rate_recovers_consistent_value(self):
        # zero_rate = -log(df) / tau_continuous
        # For flat simple-rate curve, zero_rate ≈ rate but not exactly equal.
        # Verify zero_rate is positive and in the ballpark (within 30% of rate).
        for d in self.curve.pillar_dates:
            zr = self.curve.zero_rate(d, self.dc)
            assert zr > 0
            assert abs(zr - self.rate) / self.rate < 0.30  # within 30% of nominal


# ===========================================================================
# flat_curve — zero_rate recovers the rate relationship
# ===========================================================================

class TestFlatCurveZeroRate:
    """
    For a simple-rate curve df(t) = 1 / (1 + r*tau), the continuous zero rate
    satisfies:  r_c = -log(1/(1+r*tau)) / tau = log(1 + r*tau) / tau.
    This is strictly less than r for positive r and tau > 0.
    """

    def test_zero_rate_below_simple_rate(self):
        rate = 0.08
        curve = flat_curve(date(2024, 1, 1), rate, 5, "annual", DayCount.ACT_365F)
        for d in curve.pillar_dates:
            zr = curve.zero_rate(d, DayCount.ACT_365F)
            assert zr < rate, f"zero_rate {zr} should be < simple rate {rate}"

    def test_zero_rate_converges_to_simple_rate_for_short_tenor(self):
        # As tau → 0, continuous and simple rate converge.
        # Test with monthly curve, shortest pillar (1 month ~ 1/12 year).
        rate = 0.06
        curve = flat_curve(date(2024, 1, 1), rate, 1, "monthly", DayCount.ACT_365F)
        first_pillar = curve.pillar_dates[0]
        zr = curve.zero_rate(first_pillar, DayCount.ACT_365F)
        # For tau ≈ 1/12, absolute difference < 0.001
        assert abs(zr - rate) < 0.001

    def test_zero_rate_formula_matches_manual_computation(self):
        rate = 0.08
        val = date(2024, 1, 1)
        pillar = date(2025, 1, 1)   # 1Y
        curve = flat_curve(val, rate, 1, "annual", DayCount.ACT_365F)
        tau = accrual_fraction(val, pillar, DayCount.ACT_365F)
        df = 1.0 / (1.0 + rate * tau)
        expected_zr = math.log(1.0 + rate * tau) / tau
        assert curve.zero_rate(pillar, DayCount.ACT_365F) == pytest.approx(expected_zr, rel=1e-12)


# ===========================================================================
# flat_curve — different frequencies produce correct pillar spacings
# ===========================================================================

class TestFlatCurveFrequencies:
    """Pillar spacing is determined by the frequency parameter."""

    def test_quarterly_first_pillar_is_3m(self):
        from quant_core.utils.date_utils import add_months
        val = date(2024, 1, 1)
        curve = flat_curve(val, 0.05, 1, "quarterly")
        assert curve.pillar_dates[0] == add_months(val, 3)

    def test_semiannual_first_pillar_is_6m(self):
        from quant_core.utils.date_utils import add_months
        val = date(2024, 1, 1)
        curve = flat_curve(val, 0.05, 1, "semiannual")
        assert curve.pillar_dates[0] == add_months(val, 6)

    def test_monthly_second_pillar_is_2m(self):
        from quant_core.utils.date_utils import add_months
        val = date(2024, 1, 1)
        curve = flat_curve(val, 0.05, 1, "monthly")
        assert curve.pillar_dates[1] == add_months(val, 2)


# ===========================================================================
# Canonical integration — 5Y ZAR-style flat 8% quarterly
# ===========================================================================

class TestCanonicalFlatCurve:
    """
    Replicate the V1 pricer's flat-rate assumption using the V2 curve layer.

    V1 uses 8% flat, simple discounting, quarterly ZAR JIBAR for 5Y 250m.
    The V2 curve must produce discount factors consistent with that assumption.
    """

    def setup_method(self):
        self.val = date(2024, 3, 20)
        self.rate = 0.08
        self.curve = flat_curve(self.val, self.rate, 5, "quarterly", DayCount.ACT_365F)

    def test_20_pillars(self):
        assert len(self.curve.pillar_dates) == 20

    def test_first_df_roughly_correct(self):
        # First pillar: ~3 months out, tau ≈ 91/365 ≈ 0.249
        first = self.curve.pillar_dates[0]
        tau = accrual_fraction(self.val, first, DayCount.ACT_365F)
        expected = 1.0 / (1.0 + 0.08 * tau)
        assert self.curve.df(first) == pytest.approx(expected, rel=1e-10)

    def test_last_df_lower_than_first(self):
        assert self.curve.discount_factors[-1] < self.curve.discount_factors[0]

    def test_last_df_ballpark(self):
        # At 5Y with 8% simple rate: tau ≈ 5, df ≈ 1 / 1.4 ≈ 0.714
        last_df = self.curve.discount_factors[-1]
        assert 0.68 < last_df < 0.78
