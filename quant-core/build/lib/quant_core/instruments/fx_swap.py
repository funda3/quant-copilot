"""
fx_swap — Deterministic deliverable FX swap instrument model.

Quote convention
----------------
Near and far FX rates are quoted as domestic-currency units per one unit of
foreign currency. Example: ``ZAR/USD = 18.2500`` means 18.25 ZAR per 1 USD.

Sign convention
---------------
* ``long_foreign``  — receive foreign / pay domestic on the near leg, then
  pay foreign / receive domestic on the far leg.
* ``short_foreign`` — pay foreign / receive domestic on the near leg, then
  receive foreign / pay domestic on the far leg.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from quant_core.conventions.day_count import DayCount

_SUPPORTED_POSITIONS: frozenset[str] = frozenset({"long_foreign", "short_foreign"})


@dataclass
class FXSwap:
    """Deterministic fixed-fixed deliverable FX swap."""

    valuation_date: date
    near_settlement_date: date
    far_settlement_date: date
    spot_rate: float
    near_rate: float
    far_rate: float
    notional_foreign: float
    domestic_currency: str
    foreign_currency: str
    domestic_rate: float
    day_count: DayCount
    position: str

    def __post_init__(self) -> None:
        self.domestic_currency = str(self.domestic_currency).upper()
        self.foreign_currency = str(self.foreign_currency).upper()
        self.position = str(self.position).lower()

        if self.near_settlement_date <= self.valuation_date:
            raise ValueError(
                "near_settlement_date "
                f"{self.near_settlement_date} must be > valuation_date {self.valuation_date}"
            )
        if self.far_settlement_date <= self.near_settlement_date:
            raise ValueError(
                "far_settlement_date "
                f"{self.far_settlement_date} must be > near_settlement_date {self.near_settlement_date}"
            )
        if self.notional_foreign <= 0.0:
            raise ValueError(f"notional_foreign must be > 0; got {self.notional_foreign}")
        if self.spot_rate <= 0.0:
            raise ValueError(f"spot_rate must be > 0; got {self.spot_rate}")
        if self.near_rate <= 0.0:
            raise ValueError(f"near_rate must be > 0; got {self.near_rate}")
        if self.far_rate <= 0.0:
            raise ValueError(f"far_rate must be > 0; got {self.far_rate}")
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