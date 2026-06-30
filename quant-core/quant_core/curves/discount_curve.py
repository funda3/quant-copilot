"""
discount_curve — Pillar-based discount-factor curve with log-linear interpolation.

A :class:`DiscountCurve` stores a sorted sequence of (date, discount_factor)
pillars and interpolates between them using log-linear interpolation on the
discount factors — the standard approach that guarantees positive forward rates
between any two adjacent pillars.

Extrapolation is deliberately not supported in this increment; callers must
stay within [first_pillar, last_pillar].
"""
from __future__ import annotations

import math
from datetime import date

from quant_core.conventions.day_count import DayCount, accrual_fraction


class DiscountCurve:
    """
    A discount-factor curve defined by a set of (date, df) pillars.

    Interpolation between pillars uses log-linear interpolation on discount
    factors, i.e.::

        log(df(t)) = log(df(t1)) + (t - t1) / (t2 - t1) * (log(df(t2)) - log(df(t1)))

    where the time axis is plain calendar days so that the ratio is exact and
    no day-count convention is needed for the interpolation kernel itself.

    Parameters
    ----------
    valuation_date : date
        The as-of date for the curve (i.e. where df = 1.0 by definition).
    pillar_dates : list[date]
        Strictly-increasing sequence of pillar dates (all must be after
        *valuation_date*).
    discount_factors : list[float]
        Discount factor for each pillar date.  Must be the same length as
        *pillar_dates*, and every value must be > 0.

    Raises
    ------
    ValueError
        On any invalid construction argument (see validation rules below).
    """

    def __init__(
        self,
        valuation_date: date,
        pillar_dates: list[date],
        discount_factors: list[float],
    ) -> None:
        # ------------------------------------------------------------------ #
        # Validation
        # ------------------------------------------------------------------ #
        if not pillar_dates:
            raise ValueError("pillar_dates must not be empty")
        if len(pillar_dates) != len(discount_factors):
            raise ValueError(
                f"pillar_dates length ({len(pillar_dates)}) != "
                f"discount_factors length ({len(discount_factors)})"
            )
        # Strictly increasing pillar dates
        for i in range(1, len(pillar_dates)):
            if pillar_dates[i] <= pillar_dates[i - 1]:
                raise ValueError(
                    f"pillar_dates must be strictly increasing; "
                    f"pillar[{i - 1}]={pillar_dates[i - 1]} >= pillar[{i}]={pillar_dates[i]}"
                )
        # All pillars after valuation date
        if pillar_dates[0] <= valuation_date:
            raise ValueError(
                f"First pillar date {pillar_dates[0]} must be after "
                f"valuation_date {valuation_date}"
            )
        # Positive discount factors
        for i, df in enumerate(discount_factors):
            if df <= 0.0:
                raise ValueError(
                    f"discount_factors[{i}] = {df} is not positive"
                )

        self._valuation_date: date = valuation_date
        self._pillar_dates: list[date] = list(pillar_dates)
        self._discount_factors: list[float] = list(discount_factors)
        # Pre-compute log(df) for each pillar to avoid repeated log calls.
        self._log_dfs: list[float] = [math.log(d) for d in self._discount_factors]

    # ---------------------------------------------------------------------- #
    # Properties
    # ---------------------------------------------------------------------- #

    @property
    def valuation_date(self) -> date:
        """The as-of date of the curve."""
        return self._valuation_date

    @property
    def pillar_dates(self) -> list[date]:
        """Sorted pillar dates (read-only copy)."""
        return list(self._pillar_dates)

    @property
    def discount_factors(self) -> list[float]:
        """Discount factors at each pillar (read-only copy)."""
        return list(self._discount_factors)

    # ---------------------------------------------------------------------- #
    # Core methods
    # ---------------------------------------------------------------------- #

    def df(self, target_date: date) -> float:
        """
        Return the discount factor at *target_date* via log-linear interpolation.

        Parameters
        ----------
        target_date : date
            The date at which to evaluate the discount factor.

        Returns
        -------
        float
            Discount factor df(t) ∈ (0, 1].

        Raises
        ------
        ValueError
            If *target_date* is before the first pillar or after the last
            pillar (extrapolation not supported).
        """
        if target_date < self._pillar_dates[0]:
            raise ValueError(
                f"target_date {target_date} is before the first pillar "
                f"{self._pillar_dates[0]}; extrapolation is not supported"
            )
        if target_date > self._pillar_dates[-1]:
            raise ValueError(
                f"target_date {target_date} is after the last pillar "
                f"{self._pillar_dates[-1]}; extrapolation is not supported"
            )

        # Binary search for the bracketing interval.
        lo, hi = 0, len(self._pillar_dates) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if self._pillar_dates[mid] < target_date:
                lo = mid + 1
            else:
                hi = mid

        # hi now points to the first pillar >= target_date.
        if self._pillar_dates[hi] == target_date:
            return self._discount_factors[hi]

        # target_date is strictly between pillar[hi-1] and pillar[hi].
        i_lo = hi - 1
        i_hi = hi
        d_lo = self._pillar_dates[i_lo].toordinal()
        d_hi = self._pillar_dates[i_hi].toordinal()
        d_t  = target_date.toordinal()

        frac = (d_t - d_lo) / (d_hi - d_lo)   # calendar-day fraction
        log_df = self._log_dfs[i_lo] + frac * (self._log_dfs[i_hi] - self._log_dfs[i_lo])
        return math.exp(log_df)

    def zero_rate(self, target_date: date, day_count: DayCount) -> float:
        """
        Return the continuously-compounded zero rate to *target_date*.

        The zero rate *r* satisfies::

            df(t) = exp(-r * tau)

        where *tau* is the year fraction from *valuation_date* to *target_date*
        computed with *day_count*.

        Parameters
        ----------
        target_date : date
            The date at which to evaluate the zero rate.
        day_count : DayCount
            Day-count convention used to convert the date distance to a year
            fraction.

        Returns
        -------
        float
            Continuously-compounded zero rate.

        Raises
        ------
        ValueError
            If *target_date* equals *valuation_date* (zero year fraction),
            or if *target_date* is outside the pillar range.
        """
        tau = accrual_fraction(self._valuation_date, target_date, day_count)
        if tau <= 0.0:
            raise ValueError(
                f"Year fraction from valuation_date {self._valuation_date} "
                f"to target_date {target_date} is {tau}; must be > 0"
            )
        d = self.df(target_date)
        return -math.log(d) / tau
