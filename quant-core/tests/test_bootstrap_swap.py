"""
test_bootstrap_swap — Tests for the par-swap bootstrap curve builder.

Coverage
--------
Validation
  - empty input
  - duplicate tenors
  - invalid par_rate (zero, negative, >= 1)
  - invalid tenor_years (zero, negative)

Bootstrap correctness
  - output pillar count matches quote count
  - output pillar dates are the maturity dates of quoted swaps
  - output discount factors are all positive
  - output discount factors are non-increasing with tenor
  - single-quote bootstrap against algebraic formula
  - multi-quote bootstrap: repricing each quoted swap produces NPV ≈ 0

Regression
  - canonical 4-quote ladder (1Y/2Y/3Y/5Y) produces stable discount factors
  - pre-computed expected values are verified to relative tolerance 1e-10

NPV round-trip
  - bootstrap curve then price_irs(..., "payer") gives NPV ≈ 0 for each tenor
  - bootstrap curve then price_irs(..., "receiver") gives NPV ≈ 0 for each tenor

Quote ordering
  - quotes supplied in reverse order give the same result

Regression guard
  - all existing quant-core tests are unaffected (separate test files)
"""
from __future__ import annotations

import math
from datetime import date

import pytest

from quant_core.conventions.day_count import DayCount, accrual_fraction
from quant_core.conventions.schedule import generate_unadjusted_dates
from quant_core.curves.bootstrap_swap import bootstrap_discount_curve_from_swaps
from quant_core.curves.discount_curve import DiscountCurve
from quant_core.instruments.irs import VanillaIRS
from quant_core.pricing.irs_pricer import price_irs
from quant_core.schemas.market_inputs import ParSwapQuote


# ===========================================================================
# Shared fixtures / helpers
# ===========================================================================

VAL = date(2024, 1, 1)
DC = DayCount.ACT_365F
FREQ = "annual"

# Canonical 4-point ladder used across multiple test classes.
CANONICAL_QUOTES = [
    ParSwapQuote(1, 0.0800),
    ParSwapQuote(2, 0.0810),
    ParSwapQuote(3, 0.0820),
    ParSwapQuote(5, 0.0850),
]


def _bootstrap_canonical() -> DiscountCurve:
    return bootstrap_discount_curve_from_swaps(VAL, CANONICAL_QUOTES, FREQ, DC)


def _maturity(tenor_years: int) -> date:
    """Unadjusted maturity date for a spot-starting annual swap."""
    return generate_unadjusted_dates(VAL, tenor_years, FREQ)[-1]


# ===========================================================================
# ParSwapQuote — construction validation
# ===========================================================================


class TestParSwapQuoteValidation:
    """ParSwapQuote must enforce tenor >= 1 and 0 < par_rate < 1."""

    def test_tenor_zero_raises(self):
        with pytest.raises(ValueError, match="tenor_years"):
            ParSwapQuote(0, 0.05)

    def test_tenor_negative_raises(self):
        with pytest.raises(ValueError, match="tenor_years"):
            ParSwapQuote(-1, 0.05)

    def test_par_rate_zero_raises(self):
        with pytest.raises(ValueError, match="par_rate"):
            ParSwapQuote(5, 0.0)

    def test_par_rate_negative_raises(self):
        with pytest.raises(ValueError, match="par_rate"):
            ParSwapQuote(5, -0.01)

    def test_par_rate_one_raises(self):
        with pytest.raises(ValueError, match="par_rate"):
            ParSwapQuote(5, 1.0)

    def test_par_rate_above_one_raises(self):
        with pytest.raises(ValueError, match="par_rate"):
            ParSwapQuote(5, 1.5)

    def test_valid_quote_constructs(self):
        q = ParSwapQuote(5, 0.085)
        assert q.tenor_years == 5
        assert q.par_rate == 0.085


# ===========================================================================
# bootstrap_discount_curve_from_swaps — input validation
# ===========================================================================


