"""
fx_forward — Deterministic FX forward instrument model.

Quote convention
----------------
Spot and forward rates are quoted as domestic-currency units per one unit of
foreign currency. Example: ``ZAR/USD = 18.2500`` means 18.25 ZAR per 1 USD.

Sign convention
---------------
* ``long_foreign``  — buy foreign currency / sell domestic currency at maturity.
* ``short_foreign`` — sell foreign currency / buy domestic currency at maturity.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from quant_core.conventions.day_count import DayCount

_SUPPORTED_POSITIONS: frozenset[str] = frozenset({"long_foreign", "short_foreign"})


@dataclass
class FXForward:
    """Deterministic FX forward contract priced from flat simple rates."""

    valuation_date: date
    maturity_date: date
    notional_foreign: float
    spot_rate: float
    contract_forward_rate: float
    domestic_rate: float
    foreign_rate: float
    domestic_currency: str
    foreign_currency: str
    day_count: DayCount
    position: str

    def __post_init__(self) -> None:
        self.domestic_currency = str(self.domestic_currency).upper()
        self.foreign_currency = str(self.foreign_currency).upper()
        self.position = str(self.position).lower()

        if self.maturity_date <= self.valuation_date:
            raise ValueError(
                f"maturity_date {self.maturity_date} must be > valuation_date {self.valuation_date}"
            )

        if self.notional_foreign <= 0.0:
            raise ValueError(f"notional_foreign must be > 0; got {self.notional_foreign}")

        if self.spot_rate <= 0.0:
            raise ValueError(f"spot_rate must be > 0; got {self.spot_rate}")

        if self.contract_forward_rate <= 0.0:
            raise ValueError(
                "contract_forward_rate must be > 0; "
                f"got {self.contract_forward_rate}"
            )

        if self.domestic_currency == self.foreign_currency:
            raise ValueError(
                "domestic_currency and foreign_currency must differ; "
                f"got {self.domestic_currency}/{self.foreign_currency}"
            )

        if self.position not in _SUPPORTED_POSITIONS:
            raise ValueError(
                "position must be 'long_foreign' or 'short_foreign'; "
                f"got {self.position!r}"
            )