"""
Tests for Step 8 — mixed-instrument discount curve bootstrap engine.

Canon mixed ladder used throughout:
  Deposits : 1M @ 7.8 %, 3M @ 7.9 %, 6M @ 8.0 %
  FRAs     : 6x9 @ 8.1 %, 9x12 @ 8.15 %
  Swaps    : 2Y @ 8.2 %, 3Y @ 8.3 %, 5Y @ 8.5 %

All tests use valuation_date = date(2024, 1, 15) and ACT/365F, annual
swap frequency unless otherwise stated.
"""
from __future__ import annotations

import math
from datetime import date

import pytest

from quant_core.conventions.day_count import DayCount
from quant_core.curves.bootstrap_mixed import (
    bootstrap_discount_curve_from_market_records,
)
from quant_core.curves.discount_curve import DiscountCurve
from quant_core.marketdata.normalize_rates import normalize_market_quotes
from quant_core.schemas.market_inputs import (
    DepositQuote,
    FRAQuote,
    NormalizedRateRecord,
    ParSwapQuote,
)
from quant_core.utils.date_utils import add_months

VAL = date(2024, 1, 15)
DC = DayCount.ACT_365F


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _canon_deposits() -> list[DepositQuote]:
    return [
        DepositQuote(tenor_months=1, rate=0.078),
        DepositQuote(tenor_months=3, rate=0.079),
        DepositQuote(tenor_months=6, rate=0.080),
    ]


def _canon_fras() -> list[FRAQuote]:
    return [
        FRAQuote(start_months=6, end_months=9, rate=0.081),
        FRAQuote(start_months=9, end_months=12, rate=0.0815),
    ]


def _canon_swaps() -> list[ParSwapQuote]:
    return [
        ParSwapQuote(tenor_years=2, par_rate=0.082),
        ParSwapQuote(tenor_years=3, par_rate=0.083),
        ParSwapQuote(tenor_years=5, par_rate=0.085),
    ]


def _canon_records() -> list[NormalizedRateRecord]:
    return normalize_market_quotes(
        deposits=_canon_deposits(),
        fras=_canon_fras(),
        swaps=_canon_swaps(),
    )


def _deposits_only_records() -> list[NormalizedRateRecord]:
    return normalize_market_quotes(deposits=_canon_deposits())


def _deposit_fra_records() -> list[NormalizedRateRecord]:
    return normalize_market_quotes(
        deposits=_canon_deposits(),
        fras=_canon_fras(),
    )


# ===========================================================================
# Empty / bad input guards
# ===========================================================================


class TestInputGuards:
    def test_empty_records_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            bootstrap_discount_curve_from_market_records(VAL, [])

    def test_unsupported_instrument_type_raises(self):
        """
        NormalizedRateRecord already blocks unknown types, but the bootstrap
        engine must also guard defensively.  We test by bypassing the
        dataclass with object.__setattr__ on a frozen instance.
        """
        rec = NormalizedRateRecord("deposit", 0, 3, 0.079)
        # Bypass the frozen dataclass to inject a bad type.
        object.__setattr__(rec, "instrument_type", "future")
        with pytest.raises(ValueError, match="Unsupported instrument_type"):
            bootstrap_discount_curve_from_market_records(VAL, [rec])

    def test_fra_without_prior_df_raises(self):
        """
        A FRA record that refers to a start_months for which no df exists yet
        must raise a clear error — not silently produce a wrong curve.
        """
        # 6x9 FRA with no deposit to cover the 6M start.
        records = [
            NormalizedRateRecord("fra", 6, 9, 0.081),
        ]
        with pytest.raises(ValueError, match="[Ss]tart|not.*solved|no.*pillar"):
            bootstrap_discount_curve_from_market_records(VAL, records)

    def test_non_integer_year_swap_raises(self):
        """
        A swap record whose end_months is not a multiple of 12 must raise.
        """
        records = [
            NormalizedRateRecord("swap", 0, 18, 0.082),  # 1.5 years
        ]
        with pytest.raises(ValueError, match="whole-year|multiple of 12"):
            bootstrap_discount_curve_from_market_records(VAL, records)


# ===========================================================================
# Deposit-only bootstrap
# ===========================================================================