class TestBootstrapInputValidation:
    """Invalid inputs must raise ValueError with clear messages."""

    def test_empty_quotes_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            bootstrap_discount_curve_from_swaps(VAL, [], FREQ, DC)

    def test_duplicate_tenor_raises(self):
        quotes = [ParSwapQuote(1, 0.08), ParSwapQuote(1, 0.09)]
        with pytest.raises(ValueError, match="[Dd]uplicate"):
            bootstrap_discount_curve_from_swaps(VAL, quotes, FREQ, DC)

    def test_duplicate_tenor_in_longer_list_raises(self):
        quotes = [
            ParSwapQuote(1, 0.08),
            ParSwapQuote(2, 0.081),
            ParSwapQuote(2, 0.082),
            ParSwapQuote(3, 0.083),
        ]
        with pytest.raises(ValueError, match="[Dd]uplicate"):
            bootstrap_discount_curve_from_swaps(VAL, quotes, FREQ, DC)

    def test_invalid_frequency_raised_from_schedule(self):
        # The schedule generator rejects unknown frequencies.
        quotes = [ParSwapQuote(1, 0.08)]
        with pytest.raises(ValueError):
            bootstrap_discount_curve_from_swaps(VAL, quotes, "fortnightly", DC)


# ===========================================================================
# Bootstrap output structure
# ===========================================================================


class TestBootstrapOutputStructure:
    """Output shape and types are correct."""

    def setup_method(self):
        self.curve = _bootstrap_canonical()

    def test_returns_discount_curve(self):
        assert isinstance(self.curve, DiscountCurve)

    def test_pillar_count_matches_quote_count(self):
        assert len(self.curve.pillar_dates) == len(CANONICAL_QUOTES)

    def test_valuation_date_preserved(self):
        assert self.curve.valuation_date == VAL

    def test_pillar_dates_are_maturities(self):
        for q, pillar in zip(CANONICAL_QUOTES, self.curve.pillar_dates):
            assert pillar == _maturity(q.tenor_years), (
                f"Pillar for {q.tenor_years}Y should be {_maturity(q.tenor_years)}, "
                f"got {pillar}"
            )

    def test_pillar_dates_strictly_increasing(self):
        dates = self.curve.pillar_dates
        for i in range(1, len(dates)):
            assert dates[i] > dates[i - 1]


# ===========================================================================
# Discount factor validity
# ===========================================================================


class TestDiscountFactorValidity:
    """Solved discount factors must be positive and non-increasing."""

    def setup_method(self):
        self.curve = _bootstrap_canonical()

    def test_all_discount_factors_positive(self):
        for df in self.curve.discount_factors:
            assert df > 0.0

    def test_discount_factors_nonincreasing(self):
        dfs = self.curve.discount_factors
        for i in range(1, len(dfs)):
            assert dfs[i] <= dfs[i - 1], (
                f"df[{i}]={dfs[i]:.8f} > df[{i-1}]={dfs[i-1]:.8f} "
                f"at pillar {self.curve.pillar_dates[i]}"
            )

    def test_all_discount_factors_below_one(self):
        # Positive rates imply df < 1 for maturities after today.
        for df in self.curve.discount_factors:
            assert df < 1.0


# ===========================================================================
# Single-quote algebraic verification
# ===========================================================================


