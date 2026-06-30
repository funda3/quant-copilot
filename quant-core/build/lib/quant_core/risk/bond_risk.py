"""
bond_risk — Deterministic DV01 and modified duration for fixed-rate bonds.

Both metrics are computed by bump-and-reprice: a parallel +1bp shift is
applied to all continuously-compounded zero rates implied by the discount
curve, the bond is repriced on the shifted curve, and the resulting
price change is used to derive the risk measures.

Methodology
-----------
**Bumped curve construction**

For each pillar date *d_i* the continuously-compounded zero rate is::

    r_i = -log(df_i) / τ_i          where τ_i = (d_i - val_date).days / 365.0

After bumping by *bump_bps* basis points::

    r_i_bumped = r_i + bump_bps * 0.0001

The bumped discount factor is then::

    df_i_bumped = exp(-r_i_bumped * τ_i)
               = df_i * exp(-bump_bps * 0.0001 * τ_i)

This is a parallel shift of the entire CC zero-rate curve — all pillars move
by the same amount.  It is the same convention used by
:func:`~quant_core.risk.ladder._bump_single_pillar`.

**DV01**::

    dv01 = dirty_price_base - dirty_price_bumped

The sign convention is *price fall per +1bp rate rise*, so DV01 is positive
for a long bond position.  A rate increase always decreases a bond's value,
so ``dirty_price_bumped < dirty_price_base`` and DV01 > 0 for any standard
coupon or zero-coupon bond.

**Modified duration**::

    modified_duration = dv01 / dirty_price_base * 10_000

This is the standard textbook relationship:
    dv01 ≈ modified_duration * dirty_price / 10_000

If ``dirty_price_base`` is effectively zero (< 1e-12) ``modified_duration``
returns 0.0 and the condition is documented in the docstring.  This edge
case cannot be triggered with a valid :class:`~quant_core.instruments.bond.FixedRateBond`
and a well-formed :class:`~quant_core.curves.discount_curve.DiscountCurve`
because a positive face value with positive discount factors always yields a
positive dirty price.  The guard exists purely as a defensive measure.
"""
from __future__ import annotations

import math

from quant_core.conventions.day_count import accrual_fraction
from quant_core.curves.discount_curve import DiscountCurve
from quant_core.instruments.bond import FixedRateBond
from quant_core.pricing.bond_pricer import _coupon_schedule, price_bond

# Minimum dirty price below which modified_duration returns 0.0.
_MIN_PRICE_GUARD: float = 1e-12


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _parallel_bump_curve(curve: DiscountCurve, bump_bps: float) -> DiscountCurve:
    """
    Return a new :class:`DiscountCurve` with all CC zero rates shifted by
    *bump_bps* basis points.

    The original curve is **not mutated**.  A brand-new ``DiscountCurve``
    object is constructed and returned.

    The bump formula per pillar *i*::

        df_bumped_i = df_i * exp(-bump_bps * 0.0001 * τ_i)

    where τ_i = calendar days from valuation_date to pillar_date / 365.0 is
    a simple act/act (calendar-day) year fraction used purely for the
    zero-rate conversion.  Using calendar days ensures the bump is
    consistently expressed regardless of the bond's accrual day-count.

    Parameters
    ----------
    curve : DiscountCurve
        Base discount curve.
    bump_bps : float
        Parallel shift in basis points (e.g. ``1.0`` for +1 bp).

    Returns
    -------
    DiscountCurve
        A new curve with every pillar discount factor bumped.
    """
    bump_decimal = bump_bps * 0.0001
    val_ord = curve.valuation_date.toordinal()
    new_dfs: list[float] = []

    for pillar_date, df in zip(curve.pillar_dates, curve.discount_factors):
        # Use calendar-day year fraction for zero-rate decomposition.
        tau = (pillar_date.toordinal() - val_ord) / 365.0
        bumped_df = df * math.exp(-bump_decimal * tau)
        new_dfs.append(bumped_df)

    return DiscountCurve(curve.valuation_date, curve.pillar_dates, new_dfs)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def bond_dv01(
    bond: FixedRateBond,
    curve: DiscountCurve,
    bump_bps: int | float = 1,
) -> float:
    """
    Compute the DV01 (dollar value of 1 basis point) for a fixed-rate bond.

    DV01 is defined as the *decrease* in dirty price for a parallel +1bp
    upward shift of all continuously-compounded zero rates::

        dv01 = dirty_price_base - dirty_price_bumped

    For any standard coupon or zero-coupon bond with positive face value
    and positive discount factors, ``dv01 > 0`` because bond prices fall as
    rates rise.

    Parameters
    ----------
    bond : FixedRateBond
        Fully-specified bond instrument.
    curve : DiscountCurve
        Discount curve evaluated at the same valuation date as *bond*.
        The curve must cover all remaining payment dates.
    bump_bps : int | float
        Bump size in basis points.  Must be positive.  Default: 1.

    Returns
    -------
    float
        DV01 in the same currency units as ``bond.face_value``.
        Always >= 0 for a valid bond and curve.

    Raises
    ------
    ValueError
        If ``bump_bps <= 0``, or if ``price_bond`` raises (e.g. the curve
        does not cover all payment dates).
    """
    if bump_bps <= 0:
        raise ValueError(f"bump_bps must be positive; got {bump_bps}")

    base_result = price_bond(bond, curve)
    bumped_curve = _parallel_bump_curve(curve, float(bump_bps))
    bumped_result = price_bond(bond, bumped_curve)

    return base_result.dirty_price - bumped_result.dirty_price


