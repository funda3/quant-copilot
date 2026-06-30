"""
fx_forward_pricer — Deterministic FX forward pricing from flat simple rates.

Methodology
-----------
Let the quote convention be domestic-currency units per one unit of foreign
currency. For a maturity year fraction ``tau``:

1. Compute simple-rate discount factors:

       df_dom = 1 / (1 + r_dom * tau)
       df_for = 1 / (1 + r_for * tau)

2. Infer the implied forward rate from covered interest parity:

       F = S * df_for / df_dom

3. Value the contract in domestic currency:

       long_foreign  PV = N_for * (F - K) * df_dom
       short_foreign PV = N_for * (K - F) * df_dom

where ``N_for`` is the foreign-currency notional, ``S`` is spot, and ``K`` is
the contract forward rate.
"""
from __future__ import annotations

from dataclasses import dataclass

from quant_core.conventions.day_count import accrual_fraction
from quant_core.instruments.fx_forward import FXForward


@dataclass
class FXForwardPricingResult:
    """Deterministic FX forward valuation outputs in domestic currency."""

    year_fraction: float
    domestic_discount_factor: float
    foreign_discount_factor: float
    implied_forward_rate: float
    forward_points: float
    payoff_undiscounted_domestic: float
    present_value_domestic: float


def price_fx_forward(fx_forward: FXForward) -> FXForwardPricingResult:
    """Price a deterministic FX forward using flat simple domestic and foreign rates."""
    year_fraction = accrual_fraction(
        fx_forward.valuation_date,
        fx_forward.maturity_date,
        fx_forward.day_count,
    )
    if year_fraction <= 0.0:
        raise ValueError(
            "FX forward year fraction must be > 0; check valuation_date, maturity_date, and day_count."
        )

    domestic_denominator = 1.0 + fx_forward.domestic_rate * year_fraction
    foreign_denominator = 1.0 + fx_forward.foreign_rate * year_fraction
    if domestic_denominator <= 0.0:
        raise ValueError(
            "domestic_rate implies a non-positive domestic discount factor under simple compounding."
        )
    if foreign_denominator <= 0.0:
        raise ValueError(
            "foreign_rate implies a non-positive foreign discount factor under simple compounding."
        )

    domestic_discount_factor = 1.0 / domestic_denominator
    foreign_discount_factor = 1.0 / foreign_denominator
    implied_forward_rate = (
        fx_forward.spot_rate * foreign_discount_factor / domestic_discount_factor
    )
    forward_points = implied_forward_rate - fx_forward.spot_rate

    payoff_sign = 1.0 if fx_forward.position == "long_foreign" else -1.0
    payoff_undiscounted_domestic = payoff_sign * fx_forward.notional_foreign * (
        implied_forward_rate - fx_forward.contract_forward_rate
    )
    present_value_domestic = (
        payoff_undiscounted_domestic * domestic_discount_factor
    )

    return FXForwardPricingResult(
        year_fraction=year_fraction,
        domestic_discount_factor=domestic_discount_factor,
        foreign_discount_factor=foreign_discount_factor,
        implied_forward_rate=implied_forward_rate,
        forward_points=forward_points,
        payoff_undiscounted_domestic=payoff_undiscounted_domestic,
        present_value_domestic=present_value_domestic,
    )