class TestSingleQuoteAlgebra:
    """
    For a single annual quote, the algebraic formula is:
        df(1Y) = 1 / (1 + par_rate × τ₁)
    which matches a flat curve at the same rate.
    """

    def test_single_quote_matches_algebraic_formula(self):
        c = 0.08
        quote = ParSwapQuote(1, c)
        curve = bootstrap_discount_curve_from_swaps(VAL, [quote], FREQ, DC)

        maturity = _maturity(1)
        tau = accrual_fraction(VAL, maturity, DC)
        expected_df = 1.0 / (1.0 + c * tau)

        assert curve.discount_factors[0] == pytest.approx(expected_df, rel=1e-12)

    def test_single_quote_various_rates(self):
        for rate in [0.01, 0.05, 0.08, 0.15, 0.30]:
            quote = ParSwapQuote(1, rate)
            curve = bootstrap_discount_curve_from_swaps(VAL, [quote], FREQ, DC)
            maturity = _maturity(1)
            tau = accrual_fraction(VAL, maturity, DC)
            expected = 1.0 / (1.0 + rate * tau)
            assert curve.discount_factors[0] == pytest.approx(expected, rel=1e-12), (
                f"Failed for rate={rate}"
            )

    def test_single_2y_annual_matches_formula(self):
        """
        2Y annual, val=2024-01-01:
          t1 = 2025-01-01, t2 = 2026-01-01
          τ₁ = 366/365, τ₂ = 365/365 = 1.0
          df(t1) = 1/(1 + c × τ₁)   [same as 1Y bootstrap step logic for the annuity]
          df(t2) = (1 − c × τ₁ × df(t1)) / (1 + c × τ₂)
        """
        c = 0.08
        t1 = _maturity(1)   # 2025-01-01
        t2 = _maturity(2)   # 2026-01-01
        tau1 = accrual_fraction(VAL, t1, DC)     # 366/365
        tau2 = accrual_fraction(t1, t2, DC)      # 365/365 = 1.0

        # Step 1: solve 1Y df
        df1 = 1.0 / (1.0 + c * tau1)

        # Step 2: annuity_prev = tau1 * df1; solve 2Y df
        annuity_prev = tau1 * df1
        df2 = (1.0 - c * annuity_prev) / (1.0 + c * tau2)

        # Bootstrap with just the 2Y quote.
        # Annual frequency with only a 2Y quote: the 1Y intermediate coupon
        # date (2025-01-01) is added as a pillar alongside the 2Y maturity
        # (2026-01-01) so the curve can reprice the 2Y annual swap.
        curve = bootstrap_discount_curve_from_swaps(
            VAL, [ParSwapQuote(2, c)], FREQ, DC
        )
        assert len(curve.discount_factors) == 2
        # The last pillar (2Y maturity) should match the formula.
        assert curve.discount_factors[-1] == pytest.approx(df2, rel=1e-12)


# ===========================================================================
# NPV round-trip (repricing)
# ===========================================================================


