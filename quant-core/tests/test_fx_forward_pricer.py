from __future__ import annotations

from datetime import date

import pytest

from quant_core.conventions.day_count import DayCount, accrual_fraction
from quant_core.instruments.fx_forward import FXForward
from quant_core.pricing.fx_forward_pricer import FXForwardPricingResult, price_fx_forward


def _fx_forward(**overrides) -> FXForward:
    defaults = dict(
        valuation_date=date(2024, 1, 1),
        maturity_date=date(2024, 7, 1),
        notional_foreign=1_000_000.0,
        spot_rate=18.25,
        contract_forward_rate=18.60,
        domestic_rate=0.08,
        foreign_rate=0.05,
        domestic_currency="ZAR",
        foreign_currency="USD",
        day_count=DayCount.ACT_365F,
        position="long_foreign",
    )
    defaults.update(overrides)
    return FXForward(**defaults)


class TestFXForwardConstruction:
    def test_maturity_not_after_valuation_raises(self):
        with pytest.raises(ValueError, match="maturity_date"):
            _fx_forward(maturity_date=date(2024, 1, 1))

    def test_same_currency_pair_raises(self):
        with pytest.raises(ValueError, match="must differ"):
            _fx_forward(domestic_currency="USD", foreign_currency="USD")

    def test_invalid_position_raises(self):
        with pytest.raises(ValueError, match="position"):
            _fx_forward(position="long")

    def test_position_case_normalised(self):
        fx_forward = _fx_forward(position="SHORT_FOREIGN")
        assert fx_forward.position == "short_foreign"


class TestFXForwardPricing:
    def test_result_type(self):
        result = price_fx_forward(_fx_forward())
        assert isinstance(result, FXForwardPricingResult)

    def test_deterministic_canonical_case(self):
        fx_forward = _fx_forward(contract_forward_rate=18.50)
        tau = accrual_fraction(
            fx_forward.valuation_date,
            fx_forward.maturity_date,
            fx_forward.day_count,
        )
        domestic_df = 1.0 / (1.0 + fx_forward.domestic_rate * tau)
        foreign_df = 1.0 / (1.0 + fx_forward.foreign_rate * tau)
        implied_forward = fx_forward.spot_rate * foreign_df / domestic_df
        expected_payoff = fx_forward.notional_foreign * (
            implied_forward - fx_forward.contract_forward_rate
        )
        expected_pv = expected_payoff * domestic_df

        result = price_fx_forward(fx_forward)

        assert result.year_fraction == pytest.approx(tau, rel=1e-12)
        assert result.domestic_discount_factor == pytest.approx(domestic_df, rel=1e-12)
        assert result.foreign_discount_factor == pytest.approx(foreign_df, rel=1e-12)
        assert result.implied_forward_rate == pytest.approx(implied_forward, rel=1e-12)
        assert result.forward_points == pytest.approx(
            implied_forward - fx_forward.spot_rate,
            rel=1e-12,
        )
        assert result.payoff_undiscounted_domestic == pytest.approx(expected_payoff, rel=1e-12)
        assert result.present_value_domestic == pytest.approx(expected_pv, rel=1e-12)

    def test_par_forward_gives_pv_near_zero(self):
        base = _fx_forward()
        par_rate = price_fx_forward(base).implied_forward_rate
        par_contract = _fx_forward(contract_forward_rate=par_rate)
        result = price_fx_forward(par_contract)
        assert abs(result.present_value_domestic) < 1e-8

    def test_long_short_sign_flip(self):
        long_foreign = _fx_forward(contract_forward_rate=18.50, position="long_foreign")
        short_foreign = _fx_forward(contract_forward_rate=18.50, position="short_foreign")
        long_result = price_fx_forward(long_foreign)
        short_result = price_fx_forward(short_foreign)
        assert long_result.payoff_undiscounted_domestic == pytest.approx(
            -short_result.payoff_undiscounted_domestic,
            rel=1e-12,
        )
        assert long_result.present_value_domestic == pytest.approx(
            -short_result.present_value_domestic,
            rel=1e-12,
        )

    def test_non_positive_discount_factor_fails_clearly(self):
        with pytest.raises(ValueError, match="domestic discount factor"):
            price_fx_forward(
                _fx_forward(
                    maturity_date=date(2026, 1, 1),
                    domestic_rate=-0.8,
                )
            )