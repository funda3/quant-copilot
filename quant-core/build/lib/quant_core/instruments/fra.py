"""
fra — Forward Rate Agreement instrument model.

A :class:`FRA` represents a deterministic single-period forward rate agreement.
The instrument captures only the trade economics; pricing is implemented in
:mod:`quant_core.pricing.fra_pricer`.

Sign convention
---------------
* ``payer``    — pay fixed contract rate, receive floating forward rate.
* ``receiver`` — receive fixed contract rate, pay floating forward rate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from quant_core.conventions.day_count import DayCount

_SUPPORTED_POSITIONS: frozenset[str] = frozenset({"payer", "receiver"})


@dataclass
class FRA:
    """
    Deterministic forward rate agreement.

    Parameters
    ----------
    valuation_date : date
        As-of date for pricing. Must be strictly before ``start_date``.
    start_date : date
        FRA accrual start date. Must be strictly after ``valuation_date``.
    end_date : date
        FRA accrual end / payment date. Must be strictly after ``start_date``.
    notional : float
        Contract notional. Must be strictly positive.
    contract_rate : float
        Fixed FRA contract rate as a decimal. Must satisfy ``0 <= rate < 1``.
    day_count : DayCount
        Day-count convention used for the accrual year fraction.
    position : str
        ``payer`` means pay fixed / receive floating.
        ``receiver`` means receive fixed / pay floating.
    """

    valuation_date: date
    start_date: date
    end_date: date
    notional: float
    contract_rate: float
    day_count: DayCount
    position: str

    def __post_init__(self) -> None:
        self.position = str(self.position).lower()

        if self.start_date <= self.valuation_date:
            raise ValueError(
                f"start_date {self.start_date} must be > valuation_date {self.valuation_date}"
            )

        if self.end_date <= self.start_date:
            raise ValueError(
                f"end_date {self.end_date} must be > start_date {self.start_date}"
            )

        if self.notional <= 0.0:
            raise ValueError(f"notional must be > 0; got {self.notional}")

        if not (0.0 <= self.contract_rate < 1.0):
            raise ValueError(
                f"contract_rate must be >= 0 and < 1; got {self.contract_rate}"
            )

        if self.position not in _SUPPORTED_POSITIONS:
            raise ValueError(
                f"position must be 'payer' or 'receiver'; got {self.position!r}"
            )