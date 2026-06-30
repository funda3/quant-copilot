"""
ladder — Bucketed key-rate PV01 (DV01) for vanilla IRS.

For each tenor bucket a *single* pillar of the discount curve is identified
as the nearest-maturity pillar to that bucket date and is bumped by +1 bp in
continuously-compounded zero-rate space.  The swap is repriced on the bumped
curve and the signed PV change relative to the base price is returned as that
bucket's key-rate PV01.

Signed convention
-----------------
  bucket_pv01[label] = NPV_bumped − NPV_base

For a **payer** IRS (pay fixed, receive float): higher rates increase NPV
→ each bucket PV01 is **positive**.
For a **receiver** IRS: each bucket PV01 is **negative**.

Out-of-range rule
-----------------
If the calendar target date for a requested bucket lies strictly after the
last pillar of the supplied curve the bucket is included in the output dict
with value **0.0**.  This is explicit and deterministic; no extrapolation is
attempted.

Shared-pillar rule
------------------
If two bucket dates map to the same nearest pillar (sparse curve), the same
pillar bump result is returned for both.  This is intentional and explicit.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Optional

from quant_core.conventions.day_count import DayCount, accrual_fraction
from quant_core.curves.discount_curve import DiscountCurve
from quant_core.instruments.irs import VanillaIRS
from quant_core.pricing.irs_pricer import _price_irs_core  # noqa: PLC2701

# Bump size: +1 basis point in continuously-compounded zero-rate space.
_BUMP_1BP: float = 0.0001

# Default tenor bucket set (years).
_DEFAULT_BUCKET_YEARS: list[int] = [1, 2, 3, 5, 7, 10]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _bucket_label(years: int) -> str:
    """Return the canonical string label for an integer-year bucket."""
    return f"{years}Y"


def _bucket_target_date(valuation_date: date, bucket_years: int) -> date:
    """
    Return the approximate calendar date ``bucket_years`` years after
    *valuation_date*.

    Simple year-addition is used, matching the schedule-generation convention
    in :mod:`quant_core.conventions.schedule`.  The Feb-29 edge case is
    resolved by falling back to Feb 28 (same as ISO 8601 successor-month
    arithmetic).
    """
    try:
        return valuation_date.replace(year=valuation_date.year + bucket_years)
    except ValueError:
        # valuation_date is Feb 29 and the target year is not a leap year.
        return valuation_date.replace(
            year=valuation_date.year + bucket_years, day=28
        )


def _find_nearest_pillar_index(pillar_dates: list[date], target: date) -> int:
    """
    Return the index of the pillar date closest to *target* by calendar days.

    If two pillars are equidistant the lower index (earlier date) is preferred.
    """
    best_idx = 0
    best_diff = abs(pillar_dates[0].toordinal() - target.toordinal())
    for i in range(1, len(pillar_dates)):
        diff = abs(pillar_dates[i].toordinal() - target.toordinal())
        if diff < best_diff:
            best_diff = diff
            best_idx = i
    return best_idx


def _bump_single_pillar(
    curve: DiscountCurve,
    pillar_idx: int,
    bump_size: float,
    day_count: DayCount,
) -> DiscountCurve:
    """
    Return a new :class:`DiscountCurve` with only the pillar at *pillar_idx*
    bumped by *bump_size* in continuously-compounded zero-rate space.

    The bump formula (matching the parallel-shift convention in
    :func:`quant_core.pricing.irs_pricer._bump_curve`) is::

        df_bumped = df × exp(−bump_size × τ)

    where τ = accrual_fraction(valuation_date, pillar_date, day_count).
    All other pillars are returned unchanged.

    Parameters
    ----------
    curve : DiscountCurve
        Base curve.
    pillar_idx : int
        Zero-based index of the pillar to bump.
    bump_size : float
        Rate shift in decimal units (e.g. ``0.0001`` for +1 bp).
    day_count : DayCount
        Convention for τ — should match the swap day count so the bump is
        expressed in the same year-fraction units as the fixed-leg accrual.
    """
    val = curve.valuation_date
    new_dfs = list(curve.discount_factors)
    pillar_date = curve.pillar_dates[pillar_idx]
    tau = accrual_fraction(val, pillar_date, day_count)
    new_dfs[pillar_idx] = new_dfs[pillar_idx] * math.exp(-bump_size * tau)
    return DiscountCurve(val, curve.pillar_dates, new_dfs)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def pv01_ladder_irs(
    swap: VanillaIRS,
    curve: DiscountCurve,
    bucket_years: Optional[list[int]] = None,
) -> dict[str, float]:
    """
    Compute a bucketed key-rate PV01 ladder for a vanilla IRS.

    For each tenor bucket the nearest pillar of *curve* is found and bumped
    by +1 bp in continuously-compounded zero-rate space.  The swap is repriced
    on the bumped single-pillar curve and the signed PV change is returned.

    Parameters
    ----------
    swap : VanillaIRS
        Fully-specified IRS instrument.  The swap's ``day_count`` is used for
        the bump τ computation so that the bump convention is consistent with
        the fixed-leg accrual fractions.
    curve : DiscountCurve
        Discount curve for base pricing and pillar bumping.  Must cover all
        payment dates of *swap*.
    bucket_years : list[int] | None
        Integer tenor buckets in years.  All values must be positive.
        Defaults to ``[1, 2, 3, 5, 7, 10]``.

    Returns
    -------
    dict[str, float]
        Keys are ``"1Y"``, ``"2Y"``, … (one per requested bucket, in input
        order).  Values are signed PV changes (NPV_bumped − NPV_base) per
        +1 bp bump on the nearest pillar.

    Raises
    ------
    ValueError
        If *bucket_years* contains a non-positive or non-integer entry.

    Notes
    -----
    * **Sign convention**: payer PV01s are positive; receiver PV01s are negative.
    * **Out-of-range**: if the bucket target date lies strictly after the
      curve's last pillar the bucket value is ``0.0``.
    * **Shared pillars**: if two buckets map to the same nearest pillar the
      same PV change is returned for both; this is explicit and deterministic.
    """
    if bucket_years is None:
        bucket_years = _DEFAULT_BUCKET_YEARS

    for b in bucket_years:
        if not isinstance(b, int) or b <= 0:
            raise ValueError(
                f"bucket_years must contain positive integers; got {b!r}"
            )

    # Base NPV — use internal core to avoid computing the unnecessary
    # parallel PV01 that price_irs() adds on top.
    base_npv, _, _, _ = _price_irs_core(swap, curve)

    pillar_dates = curve.pillar_dates
    last_pillar = pillar_dates[-1]
    val_date = curve.valuation_date

    result: dict[str, float] = {}

    for years in bucket_years:
        label = _bucket_label(years)
        target = _bucket_target_date(val_date, years)

        # Out-of-range: bucket maturity beyond the curve domain → 0.0.
        if target > last_pillar:
            result[label] = 0.0
            continue

        idx = _find_nearest_pillar_index(pillar_dates, target)
        bumped_curve = _bump_single_pillar(curve, idx, _BUMP_1BP, swap.day_count)

        bumped_npv, _, _, _ = _price_irs_core(swap, bumped_curve)
        result[label] = bumped_npv - base_npv

    return result
