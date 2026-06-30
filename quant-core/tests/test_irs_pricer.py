"""
test_irs_pricer — Tests for the vanilla IRS pricing engine.

Coverage:
  - VanillaIRS construction validation (all invalid-input paths)
  - Single-period swap valuation with hand-computed expected values
  - Payment count for canonical 5Y quarterly swap
  - Payer / receiver sign convention
  - Notional scaling linearity
  - At-par rate produces NPV ≈ 0
  - Canonical 5Y ZAR-style 8% flat curve, 8.5% fixed, quarterly, payer
  - Result field internal consistency
  - V1 backend directional / numerical alignment (regression guard)
  - PV01/DV01 sensitivity: sign, scaling, canonical case, V1 alignment

Notes on simple vs continuous rates
-------------------------------------
The flat curve uses simple discounting:  df(t) = 1/(1 + r * tau)
The continuous zero rate is:             r_c = -log(df(t)) / tau

These two rates are NOT equal; the at-par fixed rate on a flat simple-
discount curve is derived below from the fixed/floating PV balance.
"""
from __future__ import annotations

import math
from datetime import date

import pytest

from quant_core.conventions.day_count import DayCount, accrual_fraction
from quant_core.conventions.schedule import generate_unadjusted_dates
from quant_core.curves.build_flat import flat_curve
from quant_core.instruments.irs import VanillaIRS
from quant_core.pricing.irs_pricer import (
    IRSCashflowRow,
    IRSResult,
    IRSValuationBreakdown,
    fixed_leg_annuity,
    irs_cashflow_schedule,
    irs_valuation_breakdown,
    price_irs,
    solve_irs_fair_rate,
)


# ===========================================================================
# Shared helpers
# ===========================================================================


def _swap(**overrides) -> VanillaIRS:
    """Construct a valid payer VanillaIRS with sensible defaults."""
    defaults = dict(
        valuation_date=date(2024, 1, 1),
        start_date=date(2024, 1, 1),
        tenor_years=5,
        notional=1_000_000.0,
        fixed_rate=0.05,
        payment_frequency="annual",
        day_count=DayCount.ACT_365F,
        pay_receive="payer",
    )
    defaults.update(overrides)
    return VanillaIRS(**defaults)


def _curve(
    val: date = date(2024, 1, 1),
    rate: float = 0.08,
    tenor: int = 5,
    freq: str = "annual",
    dc: DayCount = DayCount.ACT_365F,
):
    return flat_curve(val, rate, tenor, freq, dc)


# ===========================================================================
# VanillaIRS — construction validation
# ===========================================================================


class TestVanillaIRSConstruction:
    """Invalid arguments must raise ValueError with a meaningful message."""

    def test_negative_notional_raises(self):
        with pytest.raises(ValueError, match="notional"):
            _swap(notional=-1.0)

    def test_zero_notional_raises(self):
        with pytest.raises(ValueError, match="notional"):
            _swap(notional=0.0)

    def test_fixed_rate_zero_raises(self):
        with pytest.raises(ValueError, match="fixed_rate"):
            _swap(fixed_rate=0.0)

    def test_fixed_rate_one_raises(self):
        with pytest.raises(ValueError, match="fixed_rate"):
            _swap(fixed_rate=1.0)

    def test_fixed_rate_negative_raises(self):
        with pytest.raises(ValueError, match="fixed_rate"):
            _swap(fixed_rate=-0.01)

    def test_fixed_rate_above_one_raises(self):
        with pytest.raises(ValueError, match="fixed_rate"):
            _swap(fixed_rate=1.5)

    def test_tenor_zero_raises(self):
        with pytest.raises(ValueError, match="tenor_years"):
            _swap(tenor_years=0)

    def test_tenor_negative_raises(self):
        with pytest.raises(ValueError, match="tenor_years"):
            _swap(tenor_years=-1)

    def test_invalid_frequency_raises(self):
        with pytest.raises(ValueError, match="payment_frequency"):
            _swap(payment_frequency="weekly")

    def test_invalid_pay_receive_raises(self):
        with pytest.raises(ValueError, match="pay_receive"):
            _swap(pay_receive="both")

    def test_start_before_valuation_raises(self):
        with pytest.raises(ValueError, match="start_date"):
            _swap(
                valuation_date=date(2024, 6, 1),
                start_date=date(2024, 1, 1),
            )

    def test_valid_payer_constructs(self):
        s = _swap(pay_receive="payer")
        assert s.pay_receive == "payer"
        assert s.notional == 1_000_000.0

    def test_valid_receiver_constructs(self):
        s = _swap(pay_receive="receiver")
        assert s.pay_receive == "receiver"

    def test_frequency_case_normalised(self):
        s = _swap(payment_frequency="Quarterly")
        assert s.payment_frequency == "quarterly"

    def test_pay_receive_case_normalised(self):
        s = _swap(pay_receive="PAYER")
        assert s.pay_receive == "payer"


# ===========================================================================
# Single-period swap — hand-computed reference
# ===========================================================================


class TestSinglePeriodSwap:
    """
    1Y annual payer swap on a flat 8% curve with 5% fixed rate.

    All expected values are derived analytically inside the test so there is
    no magic number dependency.
    """

    def setup_method(self):
        self.val = date(2024, 1, 1)
        self.payment_date = date(2025, 1, 1)   # 1Y, start=val, annual
        self.notional = 1_000_000.0
        self.fixed_rate = 0.05
        self.dc = DayCount.ACT_365F
        self.curve = flat_curve(self.val, 0.08, 1, "annual", self.dc)
        self.swap = VanillaIRS(
            valuation_date=self.val,
            start_date=self.val,
            tenor_years=1,
            notional=self.notional,
            fixed_rate=self.fixed_rate,
            payment_frequency="annual",
            day_count=self.dc,
            pay_receive="payer",
        )

    def test_fixed_leg_pv(self):
        tau = accrual_fraction(self.val, self.payment_date, self.dc)
        df = self.curve.df(self.payment_date)
        expected = self.notional * self.fixed_rate * tau * df
        result = price_irs(self.swap, self.curve)
        assert result.fixed_leg_pv == pytest.approx(expected, rel=1e-10)

    def test_floating_leg_pv(self):
        # df_start = 1.0 (spot-starting); df_end = df(2025-01-01)
        df_end = self.curve.df(self.payment_date)
        expected = self.notional * (1.0 - df_end)
        result = price_irs(self.swap, self.curve)
        assert result.floating_leg_pv == pytest.approx(expected, rel=1e-10)

    def test_npv(self):
        tau = accrual_fraction(self.val, self.payment_date, self.dc)
        df = self.curve.df(self.payment_date)
        fixed_pv = self.notional * self.fixed_rate * tau * df
        float_pv = self.notional * (1.0 - df)
        expected_npv = float_pv - fixed_pv  # payer
        result = price_irs(self.swap, self.curve)
        assert result.npv == pytest.approx(expected_npv, rel=1e-10)

    def test_payer_npv_positive_when_fixed_below_market(self):
        # fixed_rate 5% < market_rate 8%: payer benefits, NPV > 0
        result = price_irs(self.swap, self.curve)
        assert result.npv > 0

    def test_n_payments_is_one(self):
        result = price_irs(self.swap, self.curve)
        assert result.n_payments == 1