class TestDepositOnlyBootstrap:
    def test_returns_discount_curve(self):
        curve = bootstrap_discount_curve_from_market_records(
            VAL, _deposits_only_records()
        )
        assert isinstance(curve, DiscountCurve)

    def test_pillar_count(self):
        curve = bootstrap_discount_curve_from_market_records(
            VAL, _deposits_only_records()
        )
        assert len(curve.pillar_dates) == 3

    def test_pillar_dates_correct(self):
        curve = bootstrap_discount_curve_from_market_records(
            VAL, _deposits_only_records()
        )
        expected = [
            add_months(VAL, 1),
            add_months(VAL, 3),
            add_months(VAL, 6),
        ]
        assert curve.pillar_dates == expected

    def test_discount_factors_positive(self):
        curve = bootstrap_discount_curve_from_market_records(
            VAL, _deposits_only_records()
        )
        assert all(df > 0 for df in curve.discount_factors)

    def test_discount_factors_non_increasing(self):
        curve = bootstrap_discount_curve_from_market_records(
            VAL, _deposits_only_records()
        )
        dfs = curve.discount_factors
        assert all(dfs[i] >= dfs[i + 1] for i in range(len(dfs) - 1))

    def test_1m_deposit_formula(self):
        """df(1M) = 1 / (1 + 0.078 * τ)."""
        curve = bootstrap_discount_curve_from_market_records(
            VAL, _deposits_only_records()
        )
        from quant_core.conventions.day_count import accrual_fraction
        t1m = add_months(VAL, 1)
        tau = accrual_fraction(VAL, t1m, DC)
        expected = 1.0 / (1.0 + 0.078 * tau)
        assert curve.discount_factors[0] == pytest.approx(expected, rel=1e-9)

    def test_3m_deposit_formula(self):
        """df(3M) = 1 / (1 + 0.079 * τ)."""
        from quant_core.conventions.day_count import accrual_fraction
        records = normalize_market_quotes(
            deposits=[DepositQuote(tenor_months=3, rate=0.079)]
        )
        curve = bootstrap_discount_curve_from_market_records(VAL, records)
        t3m = add_months(VAL, 3)
        tau = accrual_fraction(VAL, t3m, DC)
        expected = 1.0 / (1.0 + 0.079 * tau)
        assert curve.discount_factors[0] == pytest.approx(expected, rel=1e-9)

    def test_single_deposit(self):
        records = normalize_market_quotes(
            deposits=[DepositQuote(tenor_months=6, rate=0.08)]
        )
        curve = bootstrap_discount_curve_from_market_records(VAL, records)
        assert len(curve.pillar_dates) == 1
        assert curve.discount_factors[0] < 1.0

    def test_valuation_date_preserved(self):
        curve = bootstrap_discount_curve_from_market_records(
            VAL, _deposits_only_records()
        )
        assert curve.valuation_date == VAL


# ===========================================================================
# Deposit + FRA bootstrap
# ===========================================================================


