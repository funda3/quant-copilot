"""
irs — Vanilla Interest Rate Swap instrument model.

A :class:`VanillaIRS` represents a plain fixed-for-floating swap in which one
leg pays a fixed coupon and the other leg pays a floating rate (IBOR).

This module contains only the *trade description* — no pricing logic.  Pricing
is handled by :mod:`quant_core.pricing.irs_pricer`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from quant_core.conventions.day_count import DayCount

_SUPPORTED_FREQUENCIES: frozenset[str] = frozenset(
    {"monthly", "quarterly", "semiannual", "annual"}
)
_SUPPORTED_PAY_RECEIVE: frozenset[str] = frozenset({"payer", "receiver"})


@dataclass
class VanillaIRS:
    """
    Plain vanilla fixed-for-floating interest rate swap.

    The instrument is described entirely by its trade economics; it carries no
    market data.  All string fields are normalised to lowercase on construction.

    Parameters
    ----------
    valuation_date : date
        As-of date for pricing (must be <= start_date).
    start_date : date
        Effective date of the swap (first accrual start).
    tenor_years : int
        Tenor in whole years (must be >= 1).
    notional : float
        Notional principal amount (must be > 0).
    fixed_rate : float
        Fixed coupon rate expressed as a decimal, e.g. 0.085 for 8.5%.
        Must be in the open interval (0, 1).
    payment_frequency : str
        Coupon frequency — one of ``"monthly"``, ``"quarterly"``,
        ``"semiannual"``, ``"annual"`` (case-insensitive).
    day_count : DayCount
        Day-count convention used for accrual fraction calculation on the
        fixed leg.
    pay_receive : str
        ``"payer"`` — pay fixed, receive float.
        ``"receiver"`` — receive fixed, pay float.

    Raises
    ------
    ValueError
        On any invalid field value (see validation rules in ``__post_init__``).
    """

    valuation_date: date
    start_date: date
    tenor_years: int
    notional: float
    fixed_rate: float
    payment_frequency: str
    day_count: DayCount
    pay_receive: str  # "payer" or "receiver"

    def __post_init__(self) -> None:
        # Normalise string fields before validation so callers may pass mixed-
        # case values (e.g. "Quarterly", "PAYER").
        self.payment_frequency = str(self.payment_frequency).lower()
        self.pay_receive = str(self.pay_receive).lower()

        if self.start_date < self.valuation_date:
            raise ValueError(
                f"start_date {self.start_date} must be >= valuation_date "
                f"{self.valuation_date}"
            )

        if self.notional <= 0.0:
            raise ValueError(
                f"notional must be > 0; got {self.notional}"
            )

        if not (0.0 < self.fixed_rate < 1.0):
            raise ValueError(
                f"fixed_rate must be in the open interval (0, 1); "
                f"got {self.fixed_rate}"
            )

        if self.tenor_years < 1:
            raise ValueError(
                f"tenor_years must be >= 1; got {self.tenor_years}"
            )

        if self.payment_frequency not in _SUPPORTED_FREQUENCIES:
            raise ValueError(
                f"payment_frequency {self.payment_frequency!r} is not supported. "
                f"Supported values: {sorted(_SUPPORTED_FREQUENCIES)}"
            )

        if self.pay_receive not in _SUPPORTED_PAY_RECEIVE:
            raise ValueError(
                f"pay_receive must be 'payer' or 'receiver'; "
                f"got {self.pay_receive!r}"
            )