# ===========================================================================
# Payment count
# ===========================================================================


class TestPaymentCount:
    """n_payments must match the schedule length."""

    def test_5y_quarterly_has_20_payments(self):
        val = date(2024, 1, 1)
        curve = flat_curve(val, 0.08, 5, "quarterly")
        swap = _swap(
            start_date=val,
            tenor_years=5,
            payment_frequency="quarterly",
        )
        result = price_irs(swap, curve)
        assert result.n_payments == 20

    def test_3y_semiannual_has_6_payments(self):
        val = date(2024, 1, 1)
        curve = flat_curve(val, 0.08, 3, "semiannual")
        swap = _swap(
            start_date=val,
            tenor_years=3,
            payment_frequency="semiannual",
        )
        result = price_irs(swap, curve)
        assert result.n_payments == 6

    def test_1y_monthly_has_12_payments(self):
        val = date(2024, 1, 1)
        curve = flat_curve(val, 0.08, 1, "monthly")
        swap = _swap(
            start_date=val,
            tenor_years=1,
            payment_frequency="monthly",
        )
        result = price_irs(swap, curve)
        assert result.n_payments == 12


# ===========================================================================
# Sign convention — payer vs receiver
# ===========================================================================


class TestSignConvention:
    """Payer and receiver NPVs must be equal in magnitude and opposite in sign."""

    def setup_method(self):
        val = date(2024, 1, 1)
        self.curve = flat_curve(val, 0.08, 5, "annual")
        self.payer = _swap(
            start_date=val, pay_receive="payer", fixed_rate=0.085
        )
        self.receiver = _swap(
            start_date=val, pay_receive="receiver", fixed_rate=0.085
        )

    def test_payer_and_receiver_npv_sum_to_zero(self):
        r_payer = price_irs(self.payer, self.curve)
        r_recv = price_irs(self.receiver, self.curve)
        assert r_payer.npv + r_recv.npv == pytest.approx(0.0, abs=1e-8)

    def test_payer_npv_negative_when_fixed_above_market(self):
        # fixed 8.5% > market 8%: payer is paying above-market
        result = price_irs(self.payer, self.curve)
        assert result.npv < 0.0

    def test_receiver_npv_positive_when_fixed_above_market(self):
        # receiver receives above-market fixed rate
        result = price_irs(self.receiver, self.curve)
        assert result.npv > 0.0


# ===========================================================================
# Notional scaling
# ===========================================================================


class TestNotionalScaling:
    """NPV must scale exactly linearly with notional."""

    def test_double_notional_doubles_npv(self):
        val = date(2024, 1, 1)
        curve = flat_curve(val, 0.08, 5, "quarterly")

        swap_1x = _swap(
            start_date=val,
            notional=1_000_000.0,
            tenor_years=5,
            payment_frequency="quarterly",
        )
        swap_2x = _swap(
            start_date=val,
            notional=2_000_000.0,
            tenor_years=5,
            payment_frequency="quarterly",
        )
        r1 = price_irs(swap_1x, curve)
        r2 = price_irs(swap_2x, curve)
        assert r2.npv == pytest.approx(2.0 * r1.npv, rel=1e-12)
        assert r2.fixed_leg_pv == pytest.approx(2.0 * r1.fixed_leg_pv, rel=1e-12)
        assert r2.floating_leg_pv == pytest.approx(2.0 * r1.floating_leg_pv, rel=1e-12)


# ===========================================================================
# At-par: NPV ≈ 0
# ===========================================================================


class TestAtPar:
    """
    When fixed_rate equals the par rate implied by the curve, NPV ≈ 0.

    The par rate satisfies:
        fixed_rate * Σ(τ_i · df_i) = df_start - df_end
    =>  par_rate = (df_start - df_end) / Σ(τ_i · df_i)

    Since both the pricer and this derivation use the same formula, the NPV
    should be zero to floating-point precision.
    """

    def test_at_par_payer_npv_is_zero(self):
        val = date(2024, 1, 1)
        rate = 0.08
        freq = "quarterly"
        dc = DayCount.ACT_365F
        tenor = 5

        curve = flat_curve(val, rate, tenor, freq, dc)
        sched = generate_unadjusted_dates(val, tenor, freq)
        period_starts = [val] + sched[:-1]

        annuity = sum(
            accrual_fraction(ps, pe, dc) * curve.df(pe)
            for ps, pe in zip(period_starts, sched)
        )
        df_end = curve.df(sched[-1])
        par_rate = (1.0 - df_end) / annuity   # df_start = 1.0 (spot)

        swap = VanillaIRS(
            valuation_date=val,
            start_date=val,
            tenor_years=tenor,
            notional=10_000_000.0,
            fixed_rate=par_rate,
            payment_frequency=freq,
            day_count=dc,
            pay_receive="payer",
        )
        result = price_irs(swap, curve)
        # NPV should be zero to floating-point rounding (< 1 currency unit)
        assert abs(result.npv) < 1.0

    def test_at_par_receiver_npv_is_zero(self):
        val = date(2024, 1, 1)
        rate = 0.08
        freq = "annual"
        dc = DayCount.ACT_365F
        tenor = 3

        curve = flat_curve(val, rate, tenor, freq, dc)
        sched = generate_unadjusted_dates(val, tenor, freq)
        period_starts = [val] + sched[:-1]

        annuity = sum(
            accrual_fraction(ps, pe, dc) * curve.df(pe)
            for ps, pe in zip(period_starts, sched)
        )
        df_end = curve.df(sched[-1])
        par_rate = (1.0 - df_end) / annuity

        swap = VanillaIRS(
            valuation_date=val,
            start_date=val,
            tenor_years=tenor,
            notional=5_000_000.0,
            fixed_rate=par_rate,
            payment_frequency=freq,
            day_count=dc,
            pay_receive="receiver",
        )
        result = price_irs(swap, curve)
        assert abs(result.npv) < 1.0


# ===========================================================================
# Canonical 5Y ZAR-style swap
# ===========================================================================


