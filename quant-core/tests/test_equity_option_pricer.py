from __future__ import annotations

from datetime import date
from math import erf, exp, log, pi, sqrt

import pytest

from quant_core.conventions.day_count import DayCount, accrual_fraction
from quant_core.instruments.equity_option import EuropeanEquityOption
from quant_core.pricing.equity_option_pricer import (
    EuropeanEquityOptionPricingResult,
    price_european_equity_option,
)


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _normal_pdf(x: float) -> float:
    return exp(-0.5 * x * x) / sqrt(2.0 * pi)


def _equity_option(**overrides) -> EuropeanEquityOption:
    defaults = dict(
        valuation_date=date(2024, 1, 1),
        expiry_date=date(2024, 7, 1),
        spot_price=100.0,
        strike_price=105.0,
        risk_free_rate=0.05,
        dividend_yield=0.02,
        volatility=0.25,
        quantity_shares=1_000.0,
        option_type="call",
        position="long",
        currency="USD",
        underlying_name="ACME",
        day_count=DayCount.ACT_365F,
    )
    defaults.update(overrides)
    return EuropeanEquityOption(**defaults)


class TestEuropeanEquityOptionConstruction:
    def test_expiry_not_after_valuation_raises(self):
        with pytest.raises(ValueError, match="expiry_date"):
            _equity_option(expiry_date=date(2024, 1, 1))

    def test_non_positive_quantity_raises(self):
        with pytest.raises(ValueError, match="quantity_shares"):
            _equity_option(quantity_shares=0.0)

    def test_option_type_and_position_are_normalised(self):
        instrument = _equity_option(option_type="PUT", position="SHORT")
        assert instrument.option_type == "put"
        assert instrument.position == "short"


class TestEuropeanEquityOptionPricing:
    def test_result_type(self):
        result = price_european_equity_option(_equity_option())
        assert isinstance(result, EuropeanEquityOptionPricingResult)

    def test_deterministic_call_case(self):
        instrument = _equity_option()
        tau = accrual_fraction(
            instrument.valuation_date,
            instrument.expiry_date,
            instrument.day_count,
        )
        df = exp(-instrument.risk_free_rate * tau)
        carry_df = exp(-instrument.dividend_yield * tau)
        forward = instrument.spot_price * carry_df / df
        sigma_root_t = instrument.volatility * sqrt(tau)
        d1 = (log(forward / instrument.strike_price) + 0.5 * instrument.volatility**2 * tau) / sigma_root_t
        d2 = d1 - sigma_root_t
        premium_unit = (
            instrument.spot_price * carry_df * _normal_cdf(d1)
            - instrument.strike_price * df * _normal_cdf(d2)
        )
        delta_unit = carry_df * _normal_cdf(d1)
        gamma_unit = carry_df * _normal_pdf(d1) / (instrument.spot_price * sigma_root_t)
        vega_unit = instrument.spot_price * carry_df * _normal_pdf(d1) * sqrt(tau)

        result = price_european_equity_option(instrument)

        assert result.year_fraction == pytest.approx(tau, rel=1e-12)
        assert result.discount_factor == pytest.approx(df, rel=1e-12)
        assert result.dividend_discount_factor == pytest.approx(carry_df, rel=1e-12)
        assert result.forward_price == pytest.approx(forward, rel=1e-12)
        assert result.premium == pytest.approx(instrument.quantity_shares * premium_unit, rel=1e-12)
        assert result.delta == pytest.approx(instrument.quantity_shares * delta_unit, rel=1e-12)
        assert result.gamma == pytest.approx(instrument.quantity_shares * gamma_unit, rel=1e-12)
        assert result.vega == pytest.approx(instrument.quantity_shares * vega_unit, rel=1e-12)

    def test_put_call_parity_holds_for_long_positions(self):
        call = price_european_equity_option(_equity_option(option_type="call"))
        put = price_european_equity_option(_equity_option(option_type="put"))
        instrument = _equity_option()
        parity_rhs = instrument.quantity_shares * (
            instrument.spot_price * call.dividend_discount_factor
            - instrument.strike_price * call.discount_factor
        )
        assert call.premium - put.premium == pytest.approx(parity_rhs, rel=1e-12)

    def test_long_short_sign_flip(self):
        long_result = price_european_equity_option(_equity_option(position="long"))
        short_result = price_european_equity_option(_equity_option(position="short"))
        assert long_result.premium == pytest.approx(-short_result.premium, rel=1e-12)
        assert long_result.delta == pytest.approx(-short_result.delta, rel=1e-12)
        assert long_result.gamma == pytest.approx(-short_result.gamma, rel=1e-12)
        assert long_result.vega == pytest.approx(-short_result.vega, rel=1e-12)

    def test_dividend_yield_reduces_call_forward_and_price(self):
        no_dividend = price_european_equity_option(_equity_option(dividend_yield=0.0))
        high_dividend = price_european_equity_option(_equity_option(dividend_yield=0.08))
        assert high_dividend.forward_price < no_dividend.forward_price
        assert high_dividend.premium < no_dividend.premium