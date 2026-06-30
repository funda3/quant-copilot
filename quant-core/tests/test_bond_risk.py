"""
Tests for quant_core.risk.bond_risk — DV01 and modified duration.

Canonical bond fixture
----------------------
  valuation_date:  2024-01-01
  issue_date:      2024-01-01
  maturity_date:   2029-01-01  (5Y)
  face_value:      1_000_000
  coupon_rate:     0.08
  coupon_frequency: annual
  day_count:       ACT_365F

Curve is the canonical continuously-compounded flat 8% discount curve used
in test_bond_pricer.py (built via quant_core.curves.build_flat.flat_curve).
"""
from __future__ import annotations

from datetime import date

import pytest

from quant_core.conventions.day_count import DayCount
from quant_core.curves.build_flat import flat_curve
from quant_core.instruments.bond import FixedRateBond
from quant_core.pricing.bond_pricer import price_bond
from quant_core.risk.bond_risk import (
    _parallel_bump_curve,
    bond_convexity,
    bond_dv01,
    macaulay_duration,
    modified_duration,
)

# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------

_VAL_DATE = date(2024, 1, 1)
_ISSUE_DATE = date(2024, 1, 1)
_MATURITY_5Y = date(2029, 1, 1)
_MATURITY_10Y = date(2034, 1, 1)
_FACE = 1_000_000.0
_COUPON = 0.08
_FLAT_RATE = 0.08


def _make_bond(
    maturity: date = _MATURITY_5Y,
    coupon: float = _COUPON,
    face: float = _FACE,
    freq: str = "annual",
    day_count: DayCount = DayCount.ACT_365F,
    val_date: date = _VAL_DATE,
    issue_date: date = _ISSUE_DATE,
) -> FixedRateBond:
    return FixedRateBond(
        valuation_date=val_date,
        issue_date=issue_date,
        maturity_date=maturity,
        face_value=face,
        coupon_rate=coupon,
        coupon_frequency=freq,
        day_count=day_count,
    )


def _make_curve(
    val_date: date = _VAL_DATE,
    tenor_years: int = 5,
    rate: float = _FLAT_RATE,
) -> object:
    return flat_curve(
        valuation_date=val_date,
        rate=rate,
        tenor_years=tenor_years,
        frequency="annual",
        day_count=DayCount.ACT_365F,
    )


# ---------------------------------------------------------------------------
# DV01 — sign and basic properties
# ---------------------------------------------------------------------------


class TestBondDv01Sign:
    def test_dv01_positive_for_standard_bond(self) -> None:
        """Rates up → bond price down → DV01 > 0 by convention."""
        bond = _make_bond()
        curve = _make_curve()
        assert bond_dv01(bond, curve) > 0.0

    def test_dv01_positive_for_low_coupon(self) -> None:
        bond = _make_bond(coupon=0.03)
        curve = _make_curve()
        assert bond_dv01(bond, curve) > 0.0

    def test_dv01_positive_for_high_coupon(self) -> None:
        bond = _make_bond(coupon=0.12)
        curve = _make_curve()
        assert bond_dv01(bond, curve) > 0.0

    def test_dv01_positive_for_semiannual_bond(self) -> None:
        bond = _make_bond(freq="semiannual")
        curve = flat_curve(
            valuation_date=_VAL_DATE,
            rate=_FLAT_RATE,
            tenor_years=5,
            frequency="semiannual",
            day_count=DayCount.ACT_365F,
        )
        assert bond_dv01(bond, curve) > 0.0

    def test_dv01_positive_for_quarterly_bond(self) -> None:
        bond = _make_bond(freq="quarterly")
        curve = flat_curve(
            valuation_date=_VAL_DATE,
            rate=_FLAT_RATE,
            tenor_years=5,
            frequency="quarterly",
            day_count=DayCount.ACT_365F,
        )
        assert bond_dv01(bond, curve) > 0.0

    def test_dv01_zero_coupon_positive(self) -> None:
        """Zero-coupon bond still has positive DV01."""
        bond = _make_bond(coupon=0.0)
        curve = _make_curve()
        assert bond_dv01(bond, curve) > 0.0