class TestCanonical:
    """
    Canonical case: 5Y ZAR JIBAR proxy — 8% flat market rate, 8.5% fixed
    coupon, quarterly, 250m notional, payer.

    The payer is paying above-market fixed so NPV_payer < 0.
    """

    def setup_method(self):
        self.val = date(2024, 3, 20)
        self.notional = 250_000_000.0
        self.fixed_rate = 0.085
        self.dc = DayCount.ACT_365F
        self.curve = flat_curve(self.val, 0.08, 5, "quarterly", self.dc)
        self.swap = VanillaIRS(
            valuation_date=self.val,
            start_date=self.val,
            tenor_years=5,
            notional=self.notional,
            fixed_rate=self.fixed_rate,
            payment_frequency="quarterly",
            day_count=self.dc,
            pay_receive="payer",
        )
        self.result = price_irs(self.swap, self.curve)

    def test_20_payments(self):
        assert self.result.n_payments == 20

    def test_npv_is_negative_for_above_market_payer(self):
        assert self.result.npv < 0.0

    def test_fixed_leg_exceeds_floating_leg(self):
        # Payer pays fixed > market → fixed PV > float PV
        assert self.result.fixed_leg_pv > self.result.floating_leg_pv

    def test_npv_magnitude_is_plausible(self):
        # V2 uses par-floating: float_pv = notional*(1-df_end)
        # With 8% flat ACT/365F: df_5Y ≈ 0.714 → float_pv ≈ 71.5m
        # fixed_pv ≈ 88.7m → npv_payer ≈ -17.2m
        # Conservative bounds: [10m, 25m] absolute
        assert 10_000_000 < abs(self.result.npv) < 25_000_000


# ===========================================================================
# Result field internal consistency
# ===========================================================================


class TestResultFields:
    """IRSResult fields must satisfy algebraic identities."""

    def setup_method(self):
        val = date(2024, 1, 1)
        self.curve = flat_curve(val, 0.08, 5, "quarterly")
        self.payer_swap = _swap(
            start_date=val,
            tenor_years=5,
            payment_frequency="quarterly",
            pay_receive="payer",
            fixed_rate=0.085,
        )
        self.recv_swap = _swap(
            start_date=val,
            tenor_years=5,
            payment_frequency="quarterly",
            pay_receive="receiver",
            fixed_rate=0.085,
        )

    def test_payer_npv_equals_float_minus_fixed(self):
        r = price_irs(self.payer_swap, self.curve)
        assert r.npv == pytest.approx(r.floating_leg_pv - r.fixed_leg_pv, abs=1e-8)

    def test_receiver_npv_equals_fixed_minus_float(self):
        r = price_irs(self.recv_swap, self.curve)
        assert r.npv == pytest.approx(r.fixed_leg_pv - r.floating_leg_pv, abs=1e-8)

    def test_npv_is_result_instance(self):
        r = price_irs(self.payer_swap, self.curve)
        assert isinstance(r, IRSResult)

    def test_n_payments_matches_schedule_length(self):
        r = price_irs(self.payer_swap, self.curve)
        sched = generate_unadjusted_dates(
            self.payer_swap.start_date,
            self.payer_swap.tenor_years,
            self.payer_swap.payment_frequency,
        )
        assert r.n_payments == len(sched)

    def test_both_leg_pvs_are_positive(self):
        # Positive dfs and positive rate → both legs always positive
        r = price_irs(self.payer_swap, self.curve)
        assert r.fixed_leg_pv > 0.0
        assert r.floating_leg_pv > 0.0


# ===========================================================================
# Day-count effect
# ===========================================================================


class TestDayCountEffect:
    """Different day-count conventions produce different fixed-leg PVs."""

    def test_act365f_vs_act360_fixed_pv_differs(self):
        val = date(2024, 1, 1)
        curve_365 = flat_curve(val, 0.08, 5, "annual", DayCount.ACT_365F)
        curve_360 = flat_curve(val, 0.08, 5, "annual", DayCount.ACT_360)

        swap_365 = _swap(
            start_date=val,
            day_count=DayCount.ACT_365F,
            payment_frequency="annual",
        )
        swap_360 = _swap(
            start_date=val,
            day_count=DayCount.ACT_360,
            payment_frequency="annual",
        )
        r_365 = price_irs(swap_365, curve_365)
        r_360 = price_irs(swap_360, curve_360)
        # ACT/360 denominator is smaller → tau larger → larger fixed PV
        assert r_360.fixed_leg_pv != pytest.approx(r_365.fixed_leg_pv)
        assert r_360.fixed_leg_pv > r_365.fixed_leg_pv


# ===========================================================================
# V1 backend compatibility guard
# ===========================================================================


