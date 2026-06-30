from __future__ import annotations

from datetime import date
from math import erf, exp, log, pi, sqrt

import pytest

from quant_core.conventions.day_count import DayCount, accrual_fraction
from quant_core.instruments.fx_option import EuropeanFXOption
from quant_core.pricing.fx_option_pricer import (
    EuropeanFXOptionPricingResult,
    price_european_fx_option,
)


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _normal_pdf(x: float) -> float:
    return exp(-0.5 * x * x) / sqrt(2.0 * pi)


def _fx_option(**overrides) -> EuropeanFXOption:
    defaults = dict(
        valuation_date=date(2024, 1, 1),
        expiry_date=date(2024, 7, 1),
        settlement_date=date(2024, 7, 1),
        spot_rate=18.25,
        strike_rate=18.40,
        domestic_rate=0.08,
        foreign_rate=0.05,
        volatility=0.18,
        notional_foreign=1_000_000.0,
        option_type="call",
        position="long",
        domestic_currency="ZAR",
        foreign_currency="USD",
        day_count=DayCount.ACT_365F,
    )
    defaults.update(overrides)
    return EuropeanFXOption(**defaults)


class TestEuropeanFXOptionConstruction:
    def test_expiry_not_after_valuation_raises(self):
        with pytest.raises(ValueError, match="expiry_date"):
            _fx_option(expiry_date=date(2024, 1, 1))

    def test_settlement_before_expiry_raises(self):
        with pytest.raises(ValueError, match="settlement_date"):
            _fx_option(settlement_date=date(2024, 6, 30))

    def test_same_currency_pair_raises(self):
        with pytest.raises(ValueError, match="must differ"):
            _fx_option(foreign_currency="ZAR")

    def test_option_type_and_position_are_normalised(self):
        instrument = _fx_option(option_type="PUT", position="SHORT")
        assert instrument.option_type == "put"
        assert instrument.position == "short"


class TestEuropeanFXOptionPricing:
    def test_result_type(self):
        result = price_european_fx_option(_fx_option())
        assert isinstance(result, EuropeanFXOptionPricingResult)

    def test_deterministic_call_case(self):
        instrument = _fx_option()
        tau = accrual_fraction(
            instrument.valuation_date,
            instrument.expiry_date,
            instrument.day_count,
        )
        settle_tau = accrual_fraction(
            instrument.valuation_date,
            instrument.settlement_date,
            instrument.day_count,
        )
        df_dom = exp(-instrument.domestic_rate * settle_tau)
        df_for = exp(-instrument.foreign_rate * settle_tau)
        forward = instrument.spot_rate * df_for / df_dom
        sigma_root_t = instrument.volatility * sqrt(tau)
        d1 = (log(forward / instrument.strike_rate) + 0.5 * instrument.volatility**2 * tau) / sigma_root_t
        d2 = d1 - sigma_root_t
        premium_unit = df_dom * (forward * _normal_cdf(d1) - instrument.strike_rate * _normal_cdf(d2))
        delta_unit = df_for * _normal_cdf(d1)
        gamma_unit = df_for * _normal_pdf(d1) / (instrument.spot_rate * sigma_root_t)
        vega_unit = instrument.spot_rate * df_for * _normal_pdf(d1) * sqrt(tau)

        result = price_european_fx_option(instrument)

        assert result.year_fraction == pytest.approx(tau, rel=1e-12)
        assert result.settlement_year_fraction == pytest.approx(settle_tau, rel=1e-12)
        assert result.domestic_discount_factor == pytest.approx(df_dom, rel=1e-12)
        assert result.foreign_discount_factor == pytest.approx(df_for, rel=1e-12)
        assert result.forward_rate == pytest.approx(forward, rel=1e-12)
        assert result.premium_domestic == pytest.approx(
            instrument.notional_foreign * premium_unit,
            rel=1e-12,
        )
        assert result.premium_foreign == pytest.approx(
            result.premium_domestic / instrument.spot_rate,
            rel=1e-12,
        )
        assert result.delta == pytest.approx(instrument.notional_foreign * delta_unit, rel=1e-12)
        assert result.gamma == pytest.approx(instrument.notional_foreign * gamma_unit, rel=1e-12)
        assert result.vega == pytest.approx(instrument.notional_foreign * vega_unit, rel=1e-12)

    def test_put_call_parity_holds_for_long_positions(self):
        call = price_european_fx_option(_fx_option(option_type="call"))
        put = price_european_fx_option(_fx_option(option_type="put"))
        instrument = _fx_option()
        parity_rhs = instrument.notional_foreign * (
            instrument.spot_rate * call.foreign_discount_factor
            - instrument.strike_rate * call.domestic_discount_factor
        )
        assert call.premium_domestic - put.premium_domestic == pytest.approx(
            parity_rhs,
            rel=1e-12,
        )

    def test_long_short_sign_flip(self):
        long_result = price_european_fx_option(_fx_option(position="long"))
        short_result = price_european_fx_option(_fx_option(position="short"))
        assert long_result.premium_domestic == pytest.approx(-short_result.premium_domestic, rel=1e-12)
        assert long_result.premium_foreign == pytest.approx(-short_result.premium_foreign, rel=1e-12)
        assert long_result.delta == pytest.approx(-short_result.delta, rel=1e-12)
        assert long_result.gamma == pytest.approx(-short_result.gamma, rel=1e-12)
        assert long_result.vega == pytest.approx(-short_result.vega, rel=1e-12)

    def test_deferred_settlement_changes_discounting_but_not_breaks_pricing(self):
        same_day = price_european_fx_option(_fx_option(settlement_date=date(2024, 7, 1)))
        deferred = price_european_fx_option(_fx_option(settlement_date=date(2024, 7, 3)))
        assert deferred.settlement_year_fraction > same_day.settlement_year_fraction
        assert deferred.domestic_discount_factor < same_day.domestic_discount_factor
        assert deferred.foreign_discount_factor < same_day.foreign_discount_factor