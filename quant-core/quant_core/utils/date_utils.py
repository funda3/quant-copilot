"""
date_utils — Low-level date arithmetic helpers.

These functions are free of any convention assumptions; they implement only
arithmetic that is deterministic across all contexts.
"""
from __future__ import annotations

import calendar
from datetime import date


def add_months(d: date, months: int) -> date:
    """
    Add a number of whole months to a date.

    If the resulting month has fewer days than the source day, the result is
    clamped to the last day of the target month (end-of-month preservation).

    Parameters
    ----------
    d : date
        The base date.
    months : int
        Number of months to add (must be >= 0).

    Returns
    -------
    date
        The resulting date.

    Examples
    --------
    >>> add_months(date(2024, 1, 31), 1)   # Jan 31 + 1M → Feb 29 (2024 leap)
    datetime.date(2024, 2, 29)
    >>> add_months(date(2023, 1, 31), 1)   # Jan 31 + 1M → Feb 28 (2023 non-leap)
    datetime.date(2023, 2, 28)
    >>> add_months(date(2024, 12, 31), 1)  # Dec 31 + 1M → Jan 31
    datetime.date(2025, 1, 31)
    """
    if months < 0:
        raise ValueError(f"months must be >= 0, got {months}")
    total_months = d.month - 1 + months
    year = d.year + total_months // 12
    month = total_months % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)