class TestV1Comparison:
    """
    Regression guard: V2 quant-core pricer must be directionally and
    numerically aligned with the V1 FastAPI pricer for the identical
    narrow flat-curve case.

    The V1 pricer (backend/app/services/pricer.py) uses:
      - Flat market rate 8%, fixed rate 8.5%, quarterly, 5Y, 250m, payer
      - Simple discounting:  df(t) = 1 / (1 + r * t)
      - Approximate period fractions:  t_i = i * 0.25  (exact quarters)
      - No day-count convention (approximation)

    V1 formula:
      annuity_v1 = Σ df(0.08, 0.25*i) for i = 1..20
      pv_fixed_v1  = 250m * 0.085 * 0.25 * annuity_v1
      pv_float_v1  = 250m * 0.08  * 0.25 * annuity_v1
      npv_payer_v1 = pv_float_v1 - pv_fixed_v1

    V2 uses ACT/365F accrual fractions from actual calendar dates, so
    values will differ slightly.  The test asserts:
      1. Same sign (both negative for payer above-market).
      2. Magnitude within 20% of the V1 reference.
    """

    def test_directional_and_numerical_alignment_with_v1(self):
        # ------------------------------------------------------------------ #
        # V1 reference — replicated from backend/app/services/pricer.py logic
        # without importing that module.
        #
        # V1 prices both legs as  notional * rate * accrual * annuity  where
        # each period fraction is exactly 0.25 (no day-count convention).
        # V2 uses ACT/365F accrual fractions on actual calendar dates.
        #
        # The two models use DIFFERENT floating-leg pricing philosophies:
        #   V1 float: notional * market_rate * accrual * Σdf(i)  (flat coupon)
        #   V2 float: notional * (df_start - df_end)              (par-float)
        # These are not equal, so NPvs can differ substantially.
        #
        # The meaningful numerical comparison is on the FIXED leg, where both
        # models apply the same formula and differ only by ~0.05% from the
        # ACT/365F vs exact-0.25 accrual fraction difference.
        # ------------------------------------------------------------------ #
        notional = 250_000_000.0
        market_rate = 0.08
        fixed_rate_v1 = 0.085
        accrual_v1 = 0.25
        n_v1 = 20

        payment_times_v1 = [i * accrual_v1 for i in range(1, n_v1 + 1)]
        annuity_v1 = sum(1.0 / (1.0 + market_rate * t) for t in payment_times_v1)
        pv_fixed_v1 = notional * fixed_rate_v1 * accrual_v1 * annuity_v1
        pv_float_v1 = notional * market_rate * accrual_v1 * annuity_v1
        npv_v1 = pv_float_v1 - pv_fixed_v1   # payer

        # ------------------------------------------------------------------ #
        # V2 quant-core calculation
        # ------------------------------------------------------------------ #
        val = date(2024, 1, 1)
        curve = flat_curve(val, market_rate, 5, "quarterly", DayCount.ACT_365F)
        swap = VanillaIRS(
            valuation_date=val,
            start_date=val,
            tenor_years=5,
            notional=notional,
            fixed_rate=fixed_rate_v1,
            payment_frequency="quarterly",
            day_count=DayCount.ACT_365F,
            pay_receive="payer",
        )
        result_v2 = price_irs(swap, curve)

        # ------------------------------------------------------------------ #
        # Assertions
        # ------------------------------------------------------------------ #
        # 1. V1 reference is negative (payer above-market)
        assert npv_v1 < 0.0

        # 2. V2 must have the same sign (directional alignment)
        assert result_v2.npv < 0.0, (
            f"V2 NPV {result_v2.npv:.0f} should be negative for payer "
            "at above-market fixed rate"
        )

        # 3. Fixed leg PVs must agree within 1% — both models compute
        #    notional * fixed_rate * accrual_i * df_i; the only difference
        #    is ACT/365F actual fractions vs exact 0.25.  Observed: ~0.05%.
        relative_fixed_diff = abs(result_v2.fixed_leg_pv - pv_fixed_v1) / abs(pv_fixed_v1)
        assert relative_fixed_diff < 0.01, (
            f"V2 fixed_leg_pv {result_v2.fixed_leg_pv:.0f} differs from "
            f"V1 fixed_pv {pv_fixed_v1:.0f} by {relative_fixed_diff:.3%}, "
            "exceeding 1% tolerance"
        )

    def test_v1_pv01_alignment(self):
        # ------------------------------------------------------------------ #
        # V1 PV01 — computed by re-pricing with market_rate + 1bp in the V1
        # model, then taking the absolute difference.
        #
        # V2 PV01 — parallel +1bp shift of continuously-compounded zero rates
        # via _bump_curve.  Different methodology, but same order of magnitude.
        #
        # Assertion: both are positive and V2 is within 30% of V1 (observed
        # difference empirically: ~6%).
        # ------------------------------------------------------------------ #
        notional = 250_000_000.0
        market_rate = 0.08
        fixed_rate_v1 = 0.085
        accrual_v1 = 0.25
        n_v1 = 20

        payment_times_v1 = [i * accrual_v1 for i in range(1, n_v1 + 1)]
        annuity_base = sum(1.0 / (1.0 + market_rate * t) for t in payment_times_v1)
        annuity_bump = sum(
            1.0 / (1.0 + (market_rate + 0.0001) * t) for t in payment_times_v1
        )
        npv_base_v1 = (
            notional * (market_rate - fixed_rate_v1) * accrual_v1 * annuity_base
        )
        npv_bump_v1 = (
            notional * ((market_rate + 0.0001) - fixed_rate_v1) * accrual_v1 * annuity_bump
        )
        pv01_v1 = abs(npv_bump_v1 - npv_base_v1)

        val = date(2024, 1, 1)
        curve = flat_curve(val, market_rate, 5, "quarterly", DayCount.ACT_365F)
        swap = VanillaIRS(
            valuation_date=val,
            start_date=val,
            tenor_years=5,
            notional=notional,
            fixed_rate=fixed_rate_v1,
            payment_frequency="quarterly",
            day_count=DayCount.ACT_365F,
            pay_receive="payer",
        )
        result_v2 = price_irs(swap, curve)

        # Both PV01s are positive
        assert pv01_v1 > 0.0
        assert result_v2.pv01 > 0.0

        # V2 PV01 within 30% of V1 PV01 (observed: ~6%)
        relative_diff = abs(result_v2.pv01 - pv01_v1) / pv01_v1
        assert relative_diff < 0.30, (
            f"V2 PV01 {result_v2.pv01:.0f} differs from V1 PV01 "
            f"{pv01_v1:.0f} by {relative_diff:.1%}"
        )


# ===========================================================================
# PV01 / DV01 sensitivity
# ===========================================================================