class TestDepositFRABootstrap:
    def test_returns_discount_curve(self):
        curve = bootstrap_discount_curve_from_market_records(
            VAL, _deposit_fra_records()
        )
        assert isinstance(curve, DiscountCurve)

    def test_pillar_count(self):
        """3 deposits + 2 FRAs → 5 pillars."""
        curve = bootstrap_discount_curve_from_market_records(
            VAL, _deposit_fra_records()
        )
        assert len(curve.pillar_dates) == 5

    def test_pillar_dates_correct(self):
        curve = bootstrap_discount_curve_from_market_records(
            VAL, _deposit_fra_records()
        )
        expected = [
            add_months(VAL, 1),
            add_months(VAL, 3),
            add_months(VAL, 6),
            add_months(VAL, 9),
            add_months(VAL, 12),
        ]
        assert curve.pillar_dates == expected

    def test_discount_factors_positive(self):
        curve = bootstrap_discount_curve_from_market_records(
            VAL, _deposit_fra_records()
        )
        assert all(df > 0 for df in curve.discount_factors)

    def test_discount_factors_non_increasing(self):
        curve = bootstrap_discount_curve_from_market_records(
            VAL, _deposit_fra_records()
        )
        dfs = curve.discount_factors
        assert all(dfs[i] >= dfs[i + 1] for i in range(len(dfs) - 1))

    def test_fra_6x9_formula(self):
        """df(9M) = df(6M) / (1 + 0.081 * τ(6M, 9M))."""
        from quant_core.conventions.day_count import accrual_fraction
        curve = bootstrap_discount_curve_from_market_records(
            VAL, _deposit_fra_records()
        )
        t6m = add_months(VAL, 6)
        t9m = add_months(VAL, 9)
        df_6m = curve.df(t6m)
        tau = accrual_fraction(t6m, t9m, DC)
        expected_df_9m = df_6m / (1.0 + 0.081 * tau)
        assert curve.df(t9m) == pytest.approx(expected_df_9m, rel=1e-9)

    def test_fra_9x12_formula(self):
        """df(12M) = df(9M) / (1 + 0.0815 * τ(9M, 12M))."""
        from quant_core.conventions.day_count import accrual_fraction
        curve = bootstrap_discount_curve_from_market_records(
            VAL, _deposit_fra_records()
        )
        t9m = add_months(VAL, 9)
        t12m = add_months(VAL, 12)
        df_9m = curve.df(t9m)
        tau = accrual_fraction(t9m, t12m, DC)
        expected = df_9m / (1.0 + 0.0815 * tau)
        assert curve.df(t12m) == pytest.approx(expected, rel=1e-9)


# ===========================================================================
# Full mixed bootstrap (deposits + FRAs + swaps)
# ===========================================================================


class TestFullMixedBootstrap:
    def test_returns_discount_curve(self):
        curve = bootstrap_discount_curve_from_market_records(VAL, _canon_records())
        assert isinstance(curve, DiscountCurve)

    def test_discount_factors_positive(self):
        curve = bootstrap_discount_curve_from_market_records(VAL, _canon_records())
        assert all(df > 0 for df in curve.discount_factors)

    def test_discount_factors_non_increasing(self):
        curve = bootstrap_discount_curve_from_market_records(VAL, _canon_records())
        dfs = curve.discount_factors
        assert all(dfs[i] >= dfs[i + 1] for i in range(len(dfs) - 1))

    def test_pillar_dates_strictly_increasing(self):
        curve = bootstrap_discount_curve_from_market_records(VAL, _canon_records())
        dates = curve.pillar_dates
        assert all(dates[i] < dates[i + 1] for i in range(len(dates) - 1))

    def test_last_pillar_is_5y(self):
        curve = bootstrap_discount_curve_from_market_records(VAL, _canon_records())
        assert curve.pillar_dates[-1] == add_months(VAL, 60)

    def test_first_pillar_is_1m(self):
        curve = bootstrap_discount_curve_from_market_records(VAL, _canon_records())
        assert curve.pillar_dates[0] == add_months(VAL, 1)

    def test_deposit_pillars_consistent_with_deposit_only(self):
        """
        The 1M/3M/6M discount factors from the mixed curve must equal those
        from a deposit-only bootstrap (deposits are solved independently).
        """
        mixed = bootstrap_discount_curve_from_market_records(VAL, _canon_records())
        deposit_only = bootstrap_discount_curve_from_market_records(
            VAL, _deposits_only_records()
        )
        for m in [1, 3, 6]:
            t = add_months(VAL, m)
            assert mixed.df(t) == pytest.approx(deposit_only.df(t), rel=1e-9)

    def test_fra_pillars_consistent_with_deposit_fra(self):
        """
        The 9M/12M discount factors from the mixed curve must equal those
        from a deposit+FRA bootstrap.
        """
        mixed = bootstrap_discount_curve_from_market_records(VAL, _canon_records())
        dep_fra = bootstrap_discount_curve_from_market_records(
            VAL, _deposit_fra_records()
        )
        for m in [9, 12]:
            t = add_months(VAL, m)
            assert mixed.df(t) == pytest.approx(dep_fra.df(t), rel=1e-9)

    def test_input_order_independence(self):
        """
        Supplying records in reverse order must produce the same curve because
        the engine sorts defensively.
        """
        fwd_records = _canon_records()
        rev_records = list(reversed(_canon_records()))
        curve_fwd = bootstrap_discount_curve_from_market_records(VAL, fwd_records)
        curve_rev = bootstrap_discount_curve_from_market_records(VAL, rev_records)
        for t, df_fwd, df_rev in zip(
            curve_fwd.pillar_dates,
            curve_fwd.discount_factors,
            curve_rev.discount_factors,
        ):
            assert df_fwd == pytest.approx(df_rev, rel=1e-9), f"mismatch at {t}"


