"""
irs_pricer — Deterministic vanilla IRS NPV pricer with PV01 sensitivity.

Prices a :class:`~quant_core.instruments.irs.VanillaIRS` against a
:class:`~quant_core.curves.discount_curve.DiscountCurve` using a
simple analytic model:

**Fixed leg**::

    PV_fixed = Σ_i  notional × fixed_rate × τ_i × df(t_i)

where τ_i = accrual_fraction(period_start_i, period_end_i, day_count)
and t_i is the payment date of period i.

**Floating leg** (par-floating approximation)::

    PV_float = notional × (df(start_date) - df(maturity))

For a spot-starting swap (start_date == curve.valuation_date),
df(start_date) = 1.0 by definition.

**Sign convention**:

* Payer  (pay fixed, receive float): NPV = PV_float − PV_fixed
* Receiver (receive fixed, pay float): NPV = PV_fixed − PV_float

**PV01 (DV01)**:

    PV01 = |NPV_bumped − NPV_base|

where NPV_bumped is computed on a curve with all continuously-compounded
zero rates shifted up by +1bp.  The bump is applied as::

    df_bumped_i = df_i × exp(−0.0001 × τ_i)

with τ_i = accrual_fraction(valuation_date, pillar_i, swap.day_count).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from quant_core.conventions.day_count import DayCount, accrual_fraction
from quant_core.conventions.schedule import generate_unadjusted_dates
from quant_core.curves.discount_curve import DiscountCurve
from quant_core.instruments.irs import VanillaIRS

# Parallel bump size for PV01 / DV01: 1 basis point expressed as a decimal.
_BUMP_1BP: float = 0.0001


@dataclass
class IRSCashflowRow:
    """
    One fixed-leg payment period in an IRS cashflow schedule.

    Attributes
    ----------
    payment_date : date
        Date on which the fixed coupon is paid.
    accrual_start : date
        Start of the accrual period.
    accrual_end : date
        End of the accrual period; equals *payment_date*.
    year_fraction : float
        Accrual fraction τ for this period under the swap's day-count convention.
    fixed_rate : float
        Annual fixed coupon rate (decimal).
    notional : float
        Notional principal.
    fixed_cashflow : float
        Undiscounted fixed coupon: ``notional × fixed_rate × year_fraction``.
    discount_factor : float
        Discount factor from the curve's valuation date to *payment_date*.
    pv_cashflow : float
        Present value of the coupon: ``fixed_cashflow × discount_factor``.
    time_to_payment_years : float
        Year fraction from the curve's valuation date to *payment_date*.
    """

    payment_date: date
    accrual_start: date
    accrual_end: date
    year_fraction: float
    fixed_rate: float
    notional: float
    fixed_cashflow: float
    discount_factor: float
    pv_cashflow: float
    time_to_payment_years: float


@dataclass
class IRSResult:
    """
    NPV decomposition and first-order rate sensitivity for a vanilla IRS.

    Attributes
    ----------
    npv : float
        Net present value from the perspective of the counterparty
        described by *pay_receive* on the swap.
    fixed_leg_pv : float
        Present value of the fixed leg (always positive for positive rate).
    floating_leg_pv : float
        Present value of the floating leg under the par-floating
        approximation (always positive for positive discount factors).
    n_payments : int
        Number of coupon periods (= number of payment dates).
    pv01 : float
        Absolute NPV change from a parallel +1bp upward shift of all
        continuously-compounded zero rates on the discount curve.
        Always non-negative.  Also known as DV01 (dollar value of 1bp).
    """

    npv: float
    fixed_leg_pv: float
    floating_leg_pv: float
    n_payments: int
    pv01: float


def _bump_curve(
    curve: DiscountCurve,
    bump_size: float,
    day_count: DayCount,
) -> DiscountCurve:
    """
    Return a new :class:`DiscountCurve` with all zero rates shifted by
    *bump_size*.

    For each pillar *i*, the bumped discount factor is::

        df_bumped_i = df_i × exp(−bump_size × τ_i)

    where τ_i = accrual_fraction(valuation_date, pillar_i, day_count).

    This is a parallel shift of continuously-compounded zero rates: if
    r_i = −log(df_i) / τ_i then r_i_bumped = r_i + bump_size.

    Parameters
    ----------
    curve : DiscountCurve
        Base curve whose pillars are shifted.
    bump_size : float
        Rate shift in decimal units (e.g. ``0.0001`` for +1bp).
    day_count : DayCount
        Convention used to compute τ_i.  Should match the swap's
        ``day_count`` so the bump is expressed in the same year-fraction
        units as the fixed-leg accrual fractions.

    Returns
    -------
    DiscountCurve
        New curve with bumped discount factors and unchanged pillar dates.
    """
    val = curve.valuation_date
    bumped_dfs = [
        df * math.exp(-bump_size * accrual_fraction(val, pillar, day_count))
        for df, pillar in zip(curve.discount_factors, curve.pillar_dates)
    ]
    return DiscountCurve(val, curve.pillar_dates, bumped_dfs)


def _build_fixed_leg_rows(
    swap: VanillaIRS,
    curve: DiscountCurve,
) -> list[IRSCashflowRow]:
    """
    Build per-period data for the fixed leg of *swap*.

    Returns a list of :class:`IRSCashflowRow` objects, one per payment
    period, in chronological order.  Used by both :func:`_price_irs_core`
    (which sums the present values) and :func:`irs_cashflow_schedule`
    (which exposes all row details).
    """
    payment_dates = generate_unadjusted_dates(
        swap.start_date, swap.tenor_years, swap.payment_frequency
    )
    period_starts = [swap.start_date] + payment_dates[:-1]
    val = curve.valuation_date

    rows: list[IRSCashflowRow] = []
    for period_start, payment_date in zip(period_starts, payment_dates):
        tau = accrual_fraction(period_start, payment_date, swap.day_count)
        cf = swap.notional * swap.fixed_rate * tau
        df = curve.df(payment_date)
        pv = cf * df
        ttp = accrual_fraction(val, payment_date, swap.day_count)
        rows.append(
            IRSCashflowRow(
                payment_date=payment_date,
                accrual_start=period_start,
                accrual_end=payment_date,
                year_fraction=tau,
                fixed_rate=swap.fixed_rate,
                notional=swap.notional,
                fixed_cashflow=cf,
                discount_factor=df,
                pv_cashflow=pv,
                time_to_payment_years=ttp,
            )
        )
    return rows


def _price_irs_core(
    swap: VanillaIRS,
    curve: DiscountCurve,
) -> tuple[float, float, float, int]:
    """
    Core pricing engine — returns (npv, fixed_leg_pv, floating_leg_pv, n_payments).

    Extracted from :func:`price_irs` so that the PV01 bump re-price uses
    the identical formula as the base price, avoiding any risk of
    inconsistency between the two evaluations.
    """
    rows = _build_fixed_leg_rows(swap, curve)
    n_payments = len(rows)
    fixed_pv = sum(r.pv_cashflow for r in rows)
    payment_dates = [r.payment_date for r in rows]

    # Floating leg — par-floating approximation
    # df at start_date is 1.0 for spot-starting swaps by definition.
    if swap.start_date == curve.valuation_date:
        df_start = 1.0
    else:
        df_start = curve.df(swap.start_date)

    df_end = curve.df(payment_dates[-1])
    float_pv = swap.notional * (df_start - df_end)

    # Sign convention
    if swap.pay_receive == "payer":
        npv = float_pv - fixed_pv
    else:
        npv = fixed_pv - float_pv

    return npv, fixed_pv, float_pv, n_payments


def price_irs(swap: VanillaIRS, curve: DiscountCurve) -> IRSResult:
    """
    Price a :class:`~quant_core.instruments.irs.VanillaIRS` off a
    :class:`~quant_core.curves.discount_curve.DiscountCurve`, returning
    NPV and PV01.

    Parameters
    ----------
    swap : VanillaIRS
        Fully-specified swap instrument.
    curve : DiscountCurve
        Discount curve evaluated at *curve.valuation_date*.  The curve
        must cover all payment dates of the swap; if any required date
        falls outside ``[first_pillar, last_pillar]`` the underlying
        :meth:`~DiscountCurve.df` call will raise ``ValueError``.

    Returns
    -------
    IRSResult
        NPV, leg decomposition, and PV01.

    Notes
    -----
    Spot-starting swaps (``swap.start_date == curve.valuation_date``)
    are handled efficiently: df at the valuation date is taken as 1.0
    by definition rather than requiring an explicit curve pillar there.

    For forward-starting swaps (``swap.start_date > curve.valuation_date``),
    the curve must contain a pillar at or around *start_date* so that
    ``curve.df(swap.start_date)`` can be evaluated.

    **PV01 bump methodology**: all continuously-compounded zero rates on the
    curve are shifted up by :data:`_BUMP_1BP` (1bp) using
    :func:`_bump_curve`.  The day-count convention used for the bump τ_i
    values is ``swap.day_count``.  The PV01 is the absolute difference
    between the bumped and base NPVs.
    """
    # Base price
    npv, fixed_pv, float_pv, n_payments = _price_irs_core(swap, curve)

    # PV01: re-price on a +1bp parallel-shifted curve
    bumped_curve = _bump_curve(curve, _BUMP_1BP, swap.day_count)
    npv_bumped, _, _, _ = _price_irs_core(swap, bumped_curve)
    pv01 = abs(npv_bumped - npv)

    return IRSResult(
        npv=npv,
        fixed_leg_pv=fixed_pv,
        floating_leg_pv=float_pv,
        n_payments=n_payments,
        pv01=pv01,
    )


_FLOATING_LEG_METHOD: str = "par_floating_approximation"
"""
Identifier for the floating-leg pricing method used throughout this module.