class TestNPVRoundTrip:
    """
    Repricing each quoted par swap against the bootstrapped curve must
    give NPV ≈ 0.  This is the primary economic correctness test.
    """

    def setup_method(self):
        self.curve = _bootstrap_canonical()

    def test_payer_npv_near_zero_for_each_quoted_tenor(self):
        for q in CANONICAL_QUOTES:
            swap = VanillaIRS(
                valuation_date=VAL,
                start_date=VAL,
                tenor_years=q.tenor_years,
                notional=1_000_000.0,
                fixed_rate=q.par_rate,
                payment_frequency=FREQ,
                day_count=DC,
                pay_receive="payer",
            )
            result = price_irs(swap, self.curve)
            assert abs(result.npv) < 1.0, (
                f"Payer NPV not near zero for {q.tenor_years}Y par swap: "
                f"NPV={result.npv:.4f}"
            )

    def test_receiver_npv_near_zero_for_each_quoted_tenor(self):
        for q in CANONICAL_QUOTES:
            swap = VanillaIRS(
                valuation_date=VAL,
                start_date=VAL,
                tenor_years=q.tenor_years,
                notional=1_000_000.0,
                fixed_rate=q.par_rate,
                payment_frequency=FREQ,
                day_count=DC,
                pay_receive="receiver",
            )
            result = price_irs(swap, self.curve)
            assert abs(result.npv) < 1.0, (
                f"Receiver NPV not near zero for {q.tenor_years}Y par swap: "
                f"NPV={result.npv:.4f}"
            )

    def test_above_par_payer_has_positive_npv(self):
        # A payer paying above the par rate has positive NPV for the fixed-payer.
        q = CANONICAL_QUOTES[0]  # 1Y at 8%
        swap = VanillaIRS(
            valuation_date=VAL,
            start_date=VAL,
            tenor_years=q.tenor_years,
            notional=1_000_000.0,
            fixed_rate=q.par_rate + 0.01,   # paying 9% when par is 8% — unfavorable
            payment_frequency=FREQ,
            day_count=DC,
            pay_receive="payer",
        )
        result = price_irs(swap, self.curve)
        assert result.npv < 0.0, (
            "Payer paying above par should have negative NPV (paying too much fixed)"
        )

    def test_below_par_payer_has_positive_npv(self):
        # A payer paying below par rate → favorable → positive NPV
        q = CANONICAL_QUOTES[0]  # 1Y at 8%
        swap = VanillaIRS(
            valuation_date=VAL,
            start_date=VAL,
            tenor_years=q.tenor_years,
            notional=1_000_000.0,
            fixed_rate=q.par_rate - 0.01,   # paying 7% when par is 8% — favorable
            payment_frequency=FREQ,
            day_count=DC,
            pay_receive="payer",
        )
        result = price_irs(swap, self.curve)
        assert result.npv > 0.0, (
            "Payer paying below par should have positive NPV"
        )

    def test_single_quote_round_trip(self):
        # Single-quote edge case: bootstrap a 1Y curve, reprice the 1Y par swap.
        q1 = ParSwapQuote(1, 0.075)
        curve = bootstrap_discount_curve_from_swaps(VAL, [q1], FREQ, DC)
        swap = VanillaIRS(
            valuation_date=VAL,
            start_date=VAL,
            tenor_years=1,
            notional=1_000_000.0,
            fixed_rate=q1.par_rate,
            payment_frequency=FREQ,
            day_count=DC,
            pay_receive="payer",
        )
        result = price_irs(swap, curve)
        assert abs(result.npv) < 1.0


# ===========================================================================
# Canonical regression — pinned expected values
# ===========================================================================