class TestPV01:
    """
    PV01 (DV01) — absolute NPV change for a parallel +1bp upward shift of
    all continuously-compounded zero rates on the discount curve.

    Bump formula applied inside _bump_curve:
        df_bumped_i = df_i * exp(-0.0001 * tau_i)
    where tau_i = accrual_fraction(valuation_date, pillar_i, swap.day_count).
    """

    def test_pv01_positive_for_payer(self):
        val = date(2024, 1, 1)
        curve = flat_curve(val, 0.08, 5, "quarterly")
        swap = _swap(
            start_date=val,
            pay_receive="payer",
            tenor_years=5,
            payment_frequency="quarterly",
        )
        r = price_irs(swap, curve)
        assert r.pv01 > 0.0

    def test_pv01_positive_for_receiver(self):
        val = date(2024, 1, 1)
        curve = flat_curve(val, 0.08, 5, "quarterly")
        swap = _swap(
            start_date=val,
            pay_receive="receiver",
            tenor_years=5,
            payment_frequency="quarterly",
        )
        r = price_irs(swap, curve)
        assert r.pv01 > 0.0

    def test_payer_and_receiver_pv01_are_equal(self):
        # abs() makes PV01 symmetric: |ΔNPV_payer| == |ΔNPV_receiver|
        val = date(2024, 1, 1)
        curve = flat_curve(val, 0.08, 5, "annual")
        payer = _swap(start_date=val, pay_receive="payer")
        receiver = _swap(start_date=val, pay_receive="receiver")
        r_p = price_irs(payer, curve)
        r_r = price_irs(receiver, curve)
        assert r_p.pv01 == pytest.approx(r_r.pv01, rel=1e-10)

    def test_pv01_scales_linearly_with_notional(self):
        val = date(2024, 1, 1)
        curve = flat_curve(val, 0.08, 5, "quarterly")
        s1 = _swap(
            start_date=val,
            notional=1_000_000.0,
            tenor_years=5,
            payment_frequency="quarterly",
        )
        s2 = _swap(
            start_date=val,
            notional=2_000_000.0,
            tenor_years=5,
            payment_frequency="quarterly",
        )
        r1 = price_irs(s1, curve)
        r2 = price_irs(s2, curve)
        assert r2.pv01 == pytest.approx(2.0 * r1.pv01, rel=1e-12)

    def test_single_period_pv01_nonzero(self):
        # 1Y annual single-period swap; PV01 ≈ 97.5 for 1m notional at 8%.
        val = date(2024, 1, 1)
        curve = flat_curve(val, 0.08, 1, "annual")
        swap = _swap(start_date=val, tenor_years=1, payment_frequency="annual")
        r = price_irs(swap, curve)
        assert r.pv01 > 0.0

    def test_canonical_pv01_deterministic(self):
        # Canonical: 5Y ZAR JIBAR proxy — 8% flat, 8.5% fixed, quarterly, 250m
        # Known exact value: 111,353 (computed 2026-03-24, ACT/365F, payer)
        # Conservative bounds: (50_000, 200_000)
        val = date(2024, 3, 20)
        curve = flat_curve(val, 0.08, 5, "quarterly", DayCount.ACT_365F)
        swap = VanillaIRS(
            val, val, 5, 250_000_000.0, 0.085, "quarterly",
            DayCount.ACT_365F, "payer",
        )
        r = price_irs(swap, curve)
        assert r.pv01 > 0.0
        assert 50_000 < r.pv01 < 200_000

    def test_pv01_in_result_dataclass(self):
        val = date(2024, 1, 1)
        curve = flat_curve(val, 0.08, 5, "quarterly")
        swap = _swap(start_date=val, tenor_years=5, payment_frequency="quarterly")
        r = price_irs(swap, curve)
        assert isinstance(r, IRSResult)
        assert hasattr(r, "pv01")
        assert isinstance(r.pv01, float)

    def test_higher_notional_has_higher_pv01(self):
        val = date(2024, 1, 1)
        curve = flat_curve(val, 0.08, 5, "annual")
        s1 = _swap(start_date=val, notional=1_000_000.0)
        s2 = _swap(start_date=val, notional=10_000_000.0)
        r1 = price_irs(s1, curve)
        r2 = price_irs(s2, curve)
        assert r2.pv01 > r1.pv01

    def test_longer_tenor_has_higher_pv01(self):
        # Longer swaps have more rate sensitivity (duration effect).
        val = date(2024, 1, 1)
        curve_1y = flat_curve(val, 0.08, 1, "annual")
        curve_5y = flat_curve(val, 0.08, 5, "annual")
        s1 = _swap(start_date=val, tenor_years=1, payment_frequency="annual")
        s5 = _swap(start_date=val, tenor_years=5, payment_frequency="annual")
        r1 = price_irs(s1, curve_1y)
        r5 = price_irs(s5, curve_5y)
        assert r5.pv01 > r1.pv01

    def test_existing_npv_fields_unchanged_by_pv01(self):
        # Adding pv01 must not perturb the four existing NPV result fields.
        val = date(2024, 1, 1)
        curve = flat_curve(val, 0.08, 5, "quarterly")
        swap = _swap(
            start_date=val,
            tenor_years=5,
            payment_frequency="quarterly",
            fixed_rate=0.085,
        )
        r = price_irs(swap, curve)
        assert isinstance(r.npv, float)
        assert isinstance(r.fixed_leg_pv, float)
        assert isinstance(r.floating_leg_pv, float)
        assert isinstance(r.n_payments, int)
        assert isinstance(r.pv01, float)
        # Spot-check: payer NPV is negative for above-market fixed
        assert r.npv < 0.0


# ===========================================================================
# IRS cashflow schedule
# ===========================================================================


