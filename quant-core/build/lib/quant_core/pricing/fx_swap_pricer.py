"""
fx_swap_pricer — Deterministic FX swap pricing from flat domestic discounting.

Methodology
-----------
Let the quote convention be domestic-currency units per one unit of foreign
currency. For a deliverable FX swap with foreign notional ``N_for``:

1. Compute simple-rate domestic discount factors for the near and far dates:

       df_near = 1 / (1 + r_dom * t_near)
       df_far  = 1 / (1 + r_dom * t_far)

2. Express each settlement's foreign-versus-domestic exchange as a domestic
   value using the current spot rate as the domestic value of one foreign unit:

       near_domestic_value = sign * N_for * (spot - near_rate)
       far_domestic_value  = sign * N_for * (far_rate - spot)

   where ``sign = +1`` for ``long_foreign`` and ``-1`` for ``short_foreign``.

3. Discount each leg back to valuation date and sum the contributions.

This is a deliberately simple, deterministic institutional placeholder. It
does not model basis, collateral, or cross-currency discounting.
"""
from __future__ import annotations

from dataclasses import dataclass

from quant_core.conventions.day_count import accrual_fraction
from quant_core.instruments.fx_swap import FXSwap


@dataclass
class FXSwapPricingResult:
    """Deterministic FX swap valuation outputs in domestic currency."""

    year_fraction_near: float
    year_fraction_far: float
    domestic_discount_factor_near: float
    domestic_discount_factor_far: float
    near_leg_value_domestic: float
    far_leg_value_domestic: float
    swap_points: float
    present_value_domestic: float


def price_fx_swap(fx_swap: FXSwap) -> FXSwapPricingResult:
    """Price a deterministic deliverable FX swap using flat domestic discounting."""
    year_fraction_near = accrual_fraction(
        fx_swap.valuation_date,
        fx_swap.near_settlement_date,
        fx_swap.day_count,
    )
    year_fraction_far = accrual_fraction(
        fx_swap.valuation_date,
        fx_swap.far_settlement_date,
        fx_swap.day_count,
    )
    if year_fraction_near <= 0.0:
        raise ValueError(
            "FX swap near-leg year fraction must be > 0; check valuation_date, near_settlement_date, and day_count."
        )
    if year_fraction_far <= 0.0:
        raise ValueError(
            "FX swap far-leg year fraction must be > 0; check valuation_date, far_settlement_date, and day_count."
        )

    domestic_denominator_near = 1.0 + fx_swap.domestic_rate * year_fraction_near
    domestic_denominator_far = 1.0 + fx_swap.domestic_rate * year_fraction_far
    if domestic_denominator_near <= 0.0:
        raise ValueError(
            "domestic_rate implies a non-positive near-leg domestic discount factor under simple compounding."
        )
    if domestic_denominator_far <= 0.0:
        raise ValueError(
            "domestic_rate implies a non-positive far-leg domestic discount factor under simple compounding."
        )

    domestic_discount_factor_near = 1.0 / domestic_denominator_near
    domestic_discount_factor_far = 1.0 / domestic_denominator_far
    leg_sign = 1.0 if fx_swap.position == "long_foreign" else -1.0

    near_leg_value_domestic = (
        leg_sign
        * fx_swap.notional_foreign
        * (fx_swap.spot_rate - fx_swap.near_rate)
        * domestic_discount_factor_near
    )
    far_leg_value_domestic = (
        leg_sign
        * fx_swap.notional_foreign
        * (fx_swap.far_rate - fx_swap.spot_rate)
        * domestic_discount_factor_far
    )
    present_value_domestic = near_leg_value_domestic + far_leg_value_domestic

    return FXSwapPricingResult(
        year_fraction_near=year_fraction_near,
        year_fraction_far=year_fraction_far,
        domestic_discount_factor_near=domestic_discount_factor_near,
        domestic_discount_factor_far=domestic_discount_factor_far,
        near_leg_value_domestic=near_leg_value_domestic,
        far_leg_value_domestic=far_leg_value_domestic,
        swap_points=fx_swap.far_rate - fx_swap.near_rate,
        present_value_domestic=present_value_domestic,
    )