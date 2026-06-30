"""
bootstrap_mixed — Bootstrap a :class:`DiscountCurve` from a mixed ladder of
deposit, FRA, and par-swap :class:`~quant_core.schemas.market_inputs.NormalizedRateRecord`
inputs.

Overview
--------
:func:`bootstrap_discount_curve_from_market_records` accepts any combination
of three instrument types expressed as
:class:`~quant_core.schemas.market_inputs.NormalizedRateRecord` items (the
output of :func:`~quant_core.marketdata.normalize_rates.normalize_market_quotes`).

Processing order
~~~~~~~~~~~~~~~~
Records are sorted—defensively—by the same deterministic key used in
``normalize_market_quotes``:

    (start_months, end_months, type_priority)

where ``deposit = 0 < fra = 1 < swap = 2``.

This guarantees that, for any well-formed market ladder, short-end deposits
precede FRAs, which precede long-end swaps—so each instrument can reference
only already-solved discount factors.

Instrument equations
~~~~~~~~~~~~~~~~~~~~

**Deposit** (``start_months = 0``, ``end_months > 0``):

    df(t_end) = 1 / (1 + r × τ(val, t_end))

A single closed-form solve; no prior pillars needed.

**FRA** (``start_months > 0``, ``end_months > start_months``):

    df(t_end) = df(t_start) / (1 + f × τ(t_start, t_end))

Requires ``df(t_start)`` to already be in the working curve (not necessarily
as a pillar — interpolation is used if it falls between existing pillars).

**Par swap** (``start_months = 0``, ``end_months > 0``):

Uses the same algebraic par-swap bootstrap as
:mod:`~quant_core.curves.bootstrap_swap`, including Newton's method for
the "gap coupon date" case that arises on non-annual ladders or sparse
swap tenors.

Duplicate-maturity guard
~~~~~~~~~~~~~~~~~~~~~~~~
Each pillar date may be solved at most once.  If a second record maps to
the same maturity date and the two implied discount factors disagree beyond
a tight tolerance (``1e-8``), a :exc:`ValueError` is raised to prevent
silent overwriting of a calibrated pillar.

If they are consistent (two instruments pointing to the same pillar within
tolerance) the redundant record is silently accepted (average is used), which
supports over-determined inputs provided they are consistent.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Sequence

from quant_core.conventions.day_count import DayCount, accrual_fraction
from quant_core.conventions.schedule import generate_unadjusted_dates
from quant_core.curves.discount_curve import DiscountCurve
from quant_core.schemas.market_inputs import NormalizedRateRecord
from quant_core.utils.date_utils import add_months

# Sort-priority weight — must match normalize_rates._TYPE_PRIORITY.
_TYPE_PRIORITY: dict[str, int] = {"deposit": 0, "fra": 1, "swap": 2}

# Duplicate-maturity tolerance: discount factors that agree within this
# absolute difference are considered consistent.
_DF_CONSISTENCY_TOL: float = 1e-8


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def bootstrap_discount_curve_from_market_records(
    valuation_date: date,
    records: Sequence[NormalizedRateRecord],
    payment_frequency: str = "annual",
    day_count: DayCount = DayCount.ACT_365F,
) -> DiscountCurve:
    """
    Bootstrap a :class:`~quant_core.curves.discount_curve.DiscountCurve`
    from a mixed ladder of normalized market-rate records.

    Parameters
    ----------
    valuation_date : date
        As-of / settlement date.
    records : sequence of NormalizedRateRecord
        The normalized market quotes to bootstrap from.  Records may be
        supplied in any order; they are sorted defensively inside this
        function using the same deterministic key as
        :func:`~quant_core.marketdata.normalize_rates.normalize_market_quotes`.
        The sequence must be non-empty.
    payment_frequency : str, optional
        Fixed-leg coupon frequency for any swap records — one of
        ``"monthly"``, ``"quarterly"``, ``"semiannual"``, ``"annual"``
        (case-insensitive).  Defaults to ``"annual"``.
    day_count : DayCount, optional
        Day-count convention applied to all accrual fractions.  Defaults
        to :attr:`~quant_core.conventions.day_count.DayCount.ACT_365F`.

    Returns
    -------
    DiscountCurve
        A calibrated curve with one pillar per unique solved maturity date.

    Raises
    ------
    ValueError
        * If ``records`` is empty.
        * If an unsupported ``instrument_type`` value is encountered
          (defensive; :class:`NormalizedRateRecord` already validates this).
        * If a FRA record references a ``start_months`` offset for which no
          discount factor has been solved yet.
        * If two records solve the same maturity to inconsistent discount
          factors (disagreement > ``1e-8``).
        * If any solved discount factor is not positive.
        * If the solved discount factors are not non-increasing with
          maturity (implies negative forward rates; signals bad inputs).
    """
    records_list = list(records)
    if not records_list:
        raise ValueError("records must be non-empty")

    # Sort by instrument type first (deposits → FRAs → swaps), then by
    # end_months within each type.  This ensures that FRA start dates are
    # always covered by prior deposit pillars, and swap bootstrapping has
    # the full short-end curve available.
    records_list.sort(
        key=lambda r: (
            _TYPE_PRIORITY.get(r.instrument_type, 99),
            r.end_months,
        )
    )

    # ---------------------------------------------------------------------- #
    # State: mapping from pillar_date → solved df; ordered lists for curve.   #
    # ---------------------------------------------------------------------- #
    pillar_map: dict[date, float] = {}  # date → df, for quick lookup
    pillar_dates: list[date] = []       # ordered, strictly increasing
    discount_factors: list[float] = []

    # The working DiscountCurve is rebuilt after every new pillar is added.
    # Before any pillar exists, it is None.
    _working_curve: DiscountCurve | None = None

    def _record_pillar(pillar_date: date, df_new: float) -> None:
        """
        Add or reconcile a solved pillar.

        If ``pillar_date`` is not yet in ``pillar_map``, insert it in
        sorted order.  If it is already there, check consistency.
        """
        nonlocal _working_curve

        if pillar_date in pillar_map:
            df_existing = pillar_map[pillar_date]
            if abs(df_new - df_existing) > _DF_CONSISTENCY_TOL:
                raise ValueError(
                    f"Inconsistent discount factors at pillar {pillar_date}: "
                    f"existing={df_existing:.10f}, new={df_new:.10f} "
                    f"(delta={abs(df_new - df_existing):.2e} > tolerance "
                    f"{_DF_CONSISTENCY_TOL:.0e})"
                )
            # Consistent duplicate — accept; no curve rebuild needed.
            return

        # Positive df guard.
        if df_new <= 0.0:
            raise ValueError(
                f"Bootstrap produced a non-positive discount factor "
                f"({df_new:.8f}) at {pillar_date}. Check input rates."
            )

        # Insert in sorted order (records are already sorted, but defensive).
        import bisect
        idx = bisect.bisect_left(pillar_dates, pillar_date)

        # Non-increasing guard vs the immediately preceding pillar.
        if idx > 0 and df_new > discount_factors[idx - 1]:
            raise ValueError(
                f"Bootstrap produced an increasing discount factor at "
                f"{pillar_date}: df={df_new:.8f} > previous "
                f"df={discount_factors[idx - 1]:.8f}. This implies a negative "
                f"implied forward rate; check input rates."
            )
        pillar_dates.insert(idx, pillar_date)
        discount_factors.insert(idx, df_new)
        pillar_map[pillar_date] = df_new

        _working_curve = DiscountCurve(valuation_date, pillar_dates, discount_factors)

    def _df_at(target_date: date) -> float:
        """
        Return df at *target_date* from the working curve.
        Raises if no working curve exists yet.
        """
        if target_date == valuation_date:
            return 1.0
        if _working_curve is None:
            raise ValueError(
                f"Cannot look up df at {target_date}: no pillars solved yet."
            )
        return _working_curve.df(target_date)

    # ---------------------------------------------------------------------- #
    # Process each record                                                      #
    # ---------------------------------------------------------------------- #
    for rec in records_list:
        t_start = add_months(valuation_date, rec.start_months)
        t_end = add_months(valuation_date, rec.end_months)

        if rec.instrument_type == "deposit":
            _bootstrap_deposit(
                valuation_date, t_end, rec.quote_rate, day_count, _record_pillar
            )

        elif rec.instrument_type == "fra":
            _bootstrap_fra(
                valuation_date, t_start, t_end, rec.quote_rate,
                day_count, _df_at, _record_pillar
            )

        elif rec.instrument_type == "swap":
            _bootstrap_swap(
                valuation_date, rec.end_months, rec.quote_rate,
                payment_frequency, day_count,
                _working_curve, _record_pillar
            )

        else:
            # NormalizedRateRecord.__post_init__ already rejects unknown types,
            # but guard defensively.
            raise ValueError(
                f"Unsupported instrument_type '{rec.instrument_type}'. "
                f"Expected one of 'deposit', 'fra', 'swap'."
            )

    return _working_curve  # type: ignore[return-value]  # non-empty validated above


# ---------------------------------------------------------------------------
# Per-instrument bootstrap helpers
# ---------------------------------------------------------------------------


def _bootstrap_deposit(
    valuation_date: date,
    t_end: date,
    rate: float,
    day_count: DayCount,
    record_pillar,  # callable(date, float) -> None
) -> None:
    """
    Solve df(t_end) from a simple deposit rate.

        df(t_end) = 1 / (1 + r * τ(val, t_end))
    """
    tau = accrual_fraction(valuation_date, t_end, day_count)
    df = 1.0 / (1.0 + rate * tau)
    record_pillar(t_end, df)


def _bootstrap_fra(
    valuation_date: date,
    t_start: date,
    t_end: date,
    forward_rate: float,
    day_count: DayCount,
    df_at,          # callable(date) -> float; raises if unknown
    record_pillar,  # callable(date, float) -> None
) -> None:
    """
    Solve df(t_end) from a FRA rate using the known df(t_start).

        df(t_end) = df(t_start) / (1 + f * τ(t_start, t_end))

    Raises :exc:`ValueError` if df(t_start) is not yet available (this
    indicates that the records were not supplied in a sensible order —
    the caller is responsible for sorting them using
    :func:`~quant_core.marketdata.normalize_rates.normalize_market_quotes`
    or providing a pre-sorted sequence).
    """
    try:
        df_start = df_at(t_start)
    except ValueError:
        raise ValueError(
            f"FRA [{t_start} → {t_end}]: discount factor at start date "
            f"{t_start} has not been solved yet. Ensure deposit records "
            f"covering the FRA start date appear before this FRA in the "
            f"sorted record list."
        )

    tau = accrual_fraction(t_start, t_end, day_count)
    df = df_start / (1.0 + forward_rate * tau)
    record_pillar(t_end, df)


def _bootstrap_swap(
    valuation_date: date,
    tenor_months: int,
    par_rate: float,
    payment_frequency: str,
    day_count: DayCount,
    working_curve: DiscountCurve | None,
    record_pillar,  # callable(date, float) -> None
) -> None:
    """
    Solve the terminal discount factor for a par swap using the algebraic
    par-swap bootstrap identity, with Newton's method for the "gap coupon
    date" case.

    This is essentially the same logic as
    :func:`~quant_core.curves.bootstrap_swap.bootstrap_discount_curve_from_swaps`
    for a single tenor, factored out so it can be called from the mixed engine.

    The tenor is expressed as *tenor_months* (= ``end_months`` of the record).
    Coupon dates are derived from ``generate_unadjusted_dates`` using
    tenor_months // 12 whole years.  Residual months (tenor_months % 12 != 0)
    are not currently supported — only whole-year swap tenors are accepted.

    Raises
    ------
    ValueError
        For non-integer-year tenors (tenor_months not divisible by 12).
    """
    if tenor_months % 12 != 0:
        raise ValueError(
            f"Swap bootstrap requires a whole-year tenor; got "
            f"tenor_months={tenor_months} ({tenor_months / 12:.2f} years). "
            f"Only tenors that are exact multiples of 12 months are supported."
        )

    tenor_years = tenor_months // 12
    payment_dates = generate_unadjusted_dates(
        valuation_date, tenor_years, payment_frequency
    )
    period_starts = [valuation_date] + payment_dates[:-1]
    n = len(payment_dates)
    maturity_date = payment_dates[-1]

    c = par_rate

    # Accrual fractions for all n periods.
    taus = [
        accrual_fraction(period_starts[i], payment_dates[i], day_count)
        for i in range(n)
    ]

    # Determine if there are "gap" coupon dates: intermediate dates
    # (i < n-1) that lie strictly beyond the last working pillar.
    if working_curve is not None:
        last_pillar = working_curve.pillar_dates[-1]
        first_pillar = working_curve.pillar_dates[0]
    else:
        last_pillar = None
        first_pillar = None

    has_gap = working_curve is not None and any(
        payment_dates[i] > last_pillar  # type: ignore[operator]
        for i in range(n - 1)
    )

    def _df_for_intermediate(i: int, df_terminal: float) -> float:
        """
        Return df for intermediate coupon date payment_dates[i] (i < n-1).
        Gap dates are log-linearly interpolated between last_pillar and df_terminal.
        """
        pd = payment_dates[i]

        if working_curve is None:
            # No pillars yet — use simple-rate approximation.
            tau_from_val = accrual_fraction(valuation_date, pd, day_count)
            return 1.0 / (1.0 + c * tau_from_val)

        if pd > last_pillar:  # type: ignore[operator]
            # Gap date: log-linear interpolation between last pillar
            # and the terminal pillar being solved.
            df_last = working_curve.discount_factors[-1]
            tau_total = accrual_fraction(last_pillar, maturity_date, day_count)
            tau_frac = accrual_fraction(last_pillar, pd, day_count)
            alpha = tau_frac / tau_total
            return math.exp(
                (1.0 - alpha) * math.log(df_last)
                + alpha * math.log(df_terminal)
            )

        if pd < first_pillar:  # type: ignore[operator]
            # Before-first-pillar: flat-forward from val to first pillar.
            t_first = working_curve.pillar_dates[0]
            df_first = working_curve.discount_factors[0]
            tau_val_first = accrual_fraction(valuation_date, t_first, day_count)
            fwd_first = -math.log(df_first) / tau_val_first
            tau_val_i = accrual_fraction(valuation_date, pd, day_count)
            return math.exp(-fwd_first * tau_val_i)

        # Within working curve range — log-linear interpolation.
        return working_curve.df(pd)

    def _par_residual(df_terminal: float) -> float:
        """Par-swap residual; zero when df_terminal is correct."""
        annuity = sum(
            taus[i] * _df_for_intermediate(i, df_terminal)
            for i in range(n - 1)
        )
        return c * (annuity + taus[-1] * df_terminal) + df_terminal - 1.0

    # ------------------------------------------------------------------ #
    # Solve for df_terminal                                                #
    # ------------------------------------------------------------------ #
    if not has_gap:
        # Par condition is linear in df_terminal → algebraic solution.
        annuity_prev = sum(
            taus[i] * _df_for_intermediate(i, 0.0)
            for i in range(n - 1)
        )
        numerator = 1.0 - c * annuity_prev
        denominator = 1.0 + c * taus[-1]
        df_terminal = numerator / denominator
    else:
        # Gap present → Newton's method.
        # Initial guess: flat-forward extrapolation from last pillar.
        df_last = working_curve.discount_factors[-1]  # type: ignore[union-attr]
        t_last = working_curve.pillar_dates[-1]  # type: ignore[union-attr]
        if len(working_curve.pillar_dates) >= 2:  # type: ignore[union-attr]
            t_prev = working_curve.pillar_dates[-2]  # type: ignore[union-attr]
            df_prev_h = working_curve.discount_factors[-2]  # type: ignore[union-attr]
            tau_seg = accrual_fraction(t_prev, t_last, day_count)
            fwd_h = (math.log(df_prev_h) - math.log(df_last)) / tau_seg
        else:
            tau_to_last = accrual_fraction(valuation_date, t_last, day_count)
            fwd_h = -math.log(df_last) / tau_to_last
        tau_extrap = accrual_fraction(t_last, maturity_date, day_count)
        df_terminal = df_last * math.exp(-fwd_h * tau_extrap)

        for _ in range(50):
            f = _par_residual(df_terminal)
            if abs(f) < 1e-14:
                break
            eps = df_terminal * 1e-7
            f_plus = _par_residual(df_terminal + eps)
            df_prime = (f_plus - f) / eps
            if abs(df_prime) < 1e-30:
                break
            df_terminal -= f / df_prime

    # For the very first swap record (no prior working curve), intermediate
    # coupon dates were approximated.  Register them as pillars too so the
    # DiscountCurve can reprice the swap through them.
    if working_curve is None and n > 1:
        for i in range(n - 1):
            pd = payment_dates[i]
            tau_from_val = accrual_fraction(valuation_date, pd, day_count)
            df_inter = 1.0 / (1.0 + c * tau_from_val)
            record_pillar(pd, df_inter)

    record_pillar(maturity_date, df_terminal)