# ---------------------------------------------------------------------------
# DV01 — scaling
# ---------------------------------------------------------------------------


class TestBondDv01Scaling:
    def test_doubling_face_doubles_dv01(self) -> None:
        bond1 = _make_bond(face=1_000_000.0)
        bond2 = _make_bond(face=2_000_000.0)
        curve = _make_curve()
        dv01_1 = bond_dv01(bond1, curve)
        dv01_2 = bond_dv01(bond2, curve)
        assert abs(dv01_2 - 2.0 * dv01_1) < 1e-4, (
            f"Expected 2× scaling: dv01_1={dv01_1}, dv01_2={dv01_2}"
        )

    def test_smaller_face_smaller_dv01(self) -> None:
        bond_large = _make_bond(face=10_000_000.0)
        bond_small = _make_bond(face=100_000.0)
        curve = _make_curve()
        assert bond_dv01(bond_large, curve) > bond_dv01(bond_small, curve)

    def test_dv01_linear_in_face(self) -> None:
        """DV01/face is constant for different face values."""
        curve = _make_curve()
        dv01_1m = bond_dv01(_make_bond(face=1_000_000.0), curve)
        dv01_5m = bond_dv01(_make_bond(face=5_000_000.0), curve)
        ratio_1m = dv01_1m / 1_000_000.0
        ratio_5m = dv01_5m / 5_000_000.0
        assert abs(ratio_1m - ratio_5m) < 1e-10


# ---------------------------------------------------------------------------
# DV01 — maturity effect (longer bond → higher DV01)
# ---------------------------------------------------------------------------


class TestBondDv01Maturity:
    def test_longer_maturity_higher_dv01(self) -> None:
        bond_5y = _make_bond(maturity=_MATURITY_5Y)
        bond_10y = _make_bond(maturity=_MATURITY_10Y)
        curve = _make_curve(tenor_years=10)
        assert bond_dv01(bond_10y, curve) > bond_dv01(bond_5y, curve)

    def test_2y_dv01_less_than_5y(self) -> None:
        bond_2y = _make_bond(maturity=date(2026, 1, 1))
        bond_5y = _make_bond(maturity=_MATURITY_5Y)
        curve = _make_curve(tenor_years=10)
        assert bond_dv01(bond_5y, curve) > bond_dv01(bond_2y, curve)


# ---------------------------------------------------------------------------
# DV01 — bump_bps parameter
# ---------------------------------------------------------------------------


class TestBondDv01BumpParam:
    def test_larger_bump_proportionally_larger_dv01(self) -> None:
        """dv01(2bp) ≈ 2 × dv01(1bp) for small bumps."""
        bond = _make_bond()
        curve = _make_curve()
        dv01_1 = bond_dv01(bond, curve, bump_bps=1)
        dv01_2 = bond_dv01(bond, curve, bump_bps=2)
        assert abs(dv01_2 - 2.0 * dv01_1) / dv01_1 < 0.001  # within 0.1%

    def test_invalid_zero_bump_raises(self) -> None:
        bond = _make_bond()
        curve = _make_curve()
        with pytest.raises(ValueError, match="bump_bps must be positive"):
            bond_dv01(bond, curve, bump_bps=0)

    def test_invalid_negative_bump_raises(self) -> None:
        bond = _make_bond()
        curve = _make_curve()
        with pytest.raises(ValueError, match="bump_bps must be positive"):
            bond_dv01(bond, curve, bump_bps=-1)


# ---------------------------------------------------------------------------
# Modified duration — sign and basic properties
# ---------------------------------------------------------------------------