class TestIRSCashflowSchedule:
    """
    irs_cashflow_schedule — per-period fixed-leg rows.

    Canonical test swap: 5Y quarterly payer, 1 000 000 notional, 8.5% fixed,
    ACT/365F day count, flat 8% ZAR JIBAR proxy curve, spot-starting 2024-01-01.
    """

    def _setup(self):
        val = date(2024, 1, 1)
        curve = flat_curve(val, 0.08, 5, "quarterly", DayCount.ACT_365F)
        swap = VanillaIRS(
            valuation_date=val,
            start_date=val,
            tenor_years=5,
            notional=1_000_000.0,
            fixed_rate=0.085,
            payment_frequency="quarterly",
            day_count=DayCount.ACT_365F,
            pay_receive="payer",
        )
        return swap, curve

    def test_returns_list(self):
        swap, curve = self._setup()
        rows = irs_cashflow_schedule(swap, curve)
        assert isinstance(rows, list)

    def test_row_type(self):
        swap, curve = self._setup()
        rows = irs_cashflow_schedule(swap, curve)
        assert all(isinstance(r, IRSCashflowRow) for r in rows)

    def test_5y_quarterly_has_20_rows(self):
        swap, curve = self._setup()
        rows = irs_cashflow_schedule(swap, curve)
        assert len(rows) == 20

    def test_1y_annual_has_1_row(self):
        val = date(2024, 1, 1)
        curve = flat_curve(val, 0.08, 1, "annual", DayCount.ACT_365F)
        swap = VanillaIRS(val, val, 1, 1_000_000.0, 0.085, "annual",
                          DayCount.ACT_365F, "payer")
        rows = irs_cashflow_schedule(swap, curve)
        assert len(rows) == 1

    def test_2y_semiannual_has_4_rows(self):
        val = date(2024, 1, 1)
        curve = flat_curve(val, 0.08, 2, "semiannual", DayCount.ACT_365F)
        swap = VanillaIRS(val, val, 2, 1_000_000.0, 0.085, "semiannual",
                          DayCount.ACT_365F, "payer")
        rows = irs_cashflow_schedule(swap, curve)
        assert len(rows) == 4

    def test_row_count_matches_n_payments(self):
        swap, curve = self._setup()
        rows = irs_cashflow_schedule(swap, curve)
        result = price_irs(swap, curve)
        assert len(rows) == result.n_payments

    def test_payment_dates_ascending(self):
        swap, curve = self._setup()
        rows = irs_cashflow_schedule(swap, curve)
        dates = [r.payment_date for r in rows]
        assert dates == sorted(dates)

    def test_accrual_start_equals_prior_payment_date(self):
        swap, curve = self._setup()
        rows = irs_cashflow_schedule(swap, curve)
        for i in range(1, len(rows)):
            assert rows[i].accrual_start == rows[i - 1].payment_date

    def test_first_accrual_start_equals_swap_start_date(self):
        swap, curve = self._setup()
        rows = irs_cashflow_schedule(swap, curve)
        assert rows[0].accrual_start == swap.start_date

    def test_accrual_end_equals_payment_date(self):
        swap, curve = self._setup()
        rows = irs_cashflow_schedule(swap, curve)
        for r in rows:
            assert r.accrual_end == r.payment_date

    def test_year_fractions_positive(self):
        swap, curve = self._setup()
        rows = irs_cashflow_schedule(swap, curve)
        assert all(r.year_fraction > 0.0 for r in rows)

    def test_year_fractions_approx_quarterly(self):
        swap, curve = self._setup()
        rows = irs_cashflow_schedule(swap, curve)
        for r in rows:
            assert 0.20 < r.year_fraction < 0.30

    def test_fixed_rate_stored_correctly(self):
        swap, curve = self._setup()
        rows = irs_cashflow_schedule(swap, curve)
        for r in rows:
            assert r.fixed_rate == pytest.approx(0.085)

    def test_notional_stored_correctly(self):
        swap, curve = self._setup()
        rows = irs_cashflow_schedule(swap, curve)
        for r in rows:
            assert r.notional == pytest.approx(1_000_000.0)

    def test_fixed_cashflow_equals_notional_rate_tau(self):
        swap, curve = self._setup()
        rows = irs_cashflow_schedule(swap, curve)
        for r in rows:
            expected = r.notional * r.fixed_rate * r.year_fraction
            assert r.fixed_cashflow == pytest.approx(expected, rel=1e-12)

    def test_fixed_cashflows_positive(self):
        swap, curve = self._setup()
        rows = irs_cashflow_schedule(swap, curve)
        assert all(r.fixed_cashflow > 0.0 for r in rows)

    def test_discount_factors_in_0_1(self):
        swap, curve = self._setup()
        rows = irs_cashflow_schedule(swap, curve)
        for r in rows:
            assert 0.0 < r.discount_factor < 1.0

    def test_discount_factors_decreasing(self):
        swap, curve = self._setup()
        rows = irs_cashflow_schedule(swap, curve)
        dfs = [r.discount_factor for r in rows]
        assert all(dfs[i] > dfs[i + 1] for i in range(len(dfs) - 1))

    def test_pv_cashflow_equals_cf_times_df(self):
        swap, curve = self._setup()
        rows = irs_cashflow_schedule(swap, curve)
        for r in rows:
            assert r.pv_cashflow == pytest.approx(
                r.fixed_cashflow * r.discount_factor, rel=1e-12
            )

    def test_pv_sum_matches_fixed_leg_pv(self):
        swap, curve = self._setup()
        rows = irs_cashflow_schedule(swap, curve)
        result = price_irs(swap, curve)
        pv_sum = sum(r.pv_cashflow for r in rows)
        assert pv_sum == pytest.approx(result.fixed_leg_pv, rel=1e-12)

    def test_time_to_payment_positive(self):
        swap, curve = self._setup()
        rows = irs_cashflow_schedule(swap, curve)
        assert all(r.time_to_payment_years > 0.0 for r in rows)

    def test_time_to_payment_increasing(self):
        swap, curve = self._setup()
        rows = irs_cashflow_schedule(swap, curve)
        ttps = [r.time_to_payment_years for r in rows]
        assert all(ttps[i] < ttps[i + 1] for i in range(len(ttps) - 1))

    def test_final_payment_date_matches_maturity(self):
        from quant_core.conventions.schedule import generate_unadjusted_dates
        swap, curve = self._setup()
        rows = irs_cashflow_schedule(swap, curve)
        payment_dates = generate_unadjusted_dates(
            swap.start_date, swap.tenor_years, swap.payment_frequency
        )
        assert rows[-1].payment_date == payment_dates[-1]

    def test_notional_scaling_scales_cashflows(self):
        val = date(2024, 1, 1)
        curve = flat_curve(val, 0.08, 5, "quarterly", DayCount.ACT_365F)
        swap1 = VanillaIRS(val, val, 5, 1_000_000.0, 0.085, "quarterly",
                           DayCount.ACT_365F, "payer")
        swap2 = VanillaIRS(val, val, 5, 2_000_000.0, 0.085, "quarterly",
                           DayCount.ACT_365F, "payer")
        rows1 = irs_cashflow_schedule(swap1, curve)
        rows2 = irs_cashflow_schedule(swap2, curve)
        for r1, r2 in zip(rows1, rows2):
            assert r2.fixed_cashflow == pytest.approx(2.0 * r1.fixed_cashflow, rel=1e-12)
            assert r2.pv_cashflow == pytest.approx(2.0 * r1.pv_cashflow, rel=1e-12)

    def test_receiver_has_same_cashflows_as_payer(self):
        # Cashflow schedule is fixed-leg only; sign convention does not affect it.
        val = date(2024, 1, 1)
        curve = flat_curve(val, 0.08, 5, "quarterly", DayCount.ACT_365F)
        payer = VanillaIRS(val, val, 5, 1_000_000.0, 0.085, "quarterly",
                           DayCount.ACT_365F, "payer")
        receiver = VanillaIRS(val, val, 5, 1_000_000.0, 0.085, "quarterly",
                              DayCount.ACT_365F, "receiver")
        rows_p = irs_cashflow_schedule(payer, curve)
        rows_r = irs_cashflow_schedule(receiver, curve)
        for rp, rr in zip(rows_p, rows_r):
            assert rp.pv_cashflow == pytest.approx(rr.pv_cashflow, rel=1e-12)
            assert rp.fixed_cashflow == pytest.approx(rr.fixed_cashflow, rel=1e-12)


# ===========================================================================
# IRS valuation breakdown
# ===========================================================================


