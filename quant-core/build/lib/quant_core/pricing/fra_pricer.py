"""
fra_pricer — Deterministic FRA pricing off a discount curve.

Methodology
-----------
For an FRA covering the accrual period ``[start_date, end_date]`` with year
fraction ``tau`` under the FRA day-count convention:

1. Infer the simple forward rate from discount factors:

       F = (df(start) / df(end) - 1) / tau

2. Compute the undiscounted payoff at the payment date ``end_date``:

       payer    = notional * (forward_rate - contract_rate) * tau
       receiver = notional * (contract_rate - forward_rate) * tau

   where ``payer`` means pay fixed / receive floating and ``receiver`` means
   receive fixed / pay floating.

3. Discount that payoff back to ``valuation_date`` with ``df(end_date)``.

No interpolation hacks are introduced beyond the existing ``DiscountCurve``
behaviour. Out-of-domain curve errors are allowed to surface as ``ValueError``.
"""
from __future__ import annotations

from dataclasses import dataclass

from quant_core.conventions.day_count import accrual_fraction
from quant_core.curves.discount_curve import DiscountCurve
from quant_core.instruments.fra import FRA


@dataclass
class FRAPricingResult:
    """Deterministic FRA valuation outputs."""

    forward_rate: float
    year_fraction: float
    discount_factor_to_payment: float
    payoff_undiscounted: float
    pv: float


def price_fra(fra: FRA, curve: DiscountCurve) -> FRAPricingResult:
    """
    Price a deterministic FRA off a :class:`DiscountCurve`.

    Parameters
    ----------
    fra : FRA
        Fully specified FRA instrument.
    curve : DiscountCurve
        Discount curve used both to infer the forward rate and discount the
        payment at ``fra.end_date``.

    Returns
    -------
    FRAPricingResult
        Forward rate, accrual fraction, payment-date discount factor,
        undiscounted payoff, and present value.

    Raises
    ------
    ValueError
        If the FRA accrual year fraction is zero or negative, or if the curve
        cannot provide a discount factor for a required date.
    """
    year_fraction = accrual_fraction(fra.start_date, fra.end_date, fra.day_count)
    if year_fraction <= 0.0:
        raise ValueError(
            "FRA accrual year fraction must be > 0; check start_date, end_date, and day_count."
        )

    df_start = curve.df(fra.start_date)
    df_end = curve.df(fra.end_date)
    forward_rate = (df_start / df_end - 1.0) / year_fraction

    payoff_sign = 1.0 if fra.position == "payer" else -1.0
    payoff_undiscounted = (
        payoff_sign
        * fra.notional
        * (forward_rate - fra.contract_rate)
        * year_fraction
    )
    pv = payoff_undiscounted * df_end

    return FRAPricingResult(
        forward_rate=forward_rate,
        year_fraction=year_fraction,
        discount_factor_to_payment=df_end,
        payoff_undiscounted=payoff_undiscounted,
        pv=pv,
    )