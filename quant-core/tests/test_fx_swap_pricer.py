from __future__ import annotations

from datetime import date

import pytest

from quant_core.conventions.day_count import DayCount, accrual_fraction
from quant_core.instruments.fx_swap import FXSwap
from quant_core.pricing.fx_swap_pricer import FXSwapPricingResult, price_fx_swap


def _fx_swap(**overrides) -> FXSwap:
    defaults = dict(
        valuation_date=date(2024, 1, 1),
        near_settlement_date=date(2024, 1, 3),
        far_settlement_date=date(2024, 7, 1),
        spot_rate=18.25,
        near_rate=18.27,
        far_rate=18.65,
        notional_foreign=1_000_000.0,
        domestic_currency="ZAR",
        foreign_currency="USD",
        domestic_rate=0.08,
        day_count=DayCount.ACT_365F,
        position="long_foreign",
    )
    defaults.update(overrides)
    return FXSwap(**defaults)


class TestFXSwapConstruction:
    def test_near_not_after_valuation_raises(self):
        with pytest.raises(ValueError, match="near_settlement_date"):
            _fx_swap(near_settlement_date=date(2024, 1, 1))

    def test_far_not_after_near_raises(self):
        with pytest.raises(ValueError, match="far_settlement_date"):
            _fx_swap(far_settlement_date=date(2024, 1, 3))

    def test_same_currency_pair_raises(self):
        with pytest.raises(ValueError, match="must differ"):
            _fx_swap(foreign_currency="ZAR")

    def test_position_case_normalised(self):
        instrument = _fx_swap(position="SHORT_FOREIGN")
        assert instrument.position == "short_foreign"


class TestFXSwapPricing:
    def test_result_type(self):
        result = price_fx_swap(_fx_swap())
        assert isinstance(result, FXSwapPricingResult)

    def test_deterministic_canonical_case(self):
        instrument = _fx_swap(near_rate=18.27, far_rate=18.62)
        tau_near = accrual_fraction(
            instrument.valuation_date,
            instrument.near_settlement_date,
            instrument.day_count,
        )
        tau_far = accrual_fraction(
            instrument.valuation_date,
            instrument.far_settlement_date,
            instrument.day_count,
        )
        df_near = 1.0 / (1.0 + instrument.domestic_rate * tau_near)
        df_far = 1.0 / (1.0 + instrument.domestic_rate * tau_far)
        expected_near = instrument.notional_foreign * (instrument.spot_rate - instrument.near_rate) * df_near
        expected_far = instrument.notional_foreign * (instrument.far_rate - instrument.spot_rate) * df_far
        result = price_fx_swap(instrument)

        assert result.year_fraction_near == pytest.approx(tau_near, rel=1e-12)
        assert result.year_fraction_far == pytest.approx(tau_far, rel=1e-12)
        assert result.domestic_discount_factor_near == pytest.approx(df_near, rel=1e-12)
        assert result.domestic_discount_factor_far == pytest.approx(df_far, rel=1e-12)
        assert result.near_leg_value_domestic == pytest.approx(expected_near, rel=1e-12)
        assert result.far_leg_value_domestic == pytest.approx(expected_far, rel=1e-12)
        assert result.swap_points == pytest.approx(
            instrument.far_rate - instrument.near_rate,
            rel=1e-12,
        )
        assert result.present_value_domestic == pytest.approx(expected_near + expected_far, rel=1e-12)

    def test_par_swap_zero_points_and_zero_pv(self):
        instrument = _fx_swap(near_rate=18.25, far_rate=18.25)
        result = price_fx_swap(instrument)
        assert result.swap_points == pytest.approx(0.0, abs=1e-12)
        assert abs(result.present_value_domestic) < 1e-8

    def test_long_short_sign_flip(self):
        long_swap = _fx_swap(position="long_foreign")
        short_swap = _fx_swap(position="short_foreign")
        long_result = price_fx_swap(long_swap)
        short_result = price_fx_swap(short_swap)
        assert long_result.near_leg_value_domestic == pytest.approx(
            -short_result.near_leg_value_domestic,
            rel=1e-12,
        )
        assert long_result.far_leg_value_domestic == pytest.approx(
            -short_result.far_leg_value_domestic,
            rel=1e-12,
        )
        assert long_result.present_value_domestic == pytest.approx(
            -short_result.present_value_domestic,
            rel=1e-12,
        )

    def test_non_positive_discount_factor_fails_clearly(self):
        with pytest.raises(ValueError, match="far-leg domestic discount factor"):
            price_fx_swap(
                _fx_swap(
                    far_settlement_date=date(2026, 1, 1),
                    domestic_rate=-0.8,
                )
            )