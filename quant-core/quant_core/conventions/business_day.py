"""
business_day — Business-day conventions (BDC) enum and date adjustment logic.

ISDA standard conventions:
- UNADJUSTED     : return date unchanged
- FOLLOWING      : advance to next business day
- MODIFIED_FOLLOWING: advance to next business day, but stay in the same month
- PRECEDING      : retreat to previous business day
"""
from __future__ import annotations

from datetime import date, timedelta
from enum import Enum

from quant_core.conventions.calendar import Calendar


class BusinessDayConvention(str, Enum):
    """ISDA business-day conventions."""

    UNADJUSTED = "UNADJUSTED"
    FOLLOWING = "FOLLOWING"
    MODIFIED_FOLLOWING = "MODIFIED FOLLOWING"
    PRECEDING = "PRECEDING"


def adjust(d: date, bdc: BusinessDayConvention, cal: Calendar) -> date:
    """
    Adjust *d* to a business day according to *bdc*.

    Parameters
    ----------
    d : date
        The raw (unadjusted) date to roll.
    bdc : BusinessDayConvention
        Convention to apply.
    cal : Calendar
        Calendar that defines business days.

    Returns
    -------
    date
        Adjusted date (may equal *d* if it was already a business day,
        or if the convention is UNADJUSTED).
    """
    if bdc is BusinessDayConvention.UNADJUSTED or cal.is_business_day(d):
        return d

    if bdc is BusinessDayConvention.FOLLOWING:
        candidate = d + timedelta(days=1)
        while not cal.is_business_day(candidate):
            candidate += timedelta(days=1)
        return candidate

    if bdc is BusinessDayConvention.MODIFIED_FOLLOWING:
        candidate = d + timedelta(days=1)
        while not cal.is_business_day(candidate):
            candidate += timedelta(days=1)
        # If rolled into the next month, fall back to PRECEDING instead.
        if candidate.month != d.month:
            candidate = d - timedelta(days=1)
            while not cal.is_business_day(candidate):
                candidate -= timedelta(days=1)
        return candidate

    if bdc is BusinessDayConvention.PRECEDING:
        candidate = d - timedelta(days=1)
        while not cal.is_business_day(candidate):
            candidate -= timedelta(days=1)
        return candidate

    raise ValueError(f"Unknown BusinessDayConvention: {bdc!r}")  # pragma: no cover