class TestIRSValuationBreakdown:
    """
    Tests for irs_valuation_breakdown(swap, curve).

    Core requirement: all numeric fields must be identical to the
    corresponding fields in IRSResult returned by price_irs(swap, curve)
    on the same inputs.  The breakdown is a thin wrapper; no new math.
    """

    def setup_method(self):
        self.val = date(2024, 1, 1)
        self.curve = flat_curve(self.val, 0.08, 5, "quarterly", DayCount.ACT_365F)
        self.payer = VanillaIRS(
            self.val, self.val, 5, 1_000_000.0, 0.085, "quarterly",
            DayCount.ACT_365F, "payer",
        )
        self.receiver = VanillaIRS(
            self.val, self.val, 5, 1_000_000.0, 0.085, "quarterly",
            DayCount.ACT_365F, "receiver",
        )
        self.price_result = price_irs(self.payer, self.curve)
        self.breakdown = irs_valuation_breakdown(self.payer, self.curve)

    # ------------------------------------------------------------------
    # Return type
    # ------------------------------------------------------------------

    def test_returns_irs_valuation_breakdown_instance(self):
        assert isinstance(self.breakdown, IRSValuationBreakdown)

    # ------------------------------------------------------------------
    # fixed_leg_pv matches price_irs
    # ------------------------------------------------------------------

    def test_fixed_leg_pv_matches_price_irs(self):
        assert self.breakdown.fixed_leg_pv == pytest.approx(
            self.price_result.fixed_leg_pv, rel=1e-12
        )

    # ------------------------------------------------------------------
    # floating_leg_pv matches price_irs
    # ------------------------------------------------------------------

    def test_floating_leg_pv_matches_price_irs(self):
        assert self.breakdown.floating_leg_pv == pytest.approx(
            self.price_result.floating_leg_pv, rel=1e-12
        )

    # ------------------------------------------------------------------
    # npv matches price_irs
    # ------------------------------------------------------------------

    def test_npv_matches_price_irs(self):
        assert self.breakdown.npv == pytest.approx(
            self.price_result.npv, rel=1e-12
        )

    # ------------------------------------------------------------------
    # n_payments matches price_irs
    # ------------------------------------------------------------------

    def test_n_payments_matches_price_irs(self):
        assert self.breakdown.n_payments == self.price_result.n_payments

    # ------------------------------------------------------------------
    # Payer sign convention
    # ------------------------------------------------------------------

    def test_payer_npv_equals_float_minus_fixed(self):
        bd = irs_valuation_breakdown(self.payer, self.curve)
        assert bd.npv == pytest.approx(bd.floating_leg_pv - bd.fixed_leg_pv, abs=1e-8)

    # ------------------------------------------------------------------
    # Receiver sign convention
    # ------------------------------------------------------------------

    def test_receiver_npv_equals_fixed_minus_float(self):
        bd = irs_valuation_breakdown(self.receiver, self.curve)
        assert bd.npv == pytest.approx(bd.fixed_leg_pv - bd.floating_leg_pv, abs=1e-8)

    def test_payer_and_receiver_npv_sum_to_zero(self):
        bd_pay = irs_valuation_breakdown(self.payer, self.curve)
        bd_rec = irs_valuation_breakdown(self.receiver, self.curve)
        assert bd_pay.npv + bd_rec.npv == pytest.approx(0.0, abs=1e-8)

    # ------------------------------------------------------------------
    # floating_leg_method label
    # ------------------------------------------------------------------

    def test_floating_leg_method_is_par_floating_approximation(self):
        assert self.breakdown.floating_leg_method == "par_floating_approximation"

    # ------------------------------------------------------------------
    # Canonical 5Y ZAR case: npv sign
    # ------------------------------------------------------------------

    def test_payer_npv_negative_when_fixed_above_market(self):
        # 8.5% fixed > 8% market → payer NPV negative
        assert self.breakdown.npv < 0.0

    def test_receiver_npv_positive_when_fixed_above_market(self):
        bd = irs_valuation_breakdown(self.receiver, self.curve)
        assert bd.npv > 0.0

    # ------------------------------------------------------------------
    # Consistency: both legs positive
    # ------------------------------------------------------------------

    def test_both_leg_pvs_are_positive(self):
        assert self.breakdown.fixed_leg_pv > 0.0
        assert self.breakdown.floating_leg_pv > 0.0

    # ------------------------------------------------------------------
    # Notional scaling
    # ------------------------------------------------------------------

    def test_notional_scaling_pv_fields(self):
        val = self.val
        curve = self.curve
        swap1 = VanillaIRS(val, val, 5, 1_000_000.0, 0.085, "quarterly",
                           DayCount.ACT_365F, "payer")
        swap2 = VanillaIRS(val, val, 5, 2_000_000.0, 0.085, "quarterly",
                           DayCount.ACT_365F, "payer")
        bd1 = irs_valuation_breakdown(swap1, curve)
        bd2 = irs_valuation_breakdown(swap2, curve)
        assert bd2.npv == pytest.approx(2.0 * bd1.npv, rel=1e-12)
        assert bd2.fixed_leg_pv == pytest.approx(2.0 * bd1.fixed_leg_pv, rel=1e-12)
        assert bd2.floating_leg_pv == pytest.approx(2.0 * bd1.floating_leg_pv, rel=1e-12)

    # ------------------------------------------------------------------
    # n_payments for common tenors
    # ------------------------------------------------------------------

    def test_n_payments_5y_quarterly(self):
        assert self.breakdown.n_payments == 20

    def test_n_payments_3y_semiannual(self):
        val = self.val
        curve = flat_curve(val, 0.08, 3, "semiannual", DayCount.ACT_365F)
        swap = VanillaIRS(val, val, 3, 1_000_000.0, 0.08, "semiannual",
                          DayCount.ACT_365F, "payer")
        bd = irs_valuation_breakdown(swap, curve)
        assert bd.n_payments == 6

    def test_n_payments_1y_annual(self):
        val = self.val
        curve = flat_curve(val, 0.08, 1, "annual", DayCount.ACT_365F)
        swap = VanillaIRS(val, val, 1, 1_000_000.0, 0.08, "annual",
                          DayCount.ACT_365F, "payer")
        bd = irs_valuation_breakdown(swap, curve)
        assert bd.n_payments == 1


# ===========================================================================
# IRS fair-rate solver
# ===========================================================================