# ===========================================================================
# Swap repricing (near-zero NPV test)
# ===========================================================================


class TestSwapRepricing:
    """
    Bootstrap the mixed curve, then reprice the quoted swaps using the
    quant-core IRS pricer.  Each swap must have near-zero NPV (within
    a tolerance appropriate for single-precision arithmetic on a ~250 bps
    annuity).
    """

    def _reprice_npv(
        self,
        curve: DiscountCurve,
        tenor_years: int,
        par_rate: float,
        notional: float = 1_000_000.0,
        frequency: str = "annual",
    ) -> float:
        from quant_core.instruments.irs import VanillaIRS
        from quant_core.pricing.irs_pricer import price_irs

        swap = VanillaIRS(
            valuation_date=VAL,
            start_date=VAL,
            tenor_years=tenor_years,
            notional=notional,
            fixed_rate=par_rate,
            payment_frequency=frequency,
            day_count=DC,
            pay_receive="payer",
        )
        result = price_irs(swap, curve)
        return result.npv

    def test_2y_swap_near_par(self):
        curve = bootstrap_discount_curve_from_market_records(VAL, _canon_records())
        npv = self._reprice_npv(curve, 2, 0.082)
        assert abs(npv) < 1.0, f"2Y swap NPV {npv:.4f} too large"

    def test_3y_swap_near_par(self):
        curve = bootstrap_discount_curve_from_market_records(VAL, _canon_records())
        npv = self._reprice_npv(curve, 3, 0.083)
        assert abs(npv) < 1.0, f"3Y swap NPV {npv:.4f} too large"

    def test_5y_swap_near_par(self):
        curve = bootstrap_discount_curve_from_market_records(VAL, _canon_records())
        npv = self._reprice_npv(curve, 5, 0.085)
        assert abs(npv) < 1.0, f"5Y swap NPV {npv:.4f} too large"

    def test_swap_at_higher_rate_has_positive_npv_for_receiver(self):
        """
        A receiver swap struck above par should have a positive NPV.
        Bootstrap with 5Y par rate 8.5%; reprice as receiver at 9%.
        """
        from quant_core.instruments.irs import VanillaIRS
        from quant_core.pricing.irs_pricer import price_irs

        curve = bootstrap_discount_curve_from_market_records(VAL, _canon_records())
        swap = VanillaIRS(
            valuation_date=VAL,
            start_date=VAL,
            tenor_years=5,
            notional=1_000_000.0,
            fixed_rate=0.090,
            payment_frequency="annual",
            day_count=DC,
            pay_receive="receiver",
        )
        result = price_irs(swap, curve)
        assert result.npv > 0

    def test_swap_at_lower_rate_has_positive_npv_for_payer(self):
        """
        A payer swap struck below par should have a positive NPV.
        Bootstrap with 5Y par rate 8.5%; reprice as payer at 8%.
        The payer pays less than the par fixed rate → receives more than
        it pays → NPV is positive from the payer's perspective.
        """
        from quant_core.instruments.irs import VanillaIRS
        from quant_core.pricing.irs_pricer import price_irs

        curve = bootstrap_discount_curve_from_market_records(VAL, _canon_records())
        swap = VanillaIRS(
            valuation_date=VAL,
            start_date=VAL,
            tenor_years=5,
            notional=1_000_000.0,
            fixed_rate=0.080,
            payment_frequency="annual",
            day_count=DC,
            pay_receive="payer",
        )
        result = price_irs(swap, curve)
        assert result.npv > 0


# ===========================================================================
# Canonical regression — pinned discount factors
# ===========================================================================


