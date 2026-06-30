"""
equity_option — Vanilla European equity option instrument model.

Option convention
-----------------
* ``call`` — right to buy the underlying equity at the strike on expiry.
* ``put``  — right to sell the underlying equity at the strike on expiry.

Quantity convention
-------------------
``quantity_shares`` is the number of underlying shares on which premium and
Greeks are scaled.

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
class EuropeanEquityOption:
    """Vanilla European equity option priced under Black-Scholes-Merton."""

    valuation_date: date
    expiry_date: date
    spot_price: float
    strike_price: float
    risk_free_rate: float
    dividend_yield: float
    volatility: float
    quantity_shares: float
    option_type: str
    position: str
    currency: str
    day_count: DayCount
    underlying_name: str | None = None

    def __post_init__(self) -> None:
        self.option_type = str(self.option_type).lower()
        self.position = str(self.position).lower()
        self.currency = str(self.currency).upper()
        self.underlying_name = (
            None if self.underlying_name is None else str(self.underlying_name).strip()
        )

        if self.expiry_date <= self.valuation_date:
            raise ValueError(
                f"expiry_date {self.expiry_date} must be > valuation_date {self.valuation_date}"
            )
        if self.spot_price <= 0.0:
            raise ValueError(f"spot_price must be > 0; got {self.spot_price}")
        if self.strike_price <= 0.0:
            raise ValueError(f"strike_price must be > 0; got {self.strike_price}")
        if self.volatility <= 0.0:
            raise ValueError(f"volatility must be > 0; got {self.volatility}")
        if self.quantity_shares <= 0.0:
            raise ValueError(f"quantity_shares must be > 0; got {self.quantity_shares}")
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