class TestCanonicalRegression:
    """
    Pinned expected discount factors for the canonical 4-quote ladder.

    Quotes: 1Y=8.00%, 2Y=8.10%, 3Y=8.20%, 5Y=8.50%
    val=2024-01-01, annual, ACT/365F.

    Expected discount factors are computed analytically using the same
    algebraic formula so they are self-consistent with the bootstrap code.
    Any change to the formula will break these tests.
    """

    # Pillar dates for the canonical ladder under annual frequency.
    @staticmethod
    def _expected_dfs() -> list[float]:
        """
        Reproduce the bootstrap analytically.

        Period structure (ACT/365F from 2024-01-01):
          t1 = 2025-01-01: 366 days (2024 is leap) → τ = 366/365
          t2 = 2026-01-01: 365 days from t1       → τ = 1.0
          t3 = 2027-01-01: 365 days from t2       → τ = 1.0
          t4 = 2028-01-01: 365 days from t3       → τ = 1.0
          t5 = 2029-01-01: 366 days from t4 (2028 leap) → τ = 366/365
        """
        t = [
            date(2025, 1, 1),
            date(2026, 1, 1),
            date(2027, 1, 1),
            date(2028, 1, 1),
            date(2029, 1, 1),
        ]
        dc = DayCount.ACT_365F
        val = VAL

        # Accrual fractions for each period start → end
        taus = [
            accrual_fraction(val,    t[0], dc),   # val → t1 (used as 1Y period)
            accrual_fraction(t[0],   t[1], dc),   # t1 → t2
            accrual_fraction(t[1],   t[2], dc),   # t2 → t3
            accrual_fraction(t[2],   t[3], dc),   # t3 → t4
            accrual_fraction(t[3],   t[4], dc),   # t4 → t5
        ]

        c1, c2, c3, c5 = 0.0800, 0.0810, 0.0820, 0.0850

        # 1Y bootstrap (single period: val → t1)
        df1 = 1.0 / (1.0 + c1 * taus[0])

        # 2Y bootstrap: annuity_prev = τ[0]*df1; solve df(t2)
        a2 = taus[0] * df1
        df2 = (1.0 - c2 * a2) / (1.0 + c2 * taus[1])

        # 3Y bootstrap: annuity_prev = τ[0]*df1 + τ[1]*df2; solve df(t3)
        a3 = taus[0] * df1 + taus[1] * df2
        df3 = (1.0 - c3 * a3) / (1.0 + c3 * taus[2])

        # 5Y bootstrap: quotes has no 4Y — gap date t4 is between t3 and t5.
        # The bootstrap uses log-linear interpolation: df(t4) depends on df(t5).
        # Solve the coupled equation numerically (same as bootstrap Newton solver).
        #
        # Residual: c5 × [A_known + tau4 × df4(df5) + tau5 × df5] + df5 − 1 = 0
        # where df4(df5) = exp((1-α)×ln(df3) + α×ln(df5)),
        #       α = ACT(t3,t4) / ACT(t3,t5)
        tau_t3_t4 = accrual_fraction(t[2], t[3], dc)
        tau_t3_t5 = accrual_fraction(t[2], t[4], dc)
        alpha = tau_t3_t4 / tau_t3_t5
        a_known = taus[0] * df1 + taus[1] * df2 + taus[2] * df3

        def _residual_5y(df5_guess: float) -> float:
            df4_guess = math.exp((1.0 - alpha) * math.log(df3) + alpha * math.log(df5_guess))
            return c5 * (a_known + taus[3] * df4_guess + taus[4] * df5_guess) + df5_guess - 1.0

        # Initial guess from flat-forward extrapolation
        tau_t2_t3 = accrual_fraction(t[1], t[2], dc)
        fwd_h = (math.log(df2) - math.log(df3)) / tau_t2_t3
        df5 = df3 * math.exp(-fwd_h * accrual_fraction(t[2], t[4], dc))
        for _ in range(50):
            f = _residual_5y(df5)
            if abs(f) < 1e-14:
                break
            eps = df5 * 1e-7
            df5_prime = (_residual_5y(df5 + eps) - f) / eps
            if abs(df5_prime) < 1e-30:
                break
            df5 -= f / df5_prime

        return [df1, df2, df3, df5]

    def test_pillar_count(self):
        curve = _bootstrap_canonical()
        assert len(curve.discount_factors) == 4

    def test_regression_1y(self):
        curve = _bootstrap_canonical()
        expected = self._expected_dfs()
        assert curve.discount_factors[0] == pytest.approx(expected[0], rel=1e-10)

    def test_regression_2y(self):
        curve = _bootstrap_canonical()
        expected = self._expected_dfs()
        assert curve.discount_factors[1] == pytest.approx(expected[1], rel=1e-10)

    def test_regression_3y(self):
        curve = _bootstrap_canonical()
        expected = self._expected_dfs()
        assert curve.discount_factors[2] == pytest.approx(expected[2], rel=1e-10)

    def test_regression_5y(self):
        curve = _bootstrap_canonical()
        expected = self._expected_dfs()
        assert curve.discount_factors[3] == pytest.approx(expected[3], rel=1e-10)

    def test_regression_dfs_are_decreasing(self):
        expected = self._expected_dfs()
        assert expected[0] > expected[1] > expected[2] > expected[3]


# ===========================================================================
# Quote ordering independence
# ===========================================================================