def modified_duration(
    bond: FixedRateBond,
    curve: DiscountCurve,
    bump_bps: int | float = 1,
) -> float:
    """
    Compute the modified duration of a fixed-rate bond.

    Modified duration is derived from DV01 via the standard relationship::

        modified_duration = dv01 / dirty_price_base * 10_000

    This is consistent with the definition::

        dv01 ≈ modified_duration * dirty_price / 10_000

    For a ``dirty_price_base < 1e-12`` (effectively zero), ``0.0`` is returned.
    This edge case is unreachable for any valid :class:`FixedRateBond` with
    positive face value and a well-formed curve.

    Parameters
    ----------
    bond : FixedRateBond
        Fully-specified bond instrument.
    curve : DiscountCurve
        Discount curve evaluated at the same valuation date as *bond*.
    bump_bps : int | float
        Bump size forwarded to :func:`bond_dv01`.  Default: 1.

    Returns
    -------
    float
        Modified duration in years.  Always >= 0.  Typically in [0, maturity_years].

    Raises
    ------
    ValueError
        If ``bump_bps <= 0`` or if pricing fails.
    """
    base_dirty = price_bond(bond, curve).dirty_price
    if base_dirty < _MIN_PRICE_GUARD:
        return 0.0

    dv01 = bond_dv01(bond, curve, bump_bps)
    return dv01 / base_dirty * 10_000.0


def bond_convexity(
    bond: FixedRateBond,
    curve: DiscountCurve,
    bump_bps: int | float = 1,
) -> float:
    """
    Compute the convexity of a fixed-rate bond using central finite differences.

    Convexity measures the curvature of the price-yield relationship — the
    second-order sensitivity of the bond price to a parallel shift in
    continuously-compounded zero rates.

    **Formula** (central difference, parallel CC zero-rate bump)::

        dy = bump_bps / 10_000
        convexity = (P_minus + P_plus - 2 * P0) / (P0 * dy * dy)

    where:

    - ``P0``      — base dirty price (unshifted curve)
    - ``P_plus``  — dirty price with all CC zero rates shifted by +dy
    - ``P_minus`` — dirty price with all CC zero rates shifted by -dy

    The result is dimensionless (years²) and always positive for a standard
    coupon or zero-coupon bond with positive face value.

    Methodology consistency
    -----------------------
    Uses the same :func:`_parallel_bump_curve` helper that underlies
    :func:`bond_dv01` and :func:`modified_duration`.  The original curve
    is never mutated.

    Parameters
    ----------
    bond : FixedRateBond
        Fully-specified bond instrument.
    curve : DiscountCurve
        Discount curve at the same valuation date as *bond*.
    bump_bps : int | float
        Bump size in basis points for the central-difference perturbation.
        Default: 1.  Must be positive.

    Returns
    -------
    float
        Convexity in years².  Always > 0 for a valid bond.

    Raises
    ------
    ValueError
        If ``bump_bps <= 0``.
        If the base dirty price is effectively zero (< ``_MIN_PRICE_GUARD``),
        convexity is undefined and a ``ValueError`` is raised.
    """
    if bump_bps <= 0:
        raise ValueError(f"bump_bps must be positive; got {bump_bps}")

    base_dirty = price_bond(bond, curve).dirty_price
    if base_dirty < _MIN_PRICE_GUARD:
        raise ValueError(
            f"Base dirty price ({base_dirty}) is effectively zero; "
            "convexity is undefined for a zero-priced bond."
        )

    curve_plus = _parallel_bump_curve(curve, float(bump_bps))
    curve_minus = _parallel_bump_curve(curve, -float(bump_bps))

    p_plus = price_bond(bond, curve_plus).dirty_price
    p_minus = price_bond(bond, curve_minus).dirty_price

    dy = bump_bps / 10_000.0
    return (p_minus + p_plus - 2.0 * base_dirty) / (base_dirty * dy * dy)