class TestModifiedDuration:
    def test_modified_duration_positive(self) -> None:
        bond = _make_bond()
        curve = _make_curve()
        assert modified_duration(bond, curve) > 0.0

    def test_modified_duration_positive_for_zero_coupon(self) -> None:
        bond = _make_bond(coupon=0.0)
        curve = _make_curve()
        assert modified_duration(bond, curve) > 0.0

    def test_longer_maturity_higher_duration(self) -> None:
        bond_5y = _make_bond(maturity=_MATURITY_5Y)
        bond_10y = _make_bond(maturity=_MATURITY_10Y)
        curve = _make_curve(tenor_years=10)
        dur_5y = modified_duration(bond_5y, curve)
        dur_10y = modified_duration(bond_10y, curve)
        assert dur_10y > dur_5y

    def test_zero_coupon_duration_approaches_maturity(self) -> None:
        """
        A zero-coupon bond has modified duration ≈ maturity_years / (1 + r).
        
        With 8% CC rate and 5Y maturity:
            CC zero rate ≈ 8%, simple-equivalent ≈ e^0.08 - 1 ≈ 8.33%
            modified_duration ≈ 5 / (1 + 0.0833) ≈ 4.62
        
        We test that it falls in a reasonable range [4.0, 5.5].
        """
        bond = _make_bond(coupon=0.0, maturity=_MATURITY_5Y)
        curve = _make_curve()
        dur = modified_duration(bond, curve)
        assert 4.0 < dur < 5.5

    def test_duration_matches_dv01_identity(self) -> None:
        """modified_duration = dv01 / dirty_price * 10_000."""
        bond = _make_bond()
        curve = _make_curve()
        from quant_core.pricing.bond_pricer import price_bond as _pb
        dirty = _pb(bond, curve).dirty_price
        dv01 = bond_dv01(bond, curve)
        expected_dur = dv01 / dirty * 10_000.0
        assert abs(modified_duration(bond, curve) - expected_dur) < 1e-10

    def test_duration_unchanged_by_face_scaling(self) -> None:
        """Modified duration is face-value-neutral."""
        curve = _make_curve()
        dur_1m = modified_duration(_make_bond(face=1_000_000.0), curve)
        dur_10m = modified_duration(_make_bond(face=10_000_000.0), curve)
        assert abs(dur_1m - dur_10m) < 1e-8

    def test_lower_coupon_higher_duration(self) -> None:
        """Lower coupon → more weight at maturity → higher duration."""
        curve = _make_curve()
        dur_low = modified_duration(_make_bond(coupon=0.03), curve)
        dur_high = modified_duration(_make_bond(coupon=0.12), curve)
        assert dur_low > dur_high


# ---------------------------------------------------------------------------
# _parallel_bump_curve — unit tests
# ---------------------------------------------------------------------------


class TestParallelBumpCurve:
    def test_bump_does_not_mutate_original(self) -> None:
        curve = _make_curve()
        original_dfs = list(curve.discount_factors)
        _parallel_bump_curve(curve, 1.0)
        assert curve.discount_factors == original_dfs

    def test_bump_reduces_discount_factors(self) -> None:
        """Positive bump (rate rise) reduces all discount factors."""
        curve = _make_curve()
        bumped = _parallel_bump_curve(curve, 1.0)
        for df_orig, df_bumped in zip(curve.discount_factors, bumped.discount_factors):
            assert df_bumped < df_orig

    def test_zero_bump_leaves_curve_unchanged(self) -> None:
        curve = _make_curve()
        bumped = _parallel_bump_curve(curve, 0.0)
        for df_orig, df_bumped in zip(curve.discount_factors, bumped.discount_factors):
            assert abs(df_orig - df_bumped) < 1e-15

    def test_bumped_curve_has_same_pillar_dates(self) -> None:
        curve = _make_curve()
        bumped = _parallel_bump_curve(curve, 1.0)
        assert bumped.pillar_dates == curve.pillar_dates

    def test_bumped_curve_same_valuation_date(self) -> None:
        curve = _make_curve()
        bumped = _parallel_bump_curve(curve, 5.0)
        assert bumped.valuation_date == curve.valuation_date


