"""
bond — Fixed-rate bond instrument model.

A :class:`FixedRateBond` represents a plain fixed-coupon bond in which the
issuer pays a fixed coupon on a regular schedule and repays the face value
at maturity.

This module contains only the *trade description* — no pricing logic.  Pricing
is handled by :mod:`quant_core.pricing.bond_pricer`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from quant_core.conventions.day_count import DayCount

# Supported coupon frequencies for bonds.
# Note: monthly is excluded — standard bond markets use annual/semiannual/quarterly.
_SUPPORTED_FREQUENCIES: frozenset[str] = frozenset(
    {"annual", "quarterly", "semiannual"}
)


@dataclass
class FixedRateBond:
    """
    Plain fixed-rate (coupon) bond.

    The instrument is described entirely by its trade economics; it carries no
    market data.  The ``coupon_frequency`` field is normalised to lowercase on
    construction.

    Parameters
    ----------
    valuation_date : date
        As-of date for pricing.  Must be <= *maturity_date*.
    issue_date : date
        Date the bond was issued.  Defines the start of the first coupon
        accrual period.
    maturity_date : date
        Final redemption date.  Must be strictly after *issue_date*.
    face_value : float
        Par / notional amount repaid at maturity.  Must be > 0.
    coupon_rate : float
        Annual coupon rate expressed as a decimal, e.g. 0.05 for 5%.
        Must be in [0, 1).  Zero gives a zero-coupon bond.
    coupon_frequency : str
        Coupon payment frequency — one of ``"annual"``, ``"semiannual"``,
        ``"quarterly"`` (case-insensitive).
    day_count : DayCount
        Day-count convention used for coupon accrual fraction calculation.

    Raises
    ------
    ValueError
        On any invalid field value (see validation rules in ``__post_init__``).
    """

    valuation_date: date
    issue_date: date
    maturity_date: date
    face_value: float
    coupon_rate: float
    coupon_frequency: str
    day_count: DayCount

    def __post_init__(self) -> None:
        # Normalise string field before validation so callers may pass
        # mixed-case values (e.g. "Annual", "SEMIANNUAL").
        self.coupon_frequency = str(self.coupon_frequency).lower()

        if self.face_value <= 0.0:
            raise ValueError(
                f"face_value must be > 0; got {self.face_value}"
            )

        if not (0.0 <= self.coupon_rate < 1.0):
            raise ValueError(
                f"coupon_rate must be >= 0 and < 1; got {self.coupon_rate}"
            )

        if self.maturity_date <= self.issue_date:
            raise ValueError(
                f"maturity_date {self.maturity_date} must be > issue_date "
                f"{self.issue_date}"
            )

        if self.valuation_date > self.maturity_date:
            raise ValueError(
                f"valuation_date {self.valuation_date} must be <= "
                f"maturity_date {self.maturity_date}"
            )

        if self.coupon_frequency not in _SUPPORTED_FREQUENCIES:
            raise ValueError(
                f"coupon_frequency {self.coupon_frequency!r} is not supported. "
                f"Supported values: {sorted(_SUPPORTED_FREQUENCIES)}"
            )
