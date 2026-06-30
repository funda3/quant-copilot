"""
fx_option — Vanilla European deliverable FX option instrument model.

Quote convention
----------------
Spot and strike rates are quoted as domestic-currency units per one unit of
foreign currency. Example: ``ZAR/USD = 18.2500`` means 18.25 ZAR per 1 USD.

Option convention
-----------------
* ``call`` — right to buy foreign currency and sell domestic currency at the strike.
* ``put``  — right to sell foreign currency and buy domestic currency at the strike.

Position convention
-------------------
* ``long``  — owns the option and benefits from positive premium value.
* ``short`` — has written the option and carries the opposite sign.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from quant_core.conventions.day_count import DayCount

_SUPPORTED_OPTION_TYPES: frozenset[str] = frozenset({"call", "put"})
_SUPPORTED_POSITIONS: frozenset[str] = frozenset({"long", "short"})


@dataclass
class EuropeanFXOption:
    """Vanilla European deliverable FX option priced under Garman-Kohlhagen."""

    valuation_date: date
    expiry_date: date
    settlement_date: date
    spot_rate: float
    strike_rate: float
    domestic_rate: float
    foreign_rate: float
    volatility: float
    notional_foreign: float
    option_type: str
    position: str
    domestic_currency: str
    foreign_currency: str
    day_count: DayCount

    def __post_init__(self) -> None:
        self.option_type = str(self.option_type).lower()
        self.position = str(self.position).lower()
        self.domestic_currency = str(self.domestic_currency).upper()
        self.foreign_currency = str(self.foreign_currency).upper()

        if self.expiry_date <= self.valuation_date:
            raise ValueError(
                f"expiry_date {self.expiry_date} must be > valuation_date {self.valuation_date}"
            )
        if self.settlement_date < self.expiry_date:
            raise ValueError(
                "settlement_date "
                f"{self.settlement_date} must be >= expiry_date {self.expiry_date}"
            )
        if self.notional_foreign <= 0.0:
            raise ValueError(f"notional_foreign must be > 0; got {self.notional_foreign}")
        if self.spot_rate <= 0.0:
            raise ValueError(f"spot_rate must be > 0; got {self.spot_rate}")
        if self.strike_rate <= 0.0:
            raise ValueError(f"strike_rate must be > 0; got {self.strike_rate}")
        if self.volatility <= 0.0:
            raise ValueError(f"volatility must be > 0; got {self.volatility}")
        if self.domestic_currency == self.foreign_currency:
            raise ValueError(
                "domestic_currency and foreign_currency must differ; "
                f"got {self.domestic_currency}/{self.foreign_currency}"
            )
        if self.option_type not in _SUPPORTED_OPTION_TYPES:
            raise ValueError(
                "option_type must be 'call' or 'put'; "
                f"got {self.option_type!r}"
            )
        if self.position not in _SUPPORTED_POSITIONS:
            raise ValueError(
                "position must be 'long' or 'short'; "
                f"got {self.position!r}"
            )