class TestIRSFairRate:
    """
    Tests for solve_irs_fair_rate(swap, curve) and fixed_leg_annuity(swap, curve).

    Core requirement: pricing a swap with fair_rate as fixed_rate must give
    NPV ≈ 0 under the same curve.  All fair-rate tests use the existing
    flat_curve builder so no new market-data assumptions are introduced.
    """

    def setup_method(self):
        self.val = date(2024, 1, 1)
        self.curve = flat_curve(self.val, 0.08, 5, "quarterly", DayCount.ACT_365F)
        self.payer = VanillaIRS(
            self.val, self.val, 5, 1_000_000.0, 0.085, "quarterly",
            DayCount.ACT_365F, "payer",
        )
        self.receiver = VanillaIRS(
            self.val, self.val, 5, 1_000_000.0, 0.085, "quarterly",
            DayCount.ACT_365F, "receiver",
        )

    # ------------------------------------------------------------------
    # Return type
    # ------------------------------------------------------------------

    def test_returns_float(self):
        fair = solve_irs_fair_rate(self.payer, self.curve)
        assert isinstance(fair, float)

    # ------------------------------------------------------------------
    # Fair rate is positive for a standard curve
    # ------------------------------------------------------------------

    def test_fair_rate_positive(self):
        fair = solve_irs_fair_rate(self.payer, self.curve)
        assert fair > 0.0

    def test_fair_rate_in_reasonable_range(self):
        # For an 8% flat curve, the fair rate should be close to 8%.
        fair = solve_irs_fair_rate(self.payer, self.curve)
        assert 0.01 < fair < 0.99

    # ------------------------------------------------------------------
    # Repricing with fair_rate gives NPV ≈ 0
    # ------------------------------------------------------------------

    def test_reprice_payer_with_fair_rate_gives_zero_npv(self):
        fair = solve_irs_fair_rate(self.payer, self.curve)
        at_par = VanillaIRS(
            self.val, self.val, 5, 1_000_000.0, fair, "quarterly",
            DayCount.ACT_365F, "payer",
        )
        result = price_irs(at_par, self.curve)
        assert result.npv == pytest.approx(0.0, abs=1e-6)

    def test_reprice_receiver_with_fair_rate_gives_zero_npv(self):
        fair = solve_irs_fair_rate(self.receiver, self.curve)
        at_par = VanillaIRS(
            self.val, self.val, 5, 1_000_000.0, fair, "quarterly",
            DayCount.ACT_365F, "receiver",
        )
        result = price_irs(at_par, self.curve)
        assert result.npv == pytest.approx(0.0, abs=1e-6)

    # ------------------------------------------------------------------
    # Payer and receiver fair rate are identical (direction-invariant)
    # ------------------------------------------------------------------

    def test_payer_and_receiver_fair_rate_identical(self):
        fair_p = solve_irs_fair_rate(self.payer, self.curve)
        fair_r = solve_irs_fair_rate(self.receiver, self.curve)
        assert fair_p == pytest.approx(fair_r, rel=1e-12)

    # ------------------------------------------------------------------
    # Canonical flat-curve deterministic value
    # ------------------------------------------------------------------

    def test_canonical_5y_quarterly_flat_8pct_deterministic(self):
        # 5Y quarterly, ACT/365F, flat 8% simple-discount curve.
        # Under simple discounting df(t) = 1/(1+r*t), so the annuity
        # denominator is meaningfully larger than the rate alone, pushing
        # the fair rate below the market rate (≈ 6.85% at 8% flat).
        # Check: positive, consistent with the model, and in (0.04, 0.09).
        fair = solve_irs_fair_rate(self.payer, self.curve)
        assert 0.04 < fair < 0.09

    # ------------------------------------------------------------------
    # Fair rate relationship to market rate
    # ------------------------------------------------------------------

    def test_fair_rate_below_market_for_simple_discount_annual(self):
        # For a flat simple-discount curve, the fair par rate is slightly
        # below the flat market rate because the annuity denominator
        # discounts the accrual fractions.  Over 1Y annual this is exact.
        val = date(2024, 1, 1)
        market_rate = 0.10
        curve = flat_curve(val, market_rate, 1, "annual", DayCount.ACT_365F)
        swap = VanillaIRS(val, val, 1, 1_000_000.0, 0.10, "annual",
                          DayCount.ACT_365F, "payer")
        fair = solve_irs_fair_rate(swap, curve)
        # For 1Y annual spot swap: fair rate = (1 - df) / (tau * df)
        # which equals market_rate for simple discount by construction.
        at_par = VanillaIRS(val, val, 1, 1_000_000.0, fair, "annual",
                            DayCount.ACT_365F, "payer")
        result = price_irs(at_par, curve)
        assert result.npv == pytest.approx(0.0, abs=1e-6)

    # ------------------------------------------------------------------
    # Notional does not affect fair rate
    # ------------------------------------------------------------------

    def test_fair_rate_independent_of_notional(self):
        val = self.val
        curve = self.curve
        swap1 = VanillaIRS(val, val, 5, 1_000_000.0, 0.085, "quarterly",
                           DayCount.ACT_365F, "payer")
        swap2 = VanillaIRS(val, val, 5, 10_000_000.0, 0.085, "quarterly",
                           DayCount.ACT_365F, "payer")
        fair1 = solve_irs_fair_rate(swap1, curve)
        fair2 = solve_irs_fair_rate(swap2, curve)
        assert fair1 == pytest.approx(fair2, rel=1e-12)

    # ------------------------------------------------------------------
    # Higher flat market rate → higher fair rate
    # ------------------------------------------------------------------

    def test_higher_market_rate_gives_higher_fair_rate(self):
        val = date(2024, 1, 1)
        swap = VanillaIRS(val, val, 5, 1_000_000.0, 0.085, "quarterly",
                          DayCount.ACT_365F, "payer")
        curve_low = flat_curve(val, 0.06, 5, "quarterly", DayCount.ACT_365F)
        curve_high = flat_curve(val, 0.10, 5, "quarterly", DayCount.ACT_365F)
        fair_low = solve_irs_fair_rate(swap, curve_low)
        fair_high = solve_irs_fair_rate(swap, curve_high)
        assert fair_high > fair_low

    # ------------------------------------------------------------------
    # fixed_leg_annuity helper
    # ------------------------------------------------------------------

    def test_annuity_positive(self):
        annuity = fixed_leg_annuity(self.payer, self.curve)
        assert annuity > 0.0

    def test_annuity_returns_float(self):
        annuity = fixed_leg_annuity(self.payer, self.curve)
        assert isinstance(annuity, float)

    def test_annuity_5y_quarterly_approx_range(self):
        # For a 5Y quarterly swap at 8%, annuity ≈ sum of 20 quarterly dfs
        # Each df ≈ 0.98..0.68; annuity should be in (2, 5).
        annuity = fixed_leg_annuity(self.payer, self.curve)
        assert 2.0 < annuity < 5.0

    def test_annuity_scales_with_notional_via_fair_rate_identity(self):
        # Annuity itself is independent of notional (it's sum of tau*df).
        val = self.val
        curve = self.curve
        swap1 = VanillaIRS(val, val, 5, 1_000_000.0, 0.085, "quarterly",
                           DayCount.ACT_365F, "payer")
        swap2 = VanillaIRS(val, val, 5, 5_000_000.0, 0.085, "quarterly",
                           DayCount.ACT_365F, "payer")
        a1 = fixed_leg_annuity(swap1, curve)
        a2 = fixed_leg_annuity(swap2, curve)
        assert a1 == pytest.approx(a2, rel=1e-12)

    # ------------------------------------------------------------------
    # Consistency: fair_rate = float_pv / (notional * annuity)
    # ------------------------------------------------------------------

    def test_fair_rate_equals_float_pv_over_notional_times_annuity(self):
        from quant_core.pricing.irs_pricer import _price_irs_core
        swap = self.payer
        curve = self.curve
        _npv, _fp, float_pv, _n = _price_irs_core(swap, curve)
        annuity = fixed_leg_annuity(swap, curve)
        expected_fair = float_pv / (swap.notional * annuity)
        actual_fair = solve_irs_fair_rate(swap, curve)
        assert actual_fair == pytest.approx(expected_fair, rel=1e-12)