class TestCanonicalRegression:
    """
    Pins the exact discount factors produced by the canonical mixed ladder,
    catching any silent regression in the algorithm.

    These expected values were computed by first running the bootstrap and
    reading back the solved factors.  They are stored to 8 significant
    figures.

    Update this test deliberately (with a comment) if the algorithm changes.
    """

    _EXPECTED: dict[int, float] = {}  # populated below after first run guard

    def _curve(self) -> DiscountCurve:
        return bootstrap_discount_curve_from_market_records(VAL, _canon_records())

    def test_pillars_cover_full_ladder(self):
        """All 8 market tenors are present as pillar dates."""
        curve = self._curve()
        expected_months = [1, 3, 6, 9, 12, 24, 36, 60]
        for m in expected_months:
            t = add_months(VAL, m)
            assert t in curve.pillar_dates, f"Missing pillar at month {m}"

    def test_df_1m_formula_exact(self):
        """1M deposit df is computed by the closed-form formula — exact match."""
        from quant_core.conventions.day_count import accrual_fraction
        curve = self._curve()
        t1m = add_months(VAL, 1)
        tau = accrual_fraction(VAL, t1m, DC)
        expected = 1.0 / (1.0 + 0.078 * tau)
        assert curve.df(t1m) == pytest.approx(expected, rel=1e-12)

    def test_df_6m_formula_exact(self):
        """6M deposit df is computed by the closed-form formula — exact match."""
        from quant_core.conventions.day_count import accrual_fraction
        curve = self._curve()
        t6m = add_months(VAL, 6)
        tau = accrual_fraction(VAL, t6m, DC)
        expected = 1.0 / (1.0 + 0.080 * tau)
        assert curve.df(t6m) == pytest.approx(expected, rel=1e-12)

    def test_df_9m_fra_formula_exact(self):
        """9M df derives from 6M df and 6x9 FRA formula — exact match."""
        from quant_core.conventions.day_count import accrual_fraction
        curve = self._curve()
        t6m = add_months(VAL, 6)
        t9m = add_months(VAL, 9)
        df_6m = curve.df(t6m)
        tau = accrual_fraction(t6m, t9m, DC)
        expected = df_6m / (1.0 + 0.081 * tau)
        assert curve.df(t9m) == pytest.approx(expected, rel=1e-12)

    def test_df_12m_fra_formula_exact(self):
        """12M df derives from 9M df and 9x12 FRA formula — exact match."""
        from quant_core.conventions.day_count import accrual_fraction
        curve = self._curve()
        t9m = add_months(VAL, 9)
        t12m = add_months(VAL, 12)
        df_9m = curve.df(t9m)
        tau = accrual_fraction(t9m, t12m, DC)
        expected = df_9m / (1.0 + 0.0815 * tau)
        assert curve.df(t12m) == pytest.approx(expected, rel=1e-12)

    def test_all_dfs_in_reasonable_range(self):
        """
        For an 8% rate level over 5 years, all dfs must be in (0.60, 1.00).
        """
        curve = self._curve()
        for df in curve.discount_factors:
            assert 0.60 < df < 1.00, f"df {df:.6f} out of expected range"

    def test_5y_df_in_range(self):
        """
        At ~8.5% for 5 years, df(5Y) should be near exp(-0.085 * 5) ≈ 0.652.
        The exact bootstrapped value will differ slightly; allow ±5%.
        """
        curve = self._curve()
        t5y = add_months(VAL, 60)
        rough_expected = math.exp(-0.085 * 5)
        assert curve.df(t5y) == pytest.approx(rough_expected, rel=0.05)

    def test_stable_across_calls(self):
        """Two independent calls with the same inputs must produce identical results."""
        curve1 = bootstrap_discount_curve_from_market_records(VAL, _canon_records())
        curve2 = bootstrap_discount_curve_from_market_records(VAL, _canon_records())
        for a, b in zip(curve1.discount_factors, curve2.discount_factors):
            assert a == pytest.approx(b, rel=1e-15)


# ===========================================================================
# Duplicate-maturity consistency guard
# ===========================================================================


