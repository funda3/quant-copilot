"""
day_count — ISDA day-count conventions.

Supported conventions
---------------------
ACT/365F      actual days / 365 (ignores leap years)
ACT/360       actual days / 360
30/360        30/360 Bond Basis (ISMA / US — ISDA 2006 §4.16(f))
ACT/ACT ISDA  ACT/ACT split at year boundaries (ISDA 2006 §4.16(b))
"""
from __future__ import annotations

import calendar
from datetime import date
from enum import Enum


class DayCount(str, Enum):
    """Canonical names for supported ISDA day-count conventions."""

    ACT_365F = "ACT/365F"
    ACT_360 = "ACT/360"
    THIRTY_360 = "30/360"
    ACT_ACT_ISDA = "ACT/ACT ISDA"


def accrual_fraction(
    start: date,
    end: date,
    convention: DayCount | str,
) -> float:
    """
    Compute the year fraction for the period [start, end) under the specified
    day-count convention.

    Parameters
    ----------
    start : date
        Period start date (inclusive).
    end : date
        Period end date (exclusive / final date per ISDA convention).
    convention : DayCount | str
        Day-count convention.  A string is coerced to ``DayCount``; an
        unrecognised string raises ``ValueError``.

    Returns
    -------
    float
        Year fraction.  Returns 0.0 when start == end.

    Raises
    ------
    ValueError
        If ``convention`` is not a supported ``DayCount`` member.
    """
    if isinstance(convention, str):
        convention = DayCount(convention)  # raises ValueError for unknown strings

    if convention is DayCount.ACT_365F:
        return _act_365f(start, end)
    if convention is DayCount.ACT_360:
        return _act_360(start, end)
    if convention is DayCount.THIRTY_360:
        return _thirty_360(start, end)
    if convention is DayCount.ACT_ACT_ISDA:
        return _act_act_isda(start, end)
    # Unreachable — enum membership already validated above, but kept for safety.
    raise ValueError(f"Unsupported day-count convention: {convention!r}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Convention implementations
# ---------------------------------------------------------------------------


def _act_365f(start: date, end: date) -> float:
    """ACT/365 Fixed: actual days / 365 (leap years ignored)."""
    return (end - start).days / 365.0


def _act_360(start: date, end: date) -> float:
    """ACT/360: actual days / 360."""
    return (end - start).days / 360.0


def _thirty_360(start: date, end: date) -> float:
    """
    30/360 Bond Basis (ISMA / US) — ISDA 2006 §4.16(f).

    Adjustment rules (applied in order):
      1.  If D1 == 31  →  D1 = 30
      2.  If D2 == 31 and D1 (after step 1) == 30  →  D2 = 30

    Formula:
        [360*(Y2-Y1) + 30*(M2-M1) + (D2-D1)] / 360
    """
    y1, m1, d1 = start.year, start.month, start.day
    y2, m2, d2 = end.year, end.month, end.day

    if d1 == 31:
        d1 = 30
    if d2 == 31 and d1 == 30:
        d2 = 30

    return (360 * (y2 - y1) + 30 * (m2 - m1) + (d2 - d1)) / 360.0


def _act_act_isda(start: date, end: date) -> float:
    """
    ACT/ACT ISDA — ISDA 2006 §4.16(b).

    The period [start, end) is split at each 1-Jan boundary.  For each
    calendar year Y spanned, divide the days in that year by 365 (or 366
    for a leap year) and sum across all years.
    """
    if start == end:
        return 0.0

    total = 0.0
    for y in range(start.year, end.year + 1):
        year_start = date(y, 1, 1)
        year_end = date(y + 1, 1, 1)

        period_start = max(start, year_start)
        period_end = min(end, year_end)

        if period_end <= period_start:
            continue

        days_in_year = 366 if calendar.isleap(y) else 365
        total += (period_end - period_start).days / days_in_year

    return total