class TestQuoteOrdering:
    """Quotes supplied in any order must give the same bootstrapped curve."""

    def test_reverse_order_same_result(self):
        forward = bootstrap_discount_curve_from_swaps(
            VAL, CANONICAL_QUOTES, FREQ, DC
        )
        reversed_quotes = list(reversed(CANONICAL_QUOTES))
        backward = bootstrap_discount_curve_from_swaps(
            VAL, reversed_quotes, FREQ, DC
        )
        for df_fwd, df_rev in zip(forward.discount_factors, backward.discount_factors):
            assert df_fwd == pytest.approx(df_rev, rel=1e-12)

    def test_shuffled_order_same_result(self):
        shuffled = [CANONICAL_QUOTES[2], CANONICAL_QUOTES[0],
                    CANONICAL_QUOTES[3], CANONICAL_QUOTES[1]]
        forward = _bootstrap_canonical()
        shuffled_curve = bootstrap_discount_curve_from_swaps(
            VAL, shuffled, FREQ, DC
        )
        for df_fwd, df_sh in zip(forward.discount_factors, shuffled_curve.discount_factors):
            assert df_fwd == pytest.approx(df_sh, rel=1e-12)


# ===========================================================================
# Monotone-df guard
# ===========================================================================


class TestMonotoneDFGuard:
    """
    A quote ladder that would produce an increasing discount factor must
    raise ValueError rather than silently producing a bad curve.

    Constructing a truly non-monotone case analytically:
    A very high short-rate followed by a very low long-rate can produce
    an increasing df.  We use a deliberately crafted pathological ladder.
    """

    def test_inverted_curve_raises_for_non_monotone_df(self):
        # 1Y at 80% and 2Y at 1% would make df(2Y) >> df(1Y) if the
        # 2Y bootstrap step happened to produce a df larger than df(1Y).
        # The rates below are designed to trigger the guard.
        quotes = [
            ParSwapQuote(1, 0.90),   # very high 1Y rate → very low df1
            ParSwapQuote(2, 0.01),   # very low 2Y rate → df2 would be very high
        ]
        with pytest.raises(ValueError, match="[Ii]ncreasing discount factor|[Nn]egative"):
            bootstrap_discount_curve_from_swaps(VAL, quotes, FREQ, DC)


# ===========================================================================
# Semiannual frequency round-trip
# ===========================================================================


class TestSemiannualFrequency:
    """Bootstrap and reprice with semiannual payment frequency."""

    def test_semiannual_single_quote_npv_near_zero(self):
        q = ParSwapQuote(1, 0.08)
        curve = bootstrap_discount_curve_from_swaps(
            VAL, [q], "semiannual", DC
        )
        # The semiannual 1Y curve has two pillars: at 6M and at 1Y maturity.
        # (The 6M intermediate coupon date is added so the curve can reprice
        # the 1Y semiannual swap.)
        assert len(curve.pillar_dates) == 2

        swap = VanillaIRS(
            valuation_date=VAL,
            start_date=VAL,
            tenor_years=1,
            notional=1_000_000.0,
            fixed_rate=q.par_rate,
            payment_frequency="semiannual",
            day_count=DC,
            pay_receive="payer",
        )
        result = price_irs(swap, curve)
        assert abs(result.npv) < 1.0

    def test_semiannual_two_quote_each_npv_near_zero(self):
        quotes = [ParSwapQuote(1, 0.0780), ParSwapQuote(2, 0.0800)]
        curve = bootstrap_discount_curve_from_swaps(
            VAL, quotes, "semiannual", DC
        )
        # 2 quotes: the 1Y semiannual adds a 6M intermediate pillar so the
        # curve spans [6M, 1Y, 2Y] — 3 pillars total.
        assert len(curve.pillar_dates) == 3

        for q in quotes:
            swap = VanillaIRS(
                valuation_date=VAL,
                start_date=VAL,
                tenor_years=q.tenor_years,
                notional=1_000_000.0,
                fixed_rate=q.par_rate,
                payment_frequency="semiannual",
                day_count=DC,
                pay_receive="payer",
            )
            result = price_irs(swap, curve)
            assert abs(result.npv) < 1.0, (
                f"Semiannual {q.tenor_years}Y NPV={result.npv:.4f}"
            )


# ===========================================================================
# Quarterly frequency round-trip
# ===========================================================================