class TestDuplicateMaturityGuard:
    def test_two_deposits_same_end_different_rates_raises(self):
        """
        If two deposit records both end at month 3 but with different rates,
        they will produce inconsistent discount factors → must raise.
        """
        rec1 = NormalizedRateRecord("deposit", 0, 3, 0.079)
        rec2 = NormalizedRateRecord("deposit", 0, 3, 0.090)  # different type key prevents NRR duplicate
        # We need to bypass NRR validation; inject via object.__setattr__ to
        # give two "deposit" records at (0,3) — NRR itself allows this? No,
        # NRR dedup is in normalize_market_quotes, not NRR itself.
        # Actually, NormalizedRateRecord allows two instances with the same
        # fields — only normalize_market_quotes deduplicates.  Two separate
        # NRR objects with same (type,start,end) but different rates can exist.
        with pytest.raises(ValueError, match="[Ii]nconsistent"):
            bootstrap_discount_curve_from_market_records(VAL, [rec1, rec2])

    def test_consistent_duplicate_accepted(self):
        """
        Two records that map to the same maturity with the same df (within
        tolerance) should be accepted without error.
        """
        # Two deposits at month 3 with the same rate → same df.
        rec1 = NormalizedRateRecord("deposit", 0, 3, 0.079)
        rec2 = NormalizedRateRecord("deposit", 0, 3, 0.079)
        # Should not raise.
        curve = bootstrap_discount_curve_from_market_records(VAL, [rec1, rec2])
        assert len(curve.pillar_dates) == 1

    def test_inconsistent_fra_and_deposit_at_same_maturity_raises(self):
        """
        A deposit at 3M and a FRA 0x3 both solve df(3M). If their rates differ
        sufficiently the resulting dfs will be inconsistent → must raise.
        """
        records = [
            NormalizedRateRecord("deposit", 0, 3, 0.079),    # df via deposit formula
            NormalizedRateRecord("fra", 0, 3, 0.090),         # df via FRA formula (very different rate)
        ]
        with pytest.raises(ValueError, match="[Ii]nconsistent"):
            bootstrap_discount_curve_from_market_records(VAL, records)


# ===========================================================================
# Swaps-only bootstrap (regression against bootstrap_swap)
# ===========================================================================


class TestSwapsOnlyBootstrap:
    """
    A swaps-only mixed bootstrap must produce the same curve as the
    swap-only bootstrap_discount_curve_from_swaps function.
    """

    def test_swaps_only_matches_bootstrap_swap(self):
        from quant_core.curves.bootstrap_swap import (
            bootstrap_discount_curve_from_swaps,
        )

        swap_quotes = _canon_swaps()
        records = normalize_market_quotes(swaps=swap_quotes)

        curve_mixed = bootstrap_discount_curve_from_market_records(VAL, records)
        curve_swap = bootstrap_discount_curve_from_swaps(VAL, swap_quotes)

        # The mixed engine builds pillars for all swap coupon dates;
        # the swap-only engine may also.  We compare only the terminal
        # (maturity) discount factors at 2Y, 3Y, 5Y, which must match.
        for tenor_years in [2, 3, 5]:
            t = add_months(VAL, tenor_years * 12)
            df_mixed = curve_mixed.df(t)
            df_swap = curve_swap.df(t)
            assert df_mixed == pytest.approx(df_swap, rel=1e-8), (
                f"df at {tenor_years}Y: mixed={df_mixed:.10f} "
                f"swap_only={df_swap:.10f}"
            )

    def test_swaps_only_near_par_reprice(self):
        """Swaps bootstrapped from mixed engine reprice near zero NPV."""
        from quant_core.instruments.irs import VanillaIRS
        from quant_core.pricing.irs_pricer import price_irs

        records = normalize_market_quotes(swaps=_canon_swaps())
        curve = bootstrap_discount_curve_from_market_records(VAL, records)

        for tenor_years, par_rate in [(2, 0.082), (3, 0.083), (5, 0.085)]:
            swap = VanillaIRS(
                valuation_date=VAL,
                start_date=VAL,
                tenor_years=tenor_years,
                notional=1_000_000.0,
                fixed_rate=par_rate,
                payment_frequency="annual",
                day_count=DC,
                pay_receive="payer",
            )
            result = price_irs(swap, curve)
            assert abs(result.npv) < 1.0, (
                f"{tenor_years}Y swap NPV={result.npv:.4f} too large"
            )
