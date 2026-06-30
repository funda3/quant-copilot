"""
schedule — Coupon-date schedule generation.

Provides two public functions:

* :func:`generate_unadjusted_dates` — raw calendar dates (no BDC applied).
* :func:`generate_schedule` — optionally applies a calendar and
  business-day convention (BDC) to the unadjusted dates.

Both functions support an *eom* flag: when the effective date falls on the
last calendar day of its month and ``eom=True``, every generated date is
forced to the last calendar day of its respective month.
"""
from __future__ import annotations

import calendar as _cal
from datetime import date
from typing import TYPE_CHECKING

from quant_core.utils.date_utils import add_months

if TYPE_CHECKING:
    from quant_core.conventions.business_day import BusinessDayConvention
    from quant_core.conventions.calendar import Calendar


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _last_day_of_month(d: date) -> date:
    """Return the last calendar day of *d*'s month."""
    return date(d.year, d.month, _cal.monthrange(d.year, d.month)[1])


def _is_month_end(d: date) -> bool:
    """Return ``True`` if *d* is the last day of its month."""
    return d.day == _cal.monthrange(d.year, d.month)[1]

# Supported frequencies and their period length in months.
_FREQ_MONTHS: dict[str, int] = {
    "monthly": 1,
    "quarterly": 3,
    "semiannual": 6,
    "annual": 12,
}


def generate_unadjusted_dates(
    effective_date: date,
    tenor_years: int,
    frequency: str,
    eom: bool = False,
) -> list[date]:
    """
    Generate the list of unadjusted coupon payment dates for a vanilla swap leg.

    Dates run from the first coupon date (``effective_date + one coupon period``)
    to the maturity date (``effective_date + tenor_years``), stepping forward by
    the coupon period.

    No business-day adjustment is applied.  The maturity date is always the
    final element.

    Parameters
    ----------
    effective_date : date
        Swap start / spot date.
    tenor_years : int
        Tenor in whole years (must be >= 1).
    frequency : str
        Payment frequency — one of ``"monthly"``, ``"quarterly"``,
        ``"semiannual"``, ``"annual"`` (case-insensitive).
    eom : bool, optional
        End-of-month rule.  When ``True`` *and* ``effective_date`` is the
        last calendar day of its month, every generated date is forced to
        the last calendar day of its respective month.  Defaults to
        ``False``.

    Returns
    -------
    list[date]
        Ordered list of unadjusted coupon dates, first coupon to maturity
        (inclusive).

    Raises
    ------
    ValueError
        For an unsupported or unknown ``frequency`` string, or a tenor < 1.
    """
    freq = str(frequency).lower()
    if freq not in _FREQ_MONTHS:
        raise ValueError(
            f"Unsupported frequency {frequency!r}. "
            f"Supported values: {sorted(_FREQ_MONTHS)}"
        )
    if tenor_years < 1:
        raise ValueError(f"tenor_years must be >= 1, got {tenor_years}")

    step_months = _FREQ_MONTHS[freq]
    apply_eom = eom and _is_month_end(effective_date)

    # Maturity: raw month arithmetic, then EOM-upgrade if rule is active.
    raw_maturity = add_months(effective_date, tenor_years * 12)
    maturity = _last_day_of_month(raw_maturity) if apply_eom else raw_maturity

    # Build dates by indexing from effective_date so EOM arithmetic stays
    # anchored to the original start (avoids drift through short months).
    dates: list[date] = []
    i = 1
    while True:
        raw = add_months(effective_date, i * step_months)
        dt = _last_day_of_month(raw) if apply_eom else raw
        if dt > maturity:
            break
        dates.append(dt)
        i += 1

    # Safety: ensure maturity is last. Protects against any edge case where
    # step arithmetic undershoots maturity.
    if not dates or dates[-1] != maturity:
        if dates and dates[-1] < maturity:
            dates.append(maturity)
        elif not dates:
            dates = [maturity]

    return dates


def generate_schedule(
    effective_date: date,
    tenor_years: int,
    frequency: str,
    calendar: "Calendar | None" = None,
    bdc: "BusinessDayConvention | None" = None,
    eom: bool = False,
) -> list[date]:
    """
    Generate a (optionally adjusted) coupon-date schedule.

    Calls :func:`generate_unadjusted_dates` with the given parameters, then
    applies business-day adjustment when both *calendar* and *bdc* are
    supplied.

    Parameters
    ----------
    effective_date : date
        Swap start / spot date.
    tenor_years : int
        Tenor in whole years.
    frequency : str
        Payment frequency string (see :func:`generate_unadjusted_dates`).
    calendar : Calendar or None
        Calendar defining business days.  If ``None``, no adjustment is
        applied regardless of *bdc*.
    bdc : BusinessDayConvention or None
        Business-day convention.  If ``None``, no adjustment is applied.
    eom : bool, optional
        End-of-month rule (see :func:`generate_unadjusted_dates`).

    Returns
    -------
    list[date]
        Adjusted (or unadjusted, if calendar/bdc are ``None``) coupon dates.
    """
    unadjusted = generate_unadjusted_dates(
        effective_date, tenor_years, frequency, eom=eom
    )
    if calendar is None or bdc is None:
        return unadjusted

    # Import here to avoid a module-level circular dependency.
    from quant_core.conventions.business_day import adjust  # noqa: PLC0415

    return [adjust(d, bdc, calendar) for d in unadjusted]


def n_payments(tenor_years: int, frequency: str) -> int:
    """
    Return the number of coupon payments for a given tenor and frequency.

    This is a convenience helper that mirrors the count of dates returned by
    :func:`generate_unadjusted_dates`, without generating the date list.

    Parameters
    ----------
    tenor_years : int
        Tenor in whole years.
    frequency : str
        Payment frequency string (see :func:`generate_unadjusted_dates`).

    Returns
    -------
    int
        Number of coupon periods.
    """
    freq = str(frequency).lower()
    if freq not in _FREQ_MONTHS:
        raise ValueError(f"Unsupported frequency {frequency!r}.")
    return (tenor_years * 12) // _FREQ_MONTHS[freq]
