"""
fx_option_pricer — European FX option pricing under Garman-Kohlhagen.

Methodology
-----------
The option is quoted on the FX rate expressed as domestic-currency units per
one unit of foreign currency. Under flat continuously compounded domestic and
foreign rates, the model uses:

1. Discount factors to settlement:

       df_dom = exp(-r_dom * t_settle)
       df_for = exp(-r_for * t_settle)

2. Forward rate to settlement:

       F = S * df_for / df_dom

3. Garman-Kohlhagen option value per unit of foreign notional:

       call = df_dom * (F N(d1) - K N(d2))
       put  = df_dom * (K N(-d2) - F N(-d1))

   with

       d1 = (ln(F / K) + 0.5 sigma^2 t_exp) / (sigma sqrt(t_exp))
       d2 = d1 - sigma sqrt(t_exp)

Greeks are reported in domestic-currency PV terms for the full foreign notional.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import erf, exp, log, pi, sqrt

from quant_core.conventions.day_count import accrual_fraction
from quant_core.instruments.fx_option import EuropeanFXOption


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _normal_pdf(x: float) -> float:
    return exp(-0.5 * x * x) / sqrt(2.0 * pi)


@dataclass
class EuropeanFXOptionPricingResult:
    """European FX option valuation outputs in domestic currency."""

    year_fraction: float
    settlement_year_fraction: float
    domestic_discount_factor: float
    foreign_discount_factor: float
    forward_rate: float
    premium_domestic: float
    premium_foreign: float
    delta: float
    gamma: float
    vega: float


def price_european_fx_option(option: EuropeanFXOption) -> EuropeanFXOptionPricingResult:
    """Price a European deliverable FX option using Garman-Kohlhagen."""
    year_fraction = accrual_fraction(
        option.valuation_date,
        option.expiry_date,
        option.day_count,
    )
    settlement_year_fraction = accrual_fraction(
        option.valuation_date,
        option.settlement_date,
        option.day_count,
    )
    if year_fraction <= 0.0:
        raise ValueError(
            "FX option expiry year fraction must be > 0; check valuation_date, expiry_date, and day_count."
        )
    if settlement_year_fraction <= 0.0:
        raise ValueError(
            "FX option settlement year fraction must be > 0; check valuation_date, settlement_date, and day_count."
        )

    domestic_discount_factor = exp(-option.domestic_rate * settlement_year_fraction)
    foreign_discount_factor = exp(-option.foreign_rate * settlement_year_fraction)
    forward_rate = option.spot_rate * foreign_discount_factor / domestic_discount_factor

    sigma_root_t = option.volatility * sqrt(year_fraction)
    if sigma_root_t <= 0.0:
        raise ValueError("volatility and expiry year fraction must imply sigma * sqrt(t) > 0.")

    d1 = (log(forward_rate / option.strike_rate) + 0.5 * option.volatility**2 * year_fraction) / sigma_root_t
    d2 = d1 - sigma_root_t
    pdf_d1 = _normal_pdf(d1)

    position_sign = 1.0 if option.position == "long" else -1.0

    if option.option_type == "call":
        premium_unit_domestic = domestic_discount_factor * (
            forward_rate * _normal_cdf(d1) - option.strike_rate * _normal_cdf(d2)
        )
        delta_unit = foreign_discount_factor * _normal_cdf(d1)
    else:
        premium_unit_domestic = domestic_discount_factor * (
            option.strike_rate * _normal_cdf(-d2) - forward_rate * _normal_cdf(-d1)
        )
        delta_unit = foreign_discount_factor * (_normal_cdf(d1) - 1.0)

    gamma_unit = foreign_discount_factor * pdf_d1 / (option.spot_rate * sigma_root_t)
    vega_unit = option.spot_rate * foreign_discount_factor * pdf_d1 * sqrt(year_fraction)

    premium_domestic = position_sign * option.notional_foreign * premium_unit_domestic
    premium_foreign = premium_domestic / option.spot_rate
    delta = position_sign * option.notional_foreign * delta_unit
    gamma = position_sign * option.notional_foreign * gamma_unit
    vega = position_sign * option.notional_foreign * vega_unit

    return EuropeanFXOptionPricingResult(
        year_fraction=year_fraction,
        settlement_year_fraction=settlement_year_fraction,
        domestic_discount_factor=domestic_discount_factor,
        foreign_discount_factor=foreign_discount_factor,
        forward_rate=forward_rate,
        premium_domestic=premium_domestic,
        premium_foreign=premium_foreign,
        delta=delta,
        gamma=gamma,
        vega=vega,
    )