# ---------------------------------------------------------------------------
# Bond convexity
# ---------------------------------------------------------------------------


class TestBondConvexity:
    def test_convexity_positive_standard_bond(self) -> None:
        """Convexity is always positive for a standard fixed-rate bond."""
        bond = _make_bond()
        curve = _make_curve()
        assert bond_convexity(bond, curve) > 0.0

    def test_convexity_positive_zero_coupon(self) -> None:
        """Convexity is positive for a zero-coupon bond."""
        bond = _make_bond(coupon=0.0)
        curve = _make_curve()
        assert bond_convexity(bond, curve) > 0.0

    def test_longer_maturity_higher_convexity(self) -> None:
        """Longer maturity bond has higher convexity (all else equal)."""
        bond_5y = _make_bond(maturity=_MATURITY_5Y)
        bond_10y = _make_bond(maturity=_MATURITY_10Y)
        curve = _make_curve(tenor_years=10)
        assert bond_convexity(bond_10y, curve) > bond_convexity(bond_5y, curve)

    def test_convexity_scales_linearly_with_face(self) -> None:
        """
        The raw convexity formula (P_minus + P_plus - 2*P0) / (P0 * dy^2) is
        face-value-neutral because numerator and P0 both scale with face.
        """
        curve = _make_curve()
        cx_1m = bond_convexity(_make_bond(face=1_000_000.0), curve)
        cx_5m = bond_convexity(_make_bond(face=5_000_000.0), curve)
        assert abs(cx_1m - cx_5m) < 1e-6

    def test_convexity_positive_for_low_coupon(self) -> None:
        bond = _make_bond(coupon=0.03)
        curve = _make_curve()
        assert bond_convexity(bond, curve) > 0.0

    def test_convexity_positive_for_high_coupon(self) -> None:
        bond = _make_bond(coupon=0.12)
        curve = _make_curve()
        assert bond_convexity(bond, curve) > 0.0

    def test_convexity_positive_for_semiannual_bond(self) -> None:
        bond = _make_bond(freq="semiannual")
        curve = flat_curve(
            valuation_date=_VAL_DATE,
            rate=_FLAT_RATE,
            tenor_years=5,
            frequency="semiannual",
            day_count=DayCount.ACT_365F,
        )
        assert bond_convexity(bond, curve) > 0.0

    def test_invalid_zero_bump_raises(self) -> None:
        bond = _make_bond()
        curve = _make_curve()
        with pytest.raises(ValueError, match="bump_bps must be positive"):
            bond_convexity(bond, curve, bump_bps=0)

    def test_invalid_negative_bump_raises(self) -> None:
        bond = _make_bond()
        curve = _make_curve()
        with pytest.raises(ValueError, match="bump_bps must be positive"):
            bond_convexity(bond, curve, bump_bps=-1)

    def test_lower_coupon_higher_convexity(self) -> None:
        """Lower coupon bond has more weight at maturity → higher convexity."""
        curve = _make_curve()
        cx_low = bond_convexity(_make_bond(coupon=0.03), curve)
        cx_high = bond_convexity(_make_bond(coupon=0.12), curve)
        assert cx_low > cx_high

    def test_does_not_mutate_curve(self) -> None:
        curve = _make_curve()
        original_dfs = list(curve.discount_factors)
        bond_convexity(_make_bond(), curve)
        assert curve.discount_factors == original_dfs


# ---------------------------------------------------------------------------
# Macaulay Duration
# ---------------------------------------------------------------------------


class TestMacaulayDuration:
    def test_macaulay_duration_positive(self) -> None:
        """Macaulay Duration must be positive for a standard bond."""
        bond = _make_bond()
        curve = _make_curve()
        assert macaulay_duration(bond, curve) > 0.0

    def test_macaulay_duration_is_float(self) -> None:
        bond = _make_bond()
        curve = _make_curve()
        result = macaulay_duration(bond, curve)
        assert isinstance(result, float)

    def test_macaulay_duration_zcb_equals_maturity_year_fraction(self) -> None:
        """
        For a zero-coupon bond, Macaulay Duration == year fraction to maturity.
        
        The ZCB has a single cashflow at maturity; the PV terms cancel, so
        D_mac == accrual_fraction(val_date, maturity_date, day_count).
        Both are measured in ACT_365F; 5 calendar years from 2024-01-01 to
        2029-01-01 spans a leap year so the fraction is slightly above 5.0.
        """
        bond = _make_bond(coupon=0.0, maturity=_MATURITY_5Y)
        curve = _make_curve()
        from quant_core.conventions.day_count import accrual_fraction, DayCount
        expected = accrual_fraction(_VAL_DATE, _MATURITY_5Y, DayCount.ACT_365F)
        assert abs(macaulay_duration(bond, curve) - expected) < 1e-12

    def test_macaulay_duration_zcb_positive(self) -> None:
        bond = _make_bond(coupon=0.0)
        curve = _make_curve()
        assert macaulay_duration(bond, curve) > 0.0

    def test_macaulay_ge_modified_duration(self) -> None:
        """
        For a bond at par (coupon rate == flat yield), Macaulay Duration
        is always >= Modified Duration for any positive yield.
        The inequality D_mac >= D_mod holds because D_mod = D_mac / (1+y*tau)
        with the period yield factor always >= 1.
        """
        bond = _make_bond()
        curve = _make_curve()
        d_mac = macaulay_duration(bond, curve)
        d_mod = modified_duration(bond, curve)
        assert d_mac >= d_mod

    def test_longer_maturity_higher_macaulay(self) -> None:
        """Longer maturity bond has higher Macaulay Duration."""
        bond_5y = _make_bond(maturity=_MATURITY_5Y)
        bond_10y = _make_bond(maturity=_MATURITY_10Y)
        curve = _make_curve(tenor_years=10)
        assert macaulay_duration(bond_10y, curve) > macaulay_duration(bond_5y, curve)

    def test_lower_coupon_higher_macaulay(self) -> None:
        """Lower coupon bond has more weight at maturity → higher Macaulay Duration."""
        curve = _make_curve()
        d_low = macaulay_duration(_make_bond(coupon=0.03), curve)
        d_high = macaulay_duration(_make_bond(coupon=0.12), curve)
        assert d_low > d_high

    def test_macaulay_face_neutral(self) -> None:
        """Macaulay Duration does not depend on face value."""
        curve = _make_curve()
        d_1m = macaulay_duration(_make_bond(face=1_000_000.0), curve)
        d_5m = macaulay_duration(_make_bond(face=5_000_000.0), curve)
        assert abs(d_1m - d_5m) < 1e-10

    def test_macaulay_within_maturity_range(self) -> None:
        """Macaulay Duration must be in (0, maturity_years] for a coupon bond."""
        bond = _make_bond(maturity=_MATURITY_5Y)
        curve = _make_curve()
        d = macaulay_duration(bond, curve)
        from quant_core.conventions.day_count import accrual_fraction, DayCount
        t_mat = accrual_fraction(_VAL_DATE, _MATURITY_5Y, DayCount.ACT_365F)
        assert 0.0 < d <= t_mat

    def test_macaulay_positive_for_semiannual_bond(self) -> None:
        bond = _make_bond(freq="semiannual")
        curve = flat_curve(
            valuation_date=_VAL_DATE,
            rate=_FLAT_RATE,
            tenor_years=5,
            frequency="semiannual",
            day_count=DayCount.ACT_365F,
        )
        assert macaulay_duration(bond, curve) > 0.0

    def test_macaulay_does_not_mutate_curve(self) -> None:
        curve = _make_curve()
        original_dfs = list(curve.discount_factors)
        macaulay_duration(_make_bond(), curve)
        assert curve.discount_factors == original_dfs