The par-floating approximation values the floating leg as:

    PV_float = notional × (df(start_date) − df(maturity))

This is exact when LIBOR/JIBAR resets on the payment schedule and
principal is exchanged at both ends (or equivalently, when accrual
fractions sum to the annuity factor under the curve).  For a spot-
starting swap df(start_date) = 1.0 by definition.
"""


@dataclass
class IRSValuationBreakdown:
    """
    Desk-level NPV decomposition for a vanilla IRS.

    Attributes
    ----------
    fixed_leg_pv : float
        Present value of the fixed leg.  Computed via
        :func:`_build_fixed_leg_rows` — the identical code path used by
        :func:`price_irs`.
    floating_leg_pv : float
        Present value of the floating leg under the par-floating
        approximation: ``notional × (df(start_date) − df(maturity))``.
        Identical to the value used by :func:`price_irs`.
    npv : float
        Net present value, using the same sign convention as
        :func:`price_irs`:
        - Payer:    npv = floating_leg_pv − fixed_leg_pv
        - Receiver: npv = fixed_leg_pv − floating_leg_pv
    n_payments : int
        Number of fixed-leg payment periods.  Matches
        :attr:`IRSResult.n_payments` from :func:`price_irs` on the same
        inputs.
    floating_leg_method : str
        Label identifying the floating-leg approximation in use.  Always
        ``"par_floating_approximation"`` in this version.
    """

    fixed_leg_pv: float
    floating_leg_pv: float
    npv: float
    n_payments: int
    floating_leg_method: str


def irs_valuation_breakdown(
    swap: VanillaIRS,
    curve: DiscountCurve,
) -> IRSValuationBreakdown:
    """
    Return a desk-level NPV breakdown for *swap* priced off *curve*.

    All four numeric fields are sourced directly from
    :func:`_price_irs_core` so they are guaranteed to be consistent with
    the output of :func:`price_irs`.  No new math is introduced here.

    Parameters
    ----------
    swap : VanillaIRS
        Fully-specified swap instrument.
    curve : DiscountCurve
        Discount curve evaluated at ``curve.valuation_date``.

    Returns
    -------
    IRSValuationBreakdown
        NPV decomposition with explicit floating-leg method label.
    """
    npv, fixed_pv, float_pv, n_payments = _price_irs_core(swap, curve)
    return IRSValuationBreakdown(
        fixed_leg_pv=fixed_pv,
        floating_leg_pv=float_pv,
        npv=npv,
        n_payments=n_payments,
        floating_leg_method=_FLOATING_LEG_METHOD,
    )


def fixed_leg_annuity(
    swap: VanillaIRS,
    curve: DiscountCurve,
) -> float:
    """
    Return the fixed-leg annuity factor for *swap* evaluated on *curve*.

    The annuity is the sum of the discounted accrual fractions::

        A = Σ_i  τ_i × df(t_i)

    where τ_i = accrual_fraction(period_start_i, period_end_i, swap.day_count)
    and t_i is the payment date of period i.

    The fair fixed rate satisfies::

        fair_rate = PV_float / (notional × A)

    so that the NPV of the payer swap is exactly zero.

    Parameters
    ----------
    swap : VanillaIRS
        Fully-specified swap instrument.  Only ``payment_frequency``,
        ``start_date``, ``tenor_years``, ``day_count``, and ``notional``
        are used; ``fixed_rate`` is not.
    curve : DiscountCurve
        Discount curve evaluated at ``curve.valuation_date``.

    Returns
    -------
    float
        Annuity factor (sum of τ_i × df_i).  Always > 0 for valid inputs.

    Raises
    ------
    ValueError
        If the annuity computes to zero or negative, which would indicate
        degenerate curve or schedule inputs.
    """
    rows = _build_fixed_leg_rows(swap, curve)
    annuity = sum(r.year_fraction * r.discount_factor for r in rows)
    if annuity <= 0.0:
        raise ValueError(
            f"Fixed-leg annuity is non-positive ({annuity}); "
            "cannot solve for fair rate. Check curve and schedule inputs."
        )
    return annuity


def solve_irs_fair_rate(
    swap: VanillaIRS,
    curve: DiscountCurve,
) -> float:
    """
    Solve for the fair fixed rate (par swap rate) that makes the NPV zero.

    Uses the algebraic identity::

        fair_rate = PV_float / (notional × A)

    where ``PV_float = notional × (df(start) − df(maturity))`` (par-floating
    approximation) and ``A = Σ_i τ_i × df(t_i)`` is the fixed-leg annuity.

    This is the unique rate at which the payer (and receiver) NPV is exactly
    zero under the existing pricing model.  The result is independent of the
    ``pay_receive`` direction on *swap*.

    Parameters
    ----------
    swap : VanillaIRS
        Fully-specified swap instrument.  The ``fixed_rate`` field is
        ignored; only the schedule parameters (tenor, frequency, day count,
        start date, notional) are used.
    curve : DiscountCurve
        Discount curve evaluated at ``curve.valuation_date``.

    Returns
    -------
    float
        Fair fixed rate as a decimal (e.g. ``0.0834`` for 8.34 %).
        Always positive for standard upward-sloping or flat curves.

    Raises
    ------
    ValueError
        If the fixed-leg annuity is zero or negative (degenerate inputs).

    Notes
    -----
    *Spot-starting swaps*: ``df(start_date) = 1.0`` by definition when
    ``swap.start_date == curve.valuation_date``, which is the common case.

    *Consistency*: calling ``price_irs`` with ``swap.fixed_rate`` replaced
    by the returned fair rate gives ``NPV ≈ 0`` to machine precision.
    """
    # Floating-leg PV under the par-floating approximation
    if swap.start_date == curve.valuation_date:
        df_start = 1.0
    else:
        df_start = curve.df(swap.start_date)

    payment_dates = [
        r.payment_date for r in _build_fixed_leg_rows(swap, curve)
    ]
    df_end = curve.df(payment_dates[-1])
    float_pv = swap.notional * (df_start - df_end)

    # Fixed-leg annuity (raises if zero/negative)
    annuity = fixed_leg_annuity(swap, curve)

    return float_pv / (swap.notional * annuity)


def irs_cashflow_schedule(
    swap: VanillaIRS,
    curve: DiscountCurve,
) -> list[IRSCashflowRow]:
    """
    Return the full fixed-leg cashflow schedule for a vanilla IRS.

    Each :class:`IRSCashflowRow` exposes the payment date, accrual period,
    year fraction, fixed cashflow, discount factor, present value, and
    time-to-payment.  Rows are returned in chronological order.

    The sum of :attr:`~IRSCashflowRow.pv_cashflow` across all rows equals
    the :attr:`~IRSResult.fixed_leg_pv` returned by :func:`price_irs` on
    the same swap and curve.

    Parameters
    ----------
    swap : VanillaIRS
        Fully-specified swap instrument.
    curve : DiscountCurve
        Discount curve evaluated at ``curve.valuation_date``.  Must cover
        all payment dates of the swap.

    Returns
    -------
    list[IRSCashflowRow]
        One row per payment period, in chronological order.
    """
    return _build_fixed_leg_rows(swap, curve)