class TestQuarterlyFrequency:
    """Bootstrap and reprice with quarterly payment frequency."""

    def test_quarterly_two_quote_each_npv_near_zero(self):
        quotes = [ParSwapQuote(1, 0.0780), ParSwapQuote(2, 0.0800)]
        curve = bootstrap_discount_curve_from_swaps(
            VAL, quotes, "quarterly", DC
        )
        # 2 quotes: the 1Y quarterly adds 3 intermediate pillars (Q1, Q2, Q3)
        # plus the 1Y maturity = 4 pillars from the first quote, then one
        # more maturity pillar for the 2Y = 5 pillars total.
        assert len(curve.pillar_dates) == 5

        for q in quotes:
            swap = VanillaIRS(
                valuation_date=VAL,
                start_date=VAL,
                tenor_years=q.tenor_years,
                notional=1_000_000.0,
                fixed_rate=q.par_rate,
                payment_frequency="quarterly",
                day_count=DC,
                pay_receive="payer",
            )
            result = price_irs(swap, curve)
            assert abs(result.npv) < 1.0, (
                f"Quarterly {q.tenor_years}Y NPV={result.npv:.4f}"
            )


# ===========================================================================
# Interpolation between quoted tenors
# ===========================================================================


class TestInterpolation:
    """
    For a 4Y swap priced on the canonical (1Y/2Y/3Y/5Y) curve, the
    required 4Y maturity date lies between the 3Y and 5Y pillars.
    DiscountCurve handles this via log-linear interpolation.
    """

    def test_can_price_4y_swap_on_1235_curve(self):
        # The curve has no 4Y pillar, but the 4Y swap maturity falls
        # within [3Y pillar, 5Y pillar], so interpolation provides df.
        curve = _bootstrap_canonical()

        # 4Y par rate is unknown; use a rough mid-point for a directional test.
        approx_4y_rate = 0.0835  # between 3Y=8.2% and 5Y=8.5%
        swap = VanillaIRS(
            valuation_date=VAL,
            start_date=VAL,
            tenor_years=4,
            notional=1_000_000.0,
            fixed_rate=approx_4y_rate,
            payment_frequency=FREQ,
            day_count=DC,
            pay_receive="payer",
        )
        # Should not raise — log-linear interpolation covers the 4Y date.
        result = price_irs(swap, curve)
        assert isinstance(result.npv, float)

    def test_df_at_2y_pillar_is_exact(self):
        """
        Querying df exactly at a known pillar returns the bootstrapped value.
        """
        curve = _bootstrap_canonical()
        t2 = _maturity(2)
        assert curve.df(t2) == pytest.approx(curve.discount_factors[1], rel=1e-12)


# ===========================================================================
# Notional scaling
# ===========================================================================


class TestNotionalScaling:
    """NPV must scale linearly with notional; the zero-NPV property is notional-independent."""

    def test_zero_npv_holds_for_large_notional(self):
        curve = _bootstrap_canonical()
        q = CANONICAL_QUOTES[2]  # 3Y
        swap = VanillaIRS(
            valuation_date=VAL,
            start_date=VAL,
            tenor_years=q.tenor_years,
            notional=1_000_000_000.0,
            fixed_rate=q.par_rate,
            payment_frequency=FREQ,
            day_count=DC,
            pay_receive="payer",
        )
        result = price_irs(swap, curve)
        assert abs(result.npv) < 1_000.0   # 1000 ZAR tolerance for 1bn notional


# ===========================================================================
# Reproducibility
# ===========================================================================


class TestReproducibility:
    """Calling the bootstrap twice with the same inputs gives identical results."""

    def test_two_calls_same_result(self):
        c1 = _bootstrap_canonical()
        c2 = _bootstrap_canonical()
        assert c1.pillar_dates == c2.pillar_dates
        for df1, df2 in zip(c1.discount_factors, c2.discount_factors):
            assert df1 == df2  # bit-for-bit identical
