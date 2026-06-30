"""
equity_option_pricer — European equity option pricing under Black-Scholes-Merton.

Methodology
-----------
Under flat continuously compounded risk-free rate ``r`` and continuous
dividend yield ``q``:

1. Discount factors and forward price:

       df = exp(-r t)
       carry_df = exp(-q t)
       F = S * carry_df / df

2. Black-Scholes-Merton option value per share:

       call = S e^{-q t} N(d1) - K e^{-r t} N(d2)
       put  = K e^{-r t} N(-d2) - S e^{-q t} N(-d1)

3. Greeks are scaled by ``quantity_shares`` and sign-adjusted by position.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import erf, exp, log, pi, sqrt

from quant_core.conventions.day_count import accrual_fraction
from quant_core.instruments.equity_option import EuropeanEquityOption


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _normal_pdf(x: float) -> float:
    return exp(-0.5 * x * x) / sqrt(2.0 * pi)


@dataclass
class EuropeanEquityOptionPricingResult:
    """European equity option valuation outputs in premium currency."""

    year_fraction: float
    discount_factor: float
    dividend_discount_factor: float
    forward_price: float
    premium: float
    delta: float
    gamma: float
    vega: float


def price_european_equity_option(
    option: EuropeanEquityOption,
) -> EuropeanEquityOptionPricingResult:
    """Price a European equity option using Black-Scholes-Merton."""
    year_fraction = accrual_fraction(
        option.valuation_date,
        option.expiry_date,
        option.day_count,
    )
    if year_fraction <= 0.0:
        raise ValueError(
            "Equity option year fraction must be > 0; check valuation_date, expiry_date, and day_count."
        )

    discount_factor = exp(-option.risk_free_rate * year_fraction)
    dividend_discount_factor = exp(-option.dividend_yield * year_fraction)
    forward_price = option.spot_price * dividend_discount_factor / discount_factor

    sigma_root_t = option.volatility * sqrt(year_fraction)
    if sigma_root_t <= 0.0:
        raise ValueError("volatility and expiry year fraction must imply sigma * sqrt(t) > 0.")

    d1 = (
        log(forward_price / option.strike_price)
        + 0.5 * option.volatility**2 * year_fraction
    ) / sigma_root_t
    d2 = d1 - sigma_root_t
    pdf_d1 = _normal_pdf(d1)

    position_sign = 1.0 if option.position == "long" else -1.0

    if option.option_type == "call":
        premium_unit = (
            option.spot_price * dividend_discount_factor * _normal_cdf(d1)
            - option.strike_price * discount_factor * _normal_cdf(d2)
        )
        delta_unit = dividend_discount_factor * _normal_cdf(d1)
    else:
        premium_unit = (
            option.strike_price * discount_factor * _normal_cdf(-d2)
            - option.spot_price * dividend_discount_factor * _normal_cdf(-d1)
        )
        delta_unit = dividend_discount_factor * (_normal_cdf(d1) - 1.0)

    gamma_unit = dividend_discount_factor * pdf_d1 / (
        option.spot_price * sigma_root_t
    )
    vega_unit = (
        option.spot_price
        * dividend_discount_factor
        * pdf_d1
        * sqrt(year_fraction)
    )

    premium = position_sign * option.quantity_shares * premium_unit
    delta = position_sign * option.quantity_shares * delta_unit
    gamma = position_sign * option.quantity_shares * gamma_unit
    vega = position_sign * option.quantity_shares * vega_unit

    return EuropeanEquityOptionPricingResult(
        year_fraction=year_fraction,
        discount_factor=discount_factor,
        dividend_discount_factor=dividend_discount_factor,
        forward_price=forward_price,
        premium=premium,
        delta=delta,
        gamma=gamma,
        vega=vega,
    )