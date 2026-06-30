"""
test_bond_pricer — Tests for the fixed-rate bond pricing engine.

Coverage:
  - FixedRateBond construction validation (all invalid-input paths)
  - Zero-coupon bond pricing (single cashflow, zero accrued)
  - Single-period coupon bond with hand-computed expected values
  - Dirty price = PV of all remaining cashflows
  - Clean price = dirty price − accrued interest
  - Accrued interest: zero at issue, positive mid-period, hand-verified
  - Par bond: coupon at par rate produces dirty_price ≈ face_value
  - Canonical 5Y annual case: deterministic bounds
  - Remaining coupon count consistency
  - Result field types and internal identities
  - V1-style directional sanity (above/below par)
"""
from __future__ import annotations

from datetime import date

import pytest

from quant_core.conventions.day_count import DayCount, accrual_fraction
from quant_core.conventions.schedule import generate_unadjusted_dates
from quant_core.curves.build_flat import flat_curve
from quant_core.curves.discount_curve import DiscountCurve
from quant_core.instruments.bond import FixedRateBond
from quant_core.pricing.bond_pricer import (
    BondCashflowRow,
    BondResult,
    bond_cashflow_schedule,
    price_bond,
    solve_bond_ytm,
)


# ===========================================================================
# Shared helpers
# ===========================================================================


def _bond(**overrides) -> FixedRateBond:
    """Construct a valid FixedRateBond with sensible 5Y annual defaults."""
    defaults = dict(
        valuation_date=date(2024, 1, 1),
        issue_date=date(2024, 1, 1),
        maturity_date=date(2029, 1, 1),
        face_value=1_000_000.0,
        coupon_rate=0.08,
        coupon_frequency="annual",
        day_count=DayCount.ACT_365F,
    )
    defaults.update(overrides)
    return FixedRateBond(**defaults)


def _curve_for(
    bond: FixedRateBond,
    rate: float = 0.08,
    frequency: str = "annual",
) -> object:
    """Build a flat curve from bond.valuation_date covering bond.maturity_date."""
    # Compute tenor in whole years (ceil to ensure full coverage).
    delta_days = (bond.maturity_date - bond.valuation_date).days
    tenor = max(1, -(-delta_days // 365))  # ceiling division
    return flat_curve(bond.valuation_date, rate, tenor, frequency, bond.day_count)


# ===========================================================================
# FixedRateBond — construction validation
# ===========================================================================


class TestFixedRateBondConstruction:
    """Invalid arguments must raise ValueError with a meaningful message."""

    def test_face_value_zero_raises(self):
        with pytest.raises(ValueError, match="face_value"):
            _bond(face_value=0.0)

    def test_face_value_negative_raises(self):
        with pytest.raises(ValueError, match="face_value"):
            _bond(face_value=-1_000.0)

    def test_coupon_rate_negative_raises(self):
        with pytest.raises(ValueError, match="coupon_rate"):
            _bond(coupon_rate=-0.01)

    def test_coupon_rate_one_raises(self):
        with pytest.raises(ValueError, match="coupon_rate"):
            _bond(coupon_rate=1.0)

    def test_coupon_rate_above_one_raises(self):
        with pytest.raises(ValueError, match="coupon_rate"):
            _bond(coupon_rate=1.5)

    def test_maturity_equal_issue_raises(self):
        with pytest.raises(ValueError, match="maturity_date"):
            _bond(
                issue_date=date(2024, 1, 1),
                maturity_date=date(2024, 1, 1),
            )

    def test_maturity_before_issue_raises(self):
        with pytest.raises(ValueError, match="maturity_date"):
            _bond(
                issue_date=date(2024, 6, 1),
                maturity_date=date(2024, 1, 1),
            )

    def test_valuation_after_maturity_raises(self):
        with pytest.raises(ValueError, match="valuation_date"):
            _bond(
                valuation_date=date(2030, 1, 1),
                maturity_date=date(2029, 1, 1),
            )

    def test_invalid_frequency_raises(self):
        with pytest.raises(ValueError, match="coupon_frequency"):
            _bond(coupon_frequency="monthly")

    def test_invalid_frequency_weekly_raises(self):
        with pytest.raises(ValueError, match="coupon_frequency"):
            _bond(coupon_frequency="weekly")

    def test_valid_annual_constructs(self):
        b = _bond(coupon_frequency="annual")
        assert b.coupon_frequency == "annual"

    def test_valid_semiannual_constructs(self):
        b = _bond(coupon_frequency="semiannual")
        assert b.coupon_frequency == "semiannual"

    def test_valid_quarterly_constructs(self):
        b = _bond(coupon_frequency="quarterly")
        assert b.coupon_frequency == "quarterly"

    def test_coupon_rate_zero_allowed(self):
        # Zero coupon rate → zero-coupon bond; must not raise.
        b = _bond(coupon_rate=0.0)
        assert b.coupon_rate == 0.0

    def test_frequency_case_normalised(self):
        b = _bond(coupon_frequency="Annual")
        assert b.coupon_frequency == "annual"

    def test_valuation_equals_maturity_allowed(self):
        # Edge case: price on maturity date is permitted by the dataclass.
        b = _bond(
            valuation_date=date(2029, 1, 1),
            maturity_date=date(2029, 1, 1),
        )
        assert b.valuation_date == b.maturity_date

    def test_valuation_before_issue_allowed(self):
        # Pricing before issuance is valid per spec (valuation <= maturity only).
        b = _bond(
            valuation_date=date(2023, 6, 1),
            issue_date=date(2024, 1, 1),
        )
        assert b.valuation_date < b.issue_date


# ===========================================================================
# Zero-coupon bond
# ===========================================================================


class TestZeroCouponBond:
    """
    Zero-coupon bond (coupon_rate == 0.0).

    A ZCB has a single cashflow: face_value at maturity.  There are no coupon
    periods, so accrued_interest is always 0 and clean_price == dirty_price.
    """

    def setup_method(self):
        self.val = date(2024, 1, 1)
        self.issue = date(2024, 1, 1)
        self.maturity = date(2029, 1, 1)  # 5Y
        self.face = 1_000_000.0
        self.dc = DayCount.ACT_365F
        self.curve = flat_curve(self.val, 0.08, 5, "annual", self.dc)
        self.bond = FixedRateBond(
            self.val, self.issue, self.maturity,
            self.face, 0.0, "annual", self.dc,
        )
        self.result = price_bond(self.bond, self.curve)

    def test_accrued_interest_is_zero(self):
        assert self.result.accrued_interest == 0.0

    def test_clean_equals_dirty(self):
        assert self.result.clean_price == pytest.approx(
            self.result.dirty_price, rel=1e-12
        )

    def test_n_remaining_coupons_is_zero(self):
        assert self.result.n_remaining_coupons == 0

    def test_pv_cashflows_equals_dirty_price(self):
        assert self.result.pv_cashflows == pytest.approx(
            self.result.dirty_price, rel=1e-12
        )

    def test_dirty_price_matches_face_times_df(self):
        # pv = face_value * df(maturity)
        expected = self.face * self.curve.df(self.maturity)
        assert self.result.dirty_price == pytest.approx(expected, rel=1e-12)

    def test_dirty_price_in_plausible_range(self):
        # df(5Y) on 8% flat ≈ 0.714; price ≈ 714_000
        assert 690_000 < self.result.dirty_price < 740_000


# ===========================================================================
# Single-period coupon bond — hand-computed reference
# ===========================================================================


class TestSinglePeriodBond:
    """
    1Y annual coupon bond priced at issue on a flat 8% curve, 5% coupon.

    All expected values are derived analytically in the test so there is
    no magic-number dependency.

    Bond: issued 2024-01-01, matures 2025-01-01 (1 coupon, then principal).
    2024 is a leap year → the single coupon period has 366 days (ACT/365F).
    """

    def setup_method(self):
        self.val = date(2024, 1, 1)
        self.issue = date(2024, 1, 1)
        self.maturity = date(2025, 1, 1)
        self.face = 1_000_000.0
        self.coupon_rate = 0.05
        self.dc = DayCount.ACT_365F
        self.curve_rate = 0.08
        self.curve = flat_curve(self.val, self.curve_rate, 1, "annual", self.dc)
        self.bond = FixedRateBond(
            self.val, self.issue, self.maturity,
            self.face, self.coupon_rate, "annual", self.dc,
        )
        self.result = price_bond(self.bond, self.curve)

    def test_n_remaining_coupons_is_one(self):
        assert self.result.n_remaining_coupons == 1

    def test_accrued_interest_zero_at_issue(self):
        # valuation == issue → no accrual yet
        assert self.result.accrued_interest == pytest.approx(0.0, abs=1e-8)

    def test_dirty_price_matches_hand_computation(self):
        # tau_period(2024-01-01 → 2025-01-01) = 366/365 (ACT/365F, 2024 leap)
        tau = accrual_fraction(self.issue, self.maturity, self.dc)
        df = self.curve.df(self.maturity)
        expected = self.face * self.coupon_rate * tau * df + self.face * df
        assert self.result.dirty_price == pytest.approx(expected, rel=1e-10)

    def test_clean_equals_dirty_at_issue(self):
        # AI == 0 at issue → clean == dirty
        assert self.result.clean_price == pytest.approx(
            self.result.dirty_price, rel=1e-12
        )

    def test_dirty_price_below_face_when_coupon_below_rate(self):
        # 5% coupon < 8% market rate → bond prices below par
        assert self.result.dirty_price < self.face

    def test_pv_cashflows_equals_dirty_price(self):
        assert self.result.pv_cashflows == pytest.approx(
            self.result.dirty_price, rel=1e-12
        )


# ===========================================================================
# Accrued interest
# ===========================================================================


class TestAccruedInterest:
    """
    Accrued interest must be zero at issue, positive mid-period, and
    analytically consistent with the day-count convention.
    """

    def test_accrued_zero_at_issue_date(self):
        val = issue = date(2024, 1, 1)
        curve = flat_curve(val, 0.08, 2, "annual")
        bond = FixedRateBond(
            val, issue, date(2026, 1, 1), 1_000_000.0, 0.05, "annual",
            DayCount.ACT_365F,
        )
        r = price_bond(bond, curve)
        assert r.accrued_interest == pytest.approx(0.0, abs=1e-8)

    def test_accrued_positive_mid_period(self):
        # Valuation 6 months after issue, inside first annual coupon period.
        val = date(2024, 7, 1)
        issue = date(2024, 1, 1)
        maturity = date(2026, 1, 1)
        face = 1_000_000.0
        coupon_rate = 0.05
        dc = DayCount.ACT_365F

        # Use quarterly curve from valuation_date to cover coupon dates.
        curve = flat_curve(val, 0.08, 2, "quarterly", dc)
        bond = FixedRateBond(val, issue, maturity, face, coupon_rate, "annual", dc)
        r = price_bond(bond, curve)

        assert r.accrued_interest > 0.0

    def test_accrued_mid_period_hand_computed(self):
        # Exact value: face * coupon_rate * tau(issue, valuation, ACT/365F)
        val = date(2024, 7, 1)
        issue = date(2024, 1, 1)
        maturity = date(2026, 1, 1)
        face = 1_000_000.0
        coupon_rate = 0.05
        dc = DayCount.ACT_365F

        curve = flat_curve(val, 0.08, 2, "quarterly", dc)
        bond = FixedRateBond(val, issue, maturity, face, coupon_rate, "annual", dc)
        r = price_bond(bond, curve)

        # tau(2024-01-01, 2024-07-01, ACT/365F) = 182 days / 365
        expected_ai = face * coupon_rate * (val - issue).days / 365.0
        assert r.accrued_interest == pytest.approx(expected_ai, rel=1e-10)

    def test_accrued_zero_exactly_on_coupon_date(self):
        # valuation_date == 2nd annual coupon date: coupon was just paid → AI = 0.
        val = date(2025, 1, 1)  # exactly the first coupon date
        issue = date(2024, 1, 1)
        maturity = date(2026, 1, 1)
        dc = DayCount.ACT_365F
        face = 500_000.0
        coupon_rate = 0.06

        curve = flat_curve(val, 0.08, 1, "annual", dc)
        bond = FixedRateBond(
            val, issue, maturity, face, coupon_rate, "annual", dc
        )
        r = price_bond(bond, curve)
        assert r.accrued_interest == pytest.approx(0.0, abs=1e-8)

    def test_accrued_nonnegative_always(self):
        # Spot check at quarterly-aligned valuation dates so all annual coupon
        # dates (2025-01-01, ...) are exact quarterly pillars on every curve.
        issue = date(2024, 1, 1)
        maturity = date(2029, 1, 1)
        face = 1_000_000.0
        coupon_rate = 0.07
        dc = DayCount.ACT_365F

        val_dates = [
            date(2024, 1, 1),   # on issue
            date(2024, 4, 1),   # 3 months in
            date(2024, 7, 1),   # 6 months in (mid-first-period)
            date(2024, 10, 1),  # 9 months in
            date(2025, 1, 1),   # exactly first coupon date (AI resets to 0)
            date(2025, 7, 1),   # mid-second-period
        ]
        for val in val_dates:
            remaining_days = (maturity - val).days
            tenor = max(1, -(-remaining_days // 365))  # ceiling
            curve = flat_curve(val, 0.08, tenor, "quarterly", dc)
            bond = FixedRateBond(val, issue, maturity, face, coupon_rate, "annual", dc)
            r = price_bond(bond, curve)
            assert r.accrued_interest >= 0.0, f"accrued_interest < 0 at val={val}"


# ===========================================================================
# Clean / dirty price relationship
# ===========================================================================


class TestCleanDirtyRelationship:
    """
    clean_price == dirty_price - accrued_interest must hold exactly.
    """

    def test_clean_equals_dirty_minus_accrued(self):
        val = date(2024, 4, 1)  # mid-period
        issue = date(2024, 1, 1)
        maturity = date(2029, 1, 1)
        dc = DayCount.ACT_365F
        curve = flat_curve(val, 0.08, 5, "quarterly", dc)
        bond = FixedRateBond(val, issue, maturity, 1_000_000.0, 0.06, "annual", dc)
        r = price_bond(bond, curve)
        assert r.clean_price == pytest.approx(
            r.dirty_price - r.accrued_interest, rel=1e-12
        )

    def test_clean_equals_dirty_at_issue(self):
        val = issue = date(2024, 1, 1)
        curve = flat_curve(val, 0.08, 5, "annual")
        bond = _bond()
        r = price_bond(bond, curve)
        assert r.clean_price == pytest.approx(r.dirty_price, rel=1e-12)

    def test_clean_less_than_dirty_mid_period(self):
        # Mid-period: accrued_interest > 0, so clean < dirty
        val = date(2024, 4, 1)
        issue = date(2024, 1, 1)
        maturity = date(2026, 1, 1)
        dc = DayCount.ACT_365F
        curve = flat_curve(val, 0.08, 2, "quarterly", dc)
        bond = FixedRateBond(val, issue, maturity, 1_000_000.0, 0.07, "annual", dc)
        r = price_bond(bond, curve)
        assert r.clean_price < r.dirty_price

    def test_pv_cashflows_equals_dirty_price(self):
        curve = flat_curve(date(2024, 1, 1), 0.08, 5, "annual")
        bond = _bond()
        r = price_bond(bond, curve)
        assert r.pv_cashflows == pytest.approx(r.dirty_price, rel=1e-12)


# ===========================================================================
# At-par pricing
# ===========================================================================


class TestAtPar:
    """
    When the coupon rate equals the par rate implied by the curve, the bond's
    dirty price should equal the face value (to floating-point precision).

    The par rate satisfies:
        coupon_rate × Σ(τ_i × df_i) + df_N = 1
    =>  par_rate = (1 - df_N) / Σ(τ_i × df_i)

    Both the test and the pricer use the same formula and the same curve, so
    dirty_price should equal face_value to within floating-point rounding
    (< 1 currency unit for face_value = 1,000,000).
    """

    def test_par_annual_dirty_price_equals_face(self):
        val = issue = date(2024, 1, 1)
        maturity = date(2029, 1, 1)
        dc = DayCount.ACT_365F
        freq = "annual"
        rate = 0.08
        tenor = 5
        face = 1_000_000.0

        curve = flat_curve(val, rate, tenor, freq, dc)

        # Compute par rate using the same formula as the pricer.
        coupon_dates = generate_unadjusted_dates(issue, tenor, freq)
        period_starts = [issue] + coupon_dates[:-1]
        annuity = sum(
            accrual_fraction(ps, pe, dc) * curve.df(pe)
            for ps, pe in zip(period_starts, coupon_dates)
        )
        df_N = curve.df(maturity)
        par_rate = (1.0 - df_N) / annuity

        bond = FixedRateBond(val, issue, maturity, face, par_rate, freq, dc)
        r = price_bond(bond, curve)

        assert abs(r.dirty_price - face) < 1.0
        # At issue: AI == 0, so clean == dirty == face.
        assert r.accrued_interest == pytest.approx(0.0, abs=1e-8)
        assert abs(r.clean_price - face) < 1.0

    def test_par_semiannual_dirty_price_equals_face(self):
        val = issue = date(2024, 1, 1)
        maturity = date(2027, 1, 1)
        dc = DayCount.ACT_365F
        freq = "semiannual"
        rate = 0.06
        tenor = 3
        face = 500_000.0

        curve = flat_curve(val, rate, tenor, freq, dc)

        coupon_dates = generate_unadjusted_dates(issue, tenor, freq)
        period_starts = [issue] + coupon_dates[:-1]
        annuity = sum(
            accrual_fraction(ps, pe, dc) * curve.df(pe)
            for ps, pe in zip(period_starts, coupon_dates)
        )
        df_N = curve.df(maturity)
        par_rate = (1.0 - df_N) / annuity

        bond = FixedRateBond(val, issue, maturity, face, par_rate, freq, dc)
        r = price_bond(bond, curve)

        assert abs(r.dirty_price - face) < 1.0


# ===========================================================================
# Canonical 5Y annual case
# ===========================================================================


class TestCanonical:
    """
    Canonical case: 5Y annual 8% coupon on 8% flat curve, 1m face value.

    Because the simple-discount flat curve gives a par rate of ~7% (< 8%),
    an 8% coupon bond prices above par.  The test verifies deterministic
    bounds and internal consistency.
    """

    def setup_method(self):
        self.val = date(2024, 3, 20)
        self.issue = date(2024, 3, 20)
        self.maturity = date(2029, 3, 20)
        self.face = 1_000_000.0
        self.dc = DayCount.ACT_365F
        self.curve = flat_curve(self.val, 0.08, 5, "annual", self.dc)
        self.bond = FixedRateBond(
            self.val, self.issue, self.maturity,
            self.face, 0.08, "annual", self.dc,
        )
        self.result = price_bond(self.bond, self.curve)

    def test_n_remaining_coupons_is_five(self):
        assert self.result.n_remaining_coupons == 5

    def test_dirty_price_above_par(self):
        # coupon_rate (8%) > par_rate (~7%) → above par
        assert self.result.dirty_price > self.face

    def test_dirty_price_in_deterministic_bounds(self):
        # Conservative bounds: ±15% of face value
        assert 850_000 < self.result.dirty_price < 1_150_000

    def test_accrued_zero_at_issue(self):
        assert self.result.accrued_interest == pytest.approx(0.0, abs=1e-8)

    def test_clean_equals_dirty_at_issue(self):
        assert self.result.clean_price == pytest.approx(
            self.result.dirty_price, rel=1e-12
        )

    def test_pv_cashflows_identity(self):
        assert self.result.pv_cashflows == pytest.approx(
            self.result.dirty_price, rel=1e-12
        )

    def test_result_is_bond_result_instance(self):
        assert isinstance(self.result, BondResult)

    def test_all_fields_are_correct_types(self):
        r = self.result
        assert isinstance(r.dirty_price, float)
        assert isinstance(r.clean_price, float)
        assert isinstance(r.accrued_interest, float)
        assert isinstance(r.pv_cashflows, float)
        assert isinstance(r.n_remaining_coupons, int)


# ===========================================================================
# Remaining coupon count
# ===========================================================================


class TestRemainingCoupons:
    """n_remaining_coupons must count only coupon dates strictly after valuation_date."""

    def test_5y_annual_at_issue_has_5_remaining(self):
        val = issue = date(2024, 1, 1)
        maturity = date(2029, 1, 1)
        curve = flat_curve(val, 0.08, 5, "annual")
        bond = FixedRateBond(val, issue, maturity, 1_000_000.0, 0.07, "annual",
                             DayCount.ACT_365F)
        r = price_bond(bond, curve)
        assert r.n_remaining_coupons == 5

    def test_5y_semiannual_at_issue_has_10_remaining(self):
        val = issue = date(2024, 1, 1)
        maturity = date(2029, 1, 1)
        curve = flat_curve(val, 0.08, 5, "semiannual")
        bond = FixedRateBond(val, issue, maturity, 1_000_000.0, 0.07, "semiannual",
                             DayCount.ACT_365F)
        r = price_bond(bond, curve)
        assert r.n_remaining_coupons == 10

    def test_5y_quarterly_at_issue_has_20_remaining(self):
        val = issue = date(2024, 1, 1)
        maturity = date(2029, 1, 1)
        curve = flat_curve(val, 0.08, 5, "quarterly")
        bond = FixedRateBond(val, issue, maturity, 1_000_000.0, 0.07, "quarterly",
                             DayCount.ACT_365F)
        r = price_bond(bond, curve)
        assert r.n_remaining_coupons == 20

    def test_after_two_annual_coupons_three_remaining(self):
        # valuation = exactly the 2nd annual coupon date → AI = 0 and
        # remaining = [2027-01-01, 2028-01-01, 2029-01-01] = 3.
        issue = date(2024, 1, 1)
        val = date(2026, 1, 1)   # 2 coupons paid: 2025-01-01, 2026-01-01
        maturity = date(2029, 1, 1)
        # 3Y curve from val covers 2027-01-01, 2028-01-01, 2029-01-01
        curve = flat_curve(val, 0.08, 3, "annual")
        bond = FixedRateBond(val, issue, maturity, 1_000_000.0, 0.07, "annual",
                             DayCount.ACT_365F)
        r = price_bond(bond, curve)
        assert r.n_remaining_coupons == 3

    def test_1y_annual_two_periods_remaining_before_first_coupon(self):
        # 2Y annual, valuation mid-first-period → both coupons still remaining.
        val = date(2024, 6, 1)
        issue = date(2024, 1, 1)
        maturity = date(2026, 1, 1)
        curve = flat_curve(val, 0.08, 2, "quarterly")
        bond = FixedRateBond(val, issue, maturity, 500_000.0, 0.05, "annual",
                             DayCount.ACT_365F)
        r = price_bond(bond, curve)
        assert r.n_remaining_coupons == 2


# ===========================================================================
# Notional scaling
# ===========================================================================


class TestNotionalScaling:
    """Bond price must scale exactly linearly with face_value."""

    def test_double_face_doubles_dirty_price(self):
        val = issue = date(2024, 1, 1)
        maturity = date(2029, 1, 1)
        curve = flat_curve(val, 0.08, 5, "annual")
        bond_1x = FixedRateBond(val, issue, maturity, 1_000_000.0, 0.07, "annual",
                                DayCount.ACT_365F)
        bond_2x = FixedRateBond(val, issue, maturity, 2_000_000.0, 0.07, "annual",
                                DayCount.ACT_365F)
        r1 = price_bond(bond_1x, curve)
        r2 = price_bond(bond_2x, curve)
        assert r2.dirty_price == pytest.approx(2.0 * r1.dirty_price, rel=1e-12)
        assert r2.accrued_interest == pytest.approx(2.0 * r1.accrued_interest,
                                                     rel=1e-12)

    def test_double_face_doubles_clean_price(self):
        val = date(2024, 7, 1)
        issue = date(2024, 1, 1)
        maturity = date(2029, 1, 1)
        curve = flat_curve(val, 0.08, 5, "quarterly")
        bond_1x = FixedRateBond(val, issue, maturity, 1_000_000.0, 0.07, "annual",
                                DayCount.ACT_365F)
        bond_2x = FixedRateBond(val, issue, maturity, 2_000_000.0, 0.07, "annual",
                                DayCount.ACT_365F)
        r1 = price_bond(bond_1x, curve)
        r2 = price_bond(bond_2x, curve)
        assert r2.clean_price == pytest.approx(2.0 * r1.clean_price, rel=1e-12)


# ===========================================================================
# Day-count effect
# ===========================================================================


class TestDayCountEffect:
    """Different day-count conventions produce different prices."""

    def test_act365f_vs_act360_dirty_price_differs(self):
        val = issue = date(2024, 1, 1)
        maturity = date(2029, 1, 1)
        curve_365 = flat_curve(val, 0.08, 5, "annual", DayCount.ACT_365F)
        curve_360 = flat_curve(val, 0.08, 5, "annual", DayCount.ACT_360)
        bond_365 = FixedRateBond(val, issue, maturity, 1_000_000.0, 0.07, "annual",
                                 DayCount.ACT_365F)
        bond_360 = FixedRateBond(val, issue, maturity, 1_000_000.0, 0.07, "annual",
                                 DayCount.ACT_360)
        r_365 = price_bond(bond_365, curve_365)
        r_360 = price_bond(bond_360, curve_360)
        # ACT/360 denominator is smaller → larger τ → larger coupon PV
        assert r_360.dirty_price != pytest.approx(r_365.dirty_price)
        assert r_360.dirty_price > r_365.dirty_price


# ===========================================================================
# Above/below par sanity
# ===========================================================================


class TestAboveBelowPar:
    """
    Directional: bond price moves in the expected direction relative to par
    as coupon rate changes relative to the market rate.
    """

    def test_coupon_above_market_prices_above_par(self):
        val = issue = date(2024, 1, 1)
        maturity = date(2029, 1, 1)
        face = 1_000_000.0
        # Flat curve at 6%; coupon 8% > 6% par rate → above par
        curve = flat_curve(val, 0.06, 5, "annual")
        bond = FixedRateBond(val, issue, maturity, face, 0.08, "annual",
                             DayCount.ACT_365F)
        r = price_bond(bond, curve)
        assert r.dirty_price > face

    def test_coupon_below_market_prices_below_par(self):
        val = issue = date(2024, 1, 1)
        maturity = date(2029, 1, 1)
        face = 1_000_000.0
        # Flat curve at 10%; coupon 5% < 10% par rate → below par
        curve = flat_curve(val, 0.10, 5, "annual")
        bond = FixedRateBond(val, issue, maturity, face, 0.05, "annual",
                             DayCount.ACT_365F)
        r = price_bond(bond, curve)
        assert r.dirty_price < face

    def test_higher_coupon_has_higher_dirty_price(self):
        val = issue = date(2024, 1, 1)
        maturity = date(2029, 1, 1)
        face = 1_000_000.0
        curve = flat_curve(val, 0.08, 5, "annual")
        bond_lo = FixedRateBond(val, issue, maturity, face, 0.05, "annual",
                                DayCount.ACT_365F)
        bond_hi = FixedRateBond(val, issue, maturity, face, 0.10, "annual",
                                DayCount.ACT_365F)
        r_lo = price_bond(bond_lo, curve)
        r_hi = price_bond(bond_hi, curve)
        assert r_hi.dirty_price > r_lo.dirty_price


# ===========================================================================
# YTM solver — solve_bond_ytm
# ===========================================================================


class TestSolveBondYTM:
    """
    Tests for the bisection-based YTM solver.

    All round-trip tests: price a bond at a known flat yield, then verify
    that solve_bond_ytm recovers that yield from the resulting dirty price.
    """

    def test_coupon_bond_ytm_round_trip_8pct(self):
        bond = _bond(coupon_rate=0.08)
        target = 0.08
        result = price_bond(bond, _curve_for(bond, rate=target))
        ytm = solve_bond_ytm(bond, result.dirty_price)
        assert ytm == pytest.approx(target, abs=1e-8)

    def test_coupon_bond_ytm_round_trip_above_coupon(self):
        # Higher yield → below-par price
        bond = _bond(coupon_rate=0.08)
        target = 0.10
        result = price_bond(bond, _curve_for(bond, rate=target))
        ytm = solve_bond_ytm(bond, result.dirty_price)
        assert ytm == pytest.approx(target, abs=1e-8)

    def test_coupon_bond_ytm_round_trip_below_coupon(self):
        # Lower yield → above-par price
        bond = _bond(coupon_rate=0.08)
        target = 0.06
        result = price_bond(bond, _curve_for(bond, rate=target))
        ytm = solve_bond_ytm(bond, result.dirty_price)
        assert ytm == pytest.approx(target, abs=1e-8)

    def test_zcb_ytm_round_trip(self):
        bond = _bond(coupon_rate=0.0)
        target = 0.08
        result = price_bond(bond, _curve_for(bond, rate=target))
        ytm = solve_bond_ytm(bond, result.dirty_price)
        assert ytm == pytest.approx(target, abs=1e-8)

    def test_semiannual_coupon_ytm_round_trip(self):
        bond = _bond(coupon_frequency="semiannual")
        target = 0.09
        result = price_bond(bond, _curve_for(bond, rate=target, frequency="semiannual"))
        ytm = solve_bond_ytm(bond, result.dirty_price)
        assert ytm == pytest.approx(target, abs=1e-8)

    def test_seasoned_bond_ytm_round_trip_uses_remaining_cashflow_dates(self):
        # Regression: seasoned bonds can have first remaining coupon date before
        # the first generic tenor-grid pillar if curve pillars are not aligned
        # to the bond schedule.
        bond = FixedRateBond(
            valuation_date=date(2026, 3, 26),
            issue_date=date(2024, 1, 1),
            maturity_date=date(2029, 1, 1),
            face_value=1_000_000.0,
            coupon_rate=0.08,
            coupon_frequency="annual",
            day_count=DayCount.ACT_365F,
        )
        target = 0.08
        payment_dates = [
            date(2027, 1, 1),
            date(2028, 1, 1),
            date(2029, 1, 1),
        ]
        discount_factors = [
            1.0 / (1.0 + target * accrual_fraction(bond.valuation_date, d, bond.day_count))
            for d in payment_dates
        ]
        curve = DiscountCurve(bond.valuation_date, payment_dates, discount_factors)
        dirty = price_bond(bond, curve).dirty_price

        ytm = solve_bond_ytm(bond, dirty)
        assert ytm == pytest.approx(target, abs=1e-8)

    def test_ytm_monotone_with_price(self):
        # Higher market price → lower YTM (inverse relationship).
        bond = _bond(coupon_rate=0.08)
        price_low = price_bond(bond, _curve_for(bond, rate=0.10)).dirty_price
        price_high = price_bond(bond, _curve_for(bond, rate=0.06)).dirty_price
        ytm_at_low_price = solve_bond_ytm(bond, price_low)
        ytm_at_high_price = solve_bond_ytm(bond, price_high)
        assert ytm_at_low_price > ytm_at_high_price

    def test_ytm_override_day_count(self):
        # Explicit day_count override must be respected; round-trip still holds.
        bond = _bond(coupon_rate=0.08, day_count=DayCount.ACT_365F)
        target = 0.08
        curve = _curve_for(bond, rate=target)
        dirty = price_bond(bond, curve).dirty_price
        ytm = solve_bond_ytm(bond, dirty, day_count=DayCount.ACT_365F)
        assert ytm == pytest.approx(target, abs=1e-8)

    def test_invalid_market_dirty_price_zero_raises(self):
        bond = _bond()
        with pytest.raises(ValueError, match="market_dirty_price"):
            solve_bond_ytm(bond, 0.0)

    def test_invalid_market_dirty_price_negative_raises(self):
        bond = _bond()
        with pytest.raises(ValueError, match="market_dirty_price"):
            solve_bond_ytm(bond, -1.0)

    def test_absurd_price_above_undiscounted_sum_raises(self):
        # A market price higher than the undiscounted sum of all cashflows
        # cannot be achieved by any non-negative yield → ValueError.
        bond = _bond(coupon_rate=0.08, face_value=1_000_000.0)
        # Theoretical max (y=0): roughly face + all coupons at full value.
        # Using an absurdly large number guarantees f(0) < 0.
        with pytest.raises(ValueError):
            solve_bond_ytm(bond, 999_000_000.0)

    def test_result_is_float(self):
        bond = _bond(coupon_rate=0.08)
        dirty = price_bond(bond, _curve_for(bond, rate=0.08)).dirty_price
        ytm = solve_bond_ytm(bond, dirty)
        assert isinstance(ytm, float)


# ===========================================================================
# bond_cashflow_schedule
# ===========================================================================


class TestBondCashflowSchedule:
    """Tests for bond_cashflow_schedule() — structured cashflow transparency."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _coupon_bond(self, **overrides) -> tuple[FixedRateBond, object]:
        b = _bond(**overrides)
        c = _curve_for(b)
        return b, c

    def _zcb(self) -> tuple[FixedRateBond, object]:
        b = _bond(coupon_rate=0.0)
        c = _curve_for(b)
        return b, c

    # ------------------------------------------------------------------
    # Return type
    # ------------------------------------------------------------------

    def test_returns_list(self):
        bond, curve = self._coupon_bond()
        rows = bond_cashflow_schedule(bond, curve)
        assert isinstance(rows, list)

    def test_rows_are_bond_cashflow_row_instances(self):
        bond, curve = self._coupon_bond()
        rows = bond_cashflow_schedule(bond, curve)
        for row in rows:
            assert isinstance(row, BondCashflowRow)

    # ------------------------------------------------------------------
    # Coupon bond row count
    # ------------------------------------------------------------------

    def test_coupon_bond_row_count_matches_n_remaining_coupons(self):
        bond, curve = self._coupon_bond()
        rows = bond_cashflow_schedule(bond, curve)
        result = price_bond(bond, curve)
        assert len(rows) == result.n_remaining_coupons

    def test_5y_annual_at_issue_has_5_rows(self):
        bond, curve = self._coupon_bond()  # default: 5Y annual
        rows = bond_cashflow_schedule(bond, curve)
        assert len(rows) == 5

    def test_5y_semiannual_at_issue_has_10_rows(self):
        val = issue = date(2024, 1, 1)
        maturity = date(2029, 1, 1)
        bond = FixedRateBond(val, issue, maturity, 1_000_000.0, 0.08,
                             "semiannual", DayCount.ACT_365F)
        curve = flat_curve(val, 0.08, 5, "semiannual", DayCount.ACT_365F)
        rows = bond_cashflow_schedule(bond, curve)
        assert len(rows) == 10

    def test_5y_quarterly_at_issue_has_20_rows(self):
        val = issue = date(2024, 1, 1)
        maturity = date(2029, 1, 1)
        bond = FixedRateBond(val, issue, maturity, 1_000_000.0, 0.08,
                             "quarterly", DayCount.ACT_365F)
        curve = flat_curve(val, 0.08, 5, "quarterly", DayCount.ACT_365F)
        rows = bond_cashflow_schedule(bond, curve)
        assert len(rows) == 20

    # ------------------------------------------------------------------
    # Zero-coupon bond
    # ------------------------------------------------------------------

    def test_zcb_has_one_row(self):
        bond, curve = self._zcb()
        rows = bond_cashflow_schedule(bond, curve)
        assert len(rows) == 1

    def test_zcb_coupon_cashflow_is_zero(self):
        bond, curve = self._zcb()
        rows = bond_cashflow_schedule(bond, curve)
        assert rows[0].coupon_cashflow == 0.0

    def test_zcb_principal_equals_face_value(self):
        bond, curve = self._zcb()
        rows = bond_cashflow_schedule(bond, curve)
        assert rows[0].principal_cashflow == bond.face_value

    def test_zcb_total_cashflow_equals_face_value(self):
        bond, curve = self._zcb()
        rows = bond_cashflow_schedule(bond, curve)
        assert rows[0].total_cashflow == bond.face_value

    # ------------------------------------------------------------------
    # Final row carries principal
    # ------------------------------------------------------------------

    def test_final_row_principal_equals_face_value(self):
        bond, curve = self._coupon_bond()
        rows = bond_cashflow_schedule(bond, curve)
        assert rows[-1].principal_cashflow == pytest.approx(bond.face_value)

    def test_non_final_rows_have_zero_principal(self):
        bond, curve = self._coupon_bond()
        rows = bond_cashflow_schedule(bond, curve)
        for row in rows[:-1]:
            assert row.principal_cashflow == 0.0

    # ------------------------------------------------------------------
    # PV consistency
    # ------------------------------------------------------------------

    def test_sum_pv_cashflow_equals_dirty_price(self):
        bond, curve = self._coupon_bond()
        rows = bond_cashflow_schedule(bond, curve)
        total_pv = sum(r.pv_cashflow for r in rows)
        result = price_bond(bond, curve)
        assert total_pv == pytest.approx(result.dirty_price, rel=1e-10)

    def test_zcb_pv_cashflow_equals_dirty_price(self):
        bond, curve = self._zcb()
        rows = bond_cashflow_schedule(bond, curve)
        result = price_bond(bond, curve)
        assert rows[0].pv_cashflow == pytest.approx(result.dirty_price, rel=1e-10)

    def test_sum_pv_consistent_after_coupon_date(self):
        # Valuation mid-life: 2 coupons already paid.
        issue = date(2024, 1, 1)
        val = date(2026, 1, 1)
        maturity = date(2029, 1, 1)
        bond = FixedRateBond(val, issue, maturity, 1_000_000.0, 0.07,
                             "annual", DayCount.ACT_365F)
        curve = flat_curve(val, 0.08, 3, "annual", DayCount.ACT_365F)
        rows = bond_cashflow_schedule(bond, curve)
        result = price_bond(bond, curve)
        assert sum(r.pv_cashflow for r in rows) == pytest.approx(
            result.dirty_price, rel=1e-10
        )

    # ------------------------------------------------------------------
    # Row field sanity
    # ------------------------------------------------------------------

    def test_payment_dates_are_date_instances(self):
        bond, curve = self._coupon_bond()
        for row in bond_cashflow_schedule(bond, curve):
            assert isinstance(row.payment_date, date)

    def test_payment_dates_strictly_after_valuation(self):
        bond, curve = self._coupon_bond()
        for row in bond_cashflow_schedule(bond, curve):
            assert row.payment_date > bond.valuation_date

    def test_discount_factors_between_zero_and_one(self):
        bond, curve = self._coupon_bond()
        for row in bond_cashflow_schedule(bond, curve):
            assert 0.0 < row.discount_factor <= 1.0

    def test_year_fractions_positive(self):
        bond, curve = self._coupon_bond()
        for row in bond_cashflow_schedule(bond, curve):
            assert row.year_fraction > 0.0

    def test_time_to_payment_years_positive(self):
        bond, curve = self._coupon_bond()
        for row in bond_cashflow_schedule(bond, curve):
            assert row.time_to_payment_years > 0.0

    def test_total_cashflow_equals_coupon_plus_principal(self):
        bond, curve = self._coupon_bond()
        for row in bond_cashflow_schedule(bond, curve):
            assert row.total_cashflow == pytest.approx(
                row.coupon_cashflow + row.principal_cashflow, rel=1e-12
            )

    def test_pv_cashflow_equals_total_times_df(self):
        bond, curve = self._coupon_bond()
        for row in bond_cashflow_schedule(bond, curve):
            assert row.pv_cashflow == pytest.approx(
                row.total_cashflow * row.discount_factor, rel=1e-12
            )

    def test_payment_dates_are_chronological(self):
        val = issue = date(2024, 1, 1)
        maturity = date(2027, 1, 1)
        bond = FixedRateBond(val, issue, maturity, 1_000_000.0, 0.07,
                             "quarterly", DayCount.ACT_365F)
        curve = flat_curve(val, 0.08, 3, "quarterly", DayCount.ACT_365F)
        rows = bond_cashflow_schedule(bond, curve)
        dates = [r.payment_date for r in rows]
        assert dates == sorted(dates)

    def test_final_row_payment_date_is_maturity(self):
        bond, curve = self._coupon_bond()
        rows = bond_cashflow_schedule(bond, curve)
        assert rows[-1].payment_date == bond.maturity_date

    # ------------------------------------------------------------------
    # Consistency with price_bond (regression guard)
    # ------------------------------------------------------------------

    def test_price_bond_unchanged_by_refactor(self):
        # price_bond now uses _build_cashflows internally; verify output
        # matches hand-computed expected values for a simple 1Y bond.
        val = issue = date(2024, 1, 1)
        maturity = date(2025, 1, 1)
        face = 1_000_000.0
        rate = 0.08
        dc = DayCount.ACT_365F
        curve = flat_curve(val, rate, 1, "annual", dc)
        bond = FixedRateBond(val, issue, maturity, face, rate, "annual", dc)
        result = price_bond(bond, curve)
        # Single coupon + principal; discount factor = 1/(1+0.08*tau)
        tau = accrual_fraction(issue, maturity, dc)
        df = 1.0 / (1.0 + rate * tau)
        expected_pv = (face * rate * tau + face) * df
        assert result.dirty_price == pytest.approx(expected_pv, rel=1e-12)
        assert result.n_remaining_coupons == 1
        assert result.accrued_interest == pytest.approx(0.0, abs=1e-8)