def macaulay_duration(
    bond: FixedRateBond,
    curve: DiscountCurve,
) -> float:
    """
    Compute the Macaulay Duration of a fixed-rate bond.

    Macaulay Duration is the weighted-average time to receipt of all
    remaining discounted cashflows::

        D_mac = sum(t_i * PV_i) / sum(PV_i)

    where:

    - ``t_i`` is the year fraction from *valuation_date* to the i-th
      cashflow date, computed using the bond\'s own day-count convention
      (same convention applied by :func:`~quant_core.pricing.bond_pricer.price_bond`).
    - ``PV_i`` is the discounted present value of the i-th cashflow:
      ``CF_i * curve.df(payment_date_i)``.
    - The denominator ``sum(PV_i)`` equals the bond\'s dirty price — it is
      computed directly here to avoid a second full pricing call.

    Cashflows enumerated
    --------------------
    For a coupon bond:

    - Each remaining coupon: ``face_value * coupon_rate * tau_period``
      discounted to *valuation_date*.
    - Final principal: ``face_value`` discounted to *valuation_date*.

    For a zero-coupon bond:

    - Single cashflow ``face_value`` at *maturity_date*.
    - Macaulay Duration equals the year fraction to *maturity_date*
      (exactly the remaining life, since there is only one cashflow).

    Time convention
    ---------------
    Year fractions for *t_i* use the bond\'s own :attr:`~FixedRateBond.day_count`
    measured from *valuation_date* to each payment date.  This matches the
    discount factors in the curve and is consistent with the accrual fractions
    used by :func:`price_bond`.

    Relationship to modified duration
    ----------------------------------
    For a bond priced at yield *y* (flat-rate simple convention)::

        modified_duration = D_mac / (1 + y * tau_period)

    The numerical identity ``modified_duration <= D_mac`` holds for any
    positive yield.

    Parameters
    ----------
    bond : FixedRateBond
        Fully-specified bond instrument.
    curve : DiscountCurve
        Discount curve at the same valuation date as *bond*.  The curve must
        cover all remaining payment dates.

    Returns
    -------
    float
        Macaulay Duration in years.  Always positive for a valid bond.

    Raises
    ------
    ValueError
        If there are no remaining cashflows.
        If the total PV of cashflows is effectively zero (< ``_MIN_PRICE_GUARD``).
    """
    val_date = bond.valuation_date

    # ------------------------------------------------------------------ #
    # Zero-coupon bond: single cashflow at maturity                       #
    # ------------------------------------------------------------------ #
    if bond.coupon_rate == 0.0:
        t = accrual_fraction(val_date, bond.maturity_date, bond.day_count)
        if t <= 0.0:
            raise ValueError(
                "No remaining cashflows: maturity_date is not after valuation_date."
            )
        # PV cancels in numerator and denominator; D_mac == t.
        return t

    # ------------------------------------------------------------------ #
    # Coupon bond: enumerate all remaining cashflows                      #
    # ------------------------------------------------------------------ #
    all_coupon_dates = _coupon_schedule(
        bond.issue_date, bond.maturity_date, bond.coupon_frequency
    )
    period_starts = [bond.issue_date] + all_coupon_dates[:-1]

    remaining = [
        (ps, pe)
        for ps, pe in zip(period_starts, all_coupon_dates)
        if pe > val_date
    ]

    if not remaining:
        raise ValueError(
            "No remaining cashflows: all coupon dates are on or before valuation_date."
        )

    weighted_sum = 0.0
    pv_sum = 0.0

    for ps, pe in remaining:
        tau_period = accrual_fraction(ps, pe, bond.day_count)
        cf = bond.face_value * bond.coupon_rate * tau_period
        t = accrual_fraction(val_date, pe, bond.day_count)
        pv_cf = cf * curve.df(pe)
        weighted_sum += t * pv_cf
        pv_sum += pv_cf

    # Principal cashflow at maturity (always remaining since maturity > val_date).
    t_mat = accrual_fraction(val_date, bond.maturity_date, bond.day_count)
    pv_principal = bond.face_value * curve.df(bond.maturity_date)
    weighted_sum += t_mat * pv_principal
    pv_sum += pv_principal

    if pv_sum < _MIN_PRICE_GUARD:
        raise ValueError(
            f"Total PV of cashflows ({pv_sum}) is effectively zero; "
            "Macaulay Duration is undefined."
        )

    return weighted_sum / pv_sum
