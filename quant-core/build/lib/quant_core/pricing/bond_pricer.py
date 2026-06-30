"""
bond_pricer — Deterministic fixed-rate bond pricer.

Prices a :class:`~quant_core.instruments.bond.FixedRateBond` against a
:class:`~quant_core.curves.discount_curve.DiscountCurve` using exact
discounted-cashflow (DCF) methodology:

**Coupon cashflows**::

    CF_i = face_value × coupon_rate × τ_i

where τ_i = accrual_fraction(period_start_i, period_end_i, bond.day_count)
and period_end_i is the i-th coupon payment date.

**Principal cashflow**::

    CF_principal = face_value   (paid at maturity_date)

**Dirty price** (full price)::

    dirty_price = Σ_i CF_i × df(period_end_i)   [remaining coupons only]
                + face_value × df(maturity_date)

where "remaining" means payment date strictly after *valuation_date*.

**Accrued interest**::

    accrued_interest = face_value × coupon_rate
                       × accrual_fraction(last_coupon_date, valuation_date,
                                          bond.day_count)

where *last_coupon_date* is the most recent coupon date on or before
*valuation_date* (or *issue_date* if *valuation_date* falls in the first
coupon period).

**Clean price** (quoted price)::

    clean_price = dirty_price - accrued_interest

**Zero-coupon bonds** (``coupon_rate == 0``): a single cashflow of
``face_value`` at *maturity_date*; ``accrued_interest`` and
``n_remaining_coupons`` are both 0.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from quant_core.conventions.day_count import DayCount, accrual_fraction
from quant_core.curves.build_flat import flat_curve
from quant_core.curves.discount_curve import DiscountCurve
from quant_core.instruments.bond import FixedRateBond
from quant_core.utils.date_utils import add_months

# Coupon period step in months for each supported frequency.
FREQ_MONTHS: dict[str, int] = {
    "annual": 12,
    "semiannual": 6,
    "quarterly": 3,
}


@dataclass
class BondCashflowRow:
    """
    Single cashflow row returned by :func:`bond_cashflow_schedule`.

    Attributes
    ----------
    payment_date : date
        Date on which the cashflow is paid.
    accrual_start : date
        Start of the accrual period for this coupon.
    accrual_end : date
        End of the accrual period (== payment_date for coupon bonds).
    year_fraction : float
        Day-count fraction for the accrual period under the bond's convention.
    coupon_cashflow : float
        Coupon amount for this period (0 for zero-coupon bonds).
    principal_cashflow : float
        Principal repayment at this date (non-zero only on final cashflow).
    total_cashflow : float
        ``coupon_cashflow + principal_cashflow``.
    discount_factor : float
        Discount factor from *valuation_date* to *payment_date*.
    pv_cashflow : float
        ``total_cashflow × discount_factor``.
    time_to_payment_years : float
        Year fraction from *valuation_date* to *payment_date* under the
        bond's day-count convention.
    """

    payment_date: date
    accrual_start: date
    accrual_end: date
    year_fraction: float
    coupon_cashflow: float
    principal_cashflow: float
    total_cashflow: float
    discount_factor: float
    pv_cashflow: float
    time_to_payment_years: float


@dataclass
class BondResult:
    """
    Pricing output for a :class:`~quant_core.instruments.bond.FixedRateBond`.

    Attributes
    ----------
    dirty_price : float
        Present value of all remaining cashflows (coupon payments plus
        principal repayment).  Also known as the *full price*.
    clean_price : float
        ``dirty_price`` minus ``accrued_interest``.  This is the conventional
        *quoted price* for bonds.
    accrued_interest : float
        Coupon accrued from the last coupon date (or *issue_date* if in the
        first coupon period) to *valuation_date*.  Always >= 0.
    pv_cashflows : float
        Present value of all remaining cashflows.  Equal to ``dirty_price``;
        provided as a named alias for clarity in cashflow analysis.
    n_remaining_coupons : int
        Number of coupon payment dates strictly after *valuation_date*.
        Zero for zero-coupon bonds.
    """

    dirty_price: float
    clean_price: float
    accrued_interest: float
    pv_cashflows: float
    n_remaining_coupons: int


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _build_cashflows(
    bond: FixedRateBond,
    curve: DiscountCurve,
) -> list[BondCashflowRow]:
    """
    Build the list of remaining discounted cashflow rows for *bond*.

    Used internally by both :func:`price_bond` and
    :func:`bond_cashflow_schedule` so that both share identical maths.

    Only cashflows with payment date **strictly after** *bond.valuation_date*
    are included.  The final row always carries the full principal repayment.
    """
    rows: list[BondCashflowRow] = []

    # ------------------------------------------------------------------ #
    # Zero-coupon bond: single cashflow only                              #
    # ------------------------------------------------------------------ #
    if bond.coupon_rate == 0.0:
        df = curve.df(bond.maturity_date)
        rows.append(
            BondCashflowRow(
                payment_date=bond.maturity_date,
                accrual_start=bond.issue_date,
                accrual_end=bond.maturity_date,
                year_fraction=accrual_fraction(
                    bond.issue_date, bond.maturity_date, bond.day_count
                ),
                coupon_cashflow=0.0,
                principal_cashflow=bond.face_value,
                total_cashflow=bond.face_value,
                discount_factor=df,
                pv_cashflow=bond.face_value * df,
                time_to_payment_years=accrual_fraction(
                    bond.valuation_date, bond.maturity_date, bond.day_count
                ),
            )
        )
        return rows

    # ------------------------------------------------------------------ #
    # Coupon bond: one row per remaining coupon period                    #
    # ------------------------------------------------------------------ #
    all_coupon_dates = _coupon_schedule(
        bond.issue_date, bond.maturity_date, bond.coupon_frequency
    )
    period_starts = [bond.issue_date] + all_coupon_dates[:-1]

    remaining = [
        (ps, pe)
        for ps, pe in zip(period_starts, all_coupon_dates)
        if pe > bond.valuation_date
    ]

    for ps, pe in remaining:
        tau = accrual_fraction(ps, pe, bond.day_count)
        cpn = bond.face_value * bond.coupon_rate * tau
        principal = bond.face_value if pe == bond.maturity_date else 0.0
        total = cpn + principal
        df = curve.df(pe)
        rows.append(
            BondCashflowRow(
                payment_date=pe,
                accrual_start=ps,
                accrual_end=pe,
                year_fraction=tau,
                coupon_cashflow=cpn,
                principal_cashflow=principal,
                total_cashflow=total,
                discount_factor=df,
                pv_cashflow=total * df,
                time_to_payment_years=accrual_fraction(
                    bond.valuation_date, pe, bond.day_count
                ),
            )
        )

    return rows


def _coupon_schedule(
    issue_date: date,
    maturity_date: date,
    coupon_frequency: str,
) -> list[date]:
    """
    Generate all coupon dates from first coupon through (and including) maturity.

    Steps forward from *issue_date* by the coupon period using month
    arithmetic via :func:`~quant_core.utils.date_utils.add_months`.
    *maturity_date* is always the final element regardless of step alignment.

    Parameters
    ----------
    issue_date : date
        Bond issue date (start of first accrual period).
    maturity_date : date
        Bond maturity / final redemption date.
    coupon_frequency : str
        ``"annual"``, ``"semiannual"``, or ``"quarterly"``.

    Returns
    -------
    list[date]
        Strictly increasing list of coupon dates from first coupon to
        maturity (inclusive).
    """
    step = FREQ_MONTHS[coupon_frequency]
    dates: list[date] = []
    i = 1
    while True:
        d = add_months(issue_date, i * step)
        if d >= maturity_date:
            break
        dates.append(d)
        i += 1
    dates.append(maturity_date)
    return dates


def _accrued_interest(bond: FixedRateBond) -> float:
    """
    Compute the accrued interest from the last coupon date to *valuation_date*.

    Returns 0.0 for zero-coupon bonds and when *valuation_date* is at or
    before *issue_date* (bond not yet accruing).

    The coupon period containing *valuation_date* is identified by finding
    the unique interval [period_start, period_end) where period_start <=
    valuation_date < period_end.  Accrued interest equals::

        face_value × coupon_rate
        × accrual_fraction(period_start, valuation_date, day_count)

    When *valuation_date* falls exactly on a coupon payment date, the
    period start equals *valuation_date* and the accrual fraction is zero,
    so accrued interest is correctly 0 (coupon was just paid).
    """
    if bond.coupon_rate == 0.0:
        return 0.0
    if bond.valuation_date <= bond.issue_date:
        return 0.0

    all_coupon_dates = _coupon_schedule(
        bond.issue_date, bond.maturity_date, bond.coupon_frequency
    )
    period_starts = [bond.issue_date] + all_coupon_dates[:-1]

    for ps, pe in zip(period_starts, all_coupon_dates):
        if ps <= bond.valuation_date < pe:
            tau = accrual_fraction(ps, bond.valuation_date, bond.day_count)
            return bond.face_value * bond.coupon_rate * tau

    # valuation_date == maturity_date: final coupon was just paid.
    return 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def price_bond(bond: FixedRateBond, curve: DiscountCurve) -> BondResult:
    """
    Price a :class:`~quant_core.instruments.bond.FixedRateBond` off a
    :class:`~quant_core.curves.discount_curve.DiscountCurve`.

    Parameters
    ----------
    bond : FixedRateBond
        Fully-specified bond instrument.
    curve : DiscountCurve
        Discount curve evaluated at *curve.valuation_date*.  The curve must
        cover all remaining payment dates; if any required date falls outside
        ``[first_pillar, last_pillar]`` the underlying
        :meth:`~DiscountCurve.df` call will raise ``ValueError``.

    Returns
    -------
    BondResult
        Full price decomposition: dirty price, clean price, accrued interest,
        and remaining coupon count.

    Notes
    -----
    The ``dirty_price`` and ``pv_cashflows`` fields are numerically identical.
    Both are the sum of discounted remaining cashflows (coupons + principal).

    Spot-settled bonds (*valuation_date* == *issue_date*) have zero accrued
    interest, so ``clean_price`` == ``dirty_price`` on that date.

    The *maturity_date* is always > *valuation_date* by :class:`FixedRateBond`
    validation, so the principal cashflow is always included in the PV sum.
    """
    rows = _build_cashflows(bond, curve)

    # ------------------------------------------------------------------ #
    # Zero-coupon bond                                                    #
    # ------------------------------------------------------------------ #
    if bond.coupon_rate == 0.0:
        pv = rows[0].pv_cashflow
        return BondResult(
            dirty_price=pv,
            clean_price=pv,
            accrued_interest=0.0,
            pv_cashflows=pv,
            n_remaining_coupons=0,
        )

    # ------------------------------------------------------------------ #
    # Coupon bond                                                         #
    # ------------------------------------------------------------------ #
    pv = sum(r.pv_cashflow for r in rows)
    accrued = _accrued_interest(bond)
    return BondResult(
        dirty_price=pv,
        clean_price=pv - accrued,
        accrued_interest=accrued,
        pv_cashflows=pv,
        n_remaining_coupons=len(rows),
    )


def solve_bond_ytm(
    bond: FixedRateBond,
    market_dirty_price: float,
    day_count: DayCount | None = None,
    coupon_frequency: str | None = None,
    tol: float = 1e-10,
    max_iter: int = 200,
) -> float:
    """
    Solve for the flat annual yield-to-maturity (YTM) of a fixed-rate bond.

    Finds a flat annual yield *y* such that::

        price_bond(bond, flat_curve(bond.valuation_date, y, tenor, freq, dc)).dirty_price
            == market_dirty_price

    The discount convention matches :func:`~quant_core.curves.build_flat.flat_curve`:
    ``df(t) = 1 / (1 + y × τ)`` where *τ* is the year fraction from
    ``bond.valuation_date`` to *t* under the day-count convention.

    A deterministic **bisection** method is used.  The search bracket is
    ``[0.0, 1.0]`` (i.e. 0 – 100 %).  If the market price falls below the
    theoretical price at 100 % yield, the upper bound is expanded to 5.0 (500 %).
    If the root is still not bracketed a :class:`ValueError` is raised.

    Parameters
    ----------
    bond : FixedRateBond
        Fully-specified bond instrument.
    market_dirty_price : float
        Observed market dirty (full) price.  Must be strictly positive.
    day_count : DayCount | None, optional
        Day-count convention for the flat curve.  Defaults to ``bond.day_count``.
    coupon_frequency : str | None, optional
        Frequency label for the flat curve pillar grid.  Defaults to
        ``bond.coupon_frequency``.
    tol : float, optional
        Convergence tolerance in price units.  Bisection stops when either
        ``|f(mid)| < tol`` or the bracket width ``(high - low) < tol``.
        Defaults to ``1e-10``.
    max_iter : int, optional
        Maximum number of bisection iterations.  Defaults to 200.

    Returns
    -------
    float
        Flat annual yield (e.g. 0.08 for 8 %).

    Raises
    ------
    ValueError
        If ``market_dirty_price <= 0``, or if no root can be bracketed within
        the expanded bounds, indicating an unrealistic market price.
    """
    if market_dirty_price <= 0.0:
        raise ValueError(
            f"market_dirty_price must be > 0; got {market_dirty_price}"
        )

    _dc = day_count if day_count is not None else bond.day_count
    _freq = coupon_frequency if coupon_frequency is not None else bond.coupon_frequency

    # Tenor covering the full remaining bond life (ceiling division).
    delta_days = (bond.maturity_date - bond.valuation_date).days
    _tenor = max(1, -(-delta_days // 365))

    def _price_at_yield(y: float) -> float:
        curve = flat_curve(bond.valuation_date, y, _tenor, _freq, _dc)
        return price_bond(bond, curve).dirty_price

    # f(y) = price(y) - market_dirty_price.
    # Bond price is monotonically decreasing in yield (simple-rate), so:
    #   f(low) > 0  ← low yield produces a higher price
    #   f(high) < 0 ← high yield produces a lower price
    low, high = 0.0, 1.0
    f_low = _price_at_yield(low) - market_dirty_price
    f_high = _price_at_yield(high) - market_dirty_price

    # Expand upper bound for very deeply discounted bonds.
    if f_high > 0.0:
        high = 5.0
        f_high = _price_at_yield(high) - market_dirty_price

    if f_low * f_high >= 0.0:
        raise ValueError(
            f"Cannot bracket YTM root in [0.0, {high}]: "
            f"price(0%) = {_price_at_yield(0.0):.4f}, "
            f"price({high * 100:.0f}%) = {_price_at_yield(high):.4f}, "
            f"market_dirty_price = {market_dirty_price:.4f}. "
            "Verify that market_dirty_price is a realistic price for this bond."
        )

    for _ in range(max_iter):
        mid = 0.5 * (low + high)
        f_mid = _price_at_yield(mid) - market_dirty_price
        if abs(f_mid) < tol or (high - low) < tol:
            return mid
        if f_low * f_mid < 0.0:
            high = mid
            f_high = f_mid
        else:
            low = mid
            f_low = f_mid

    return 0.5 * (low + high)


def bond_cashflow_schedule(
    bond: FixedRateBond,
    curve: DiscountCurve,
) -> list[BondCashflowRow]:
    """
    Return the full remaining cashflow schedule for *bond* discounted off
    *curve*.

    Each row in the returned list represents one payment date.  For coupon
    bonds this is one row per remaining coupon period; the final row also
    carries the principal repayment.  For zero-coupon bonds there is exactly
    one row with ``coupon_cashflow == 0`` and ``principal_cashflow == face_value``.

    Only cashflows with payment date **strictly after** ``bond.valuation_date``
    are included (matching the coverage of :func:`price_bond`).

    Parameters
    ----------
    bond : FixedRateBond
        Fully-specified bond instrument.
    curve : DiscountCurve
        Discount curve evaluated at ``curve.valuation_date``.

    Returns
    -------
    list[BondCashflowRow]
        Chronologically ordered cashflow rows.  The sum of
        ``row.pv_cashflow`` across all rows equals the bond's ``dirty_price``.
    """
    return _build_cashflows(bond, curve)
