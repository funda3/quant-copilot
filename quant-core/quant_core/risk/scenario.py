"""
scenario — Parallel-shift scenario analysis for vanilla IRS.

For each requested shift level, all continuously-compounded zero rates of
the supplied discount curve are shifted in parallel by the shift amount and
the swap is repriced on the bumped curve.  No curve is mutated; each bumped
curve is a new DiscountCurve instance constructed by ``_bump_curve`` from
:mod:`quant_core.pricing.irs_pricer`.

Shift convention
----------------
  shift_bps > 0  → rates rise  → payer NPV increases, receiver NPV decreases
  shift_bps < 0  → rates fall  → payer NPV decreases, receiver NPV increases
  shift_bps = 0  → unchanged curve → returns base NPV (exp(0) = 1)

Label format
------------
  label = f"{shift_bps}bp"

  Examples:  "-200bp", "-100bp", "0bp", "50bp", "200bp"

The parallel bump reuses the same ``_bump_curve`` helper from
:mod:`quant_core.pricing.irs_pricer` (and the same ``_price_irs_core``
engine) so the scenario NPV is computed with exactly the same formula as
the base price, the PV01, and the single-pillar ladder bumps.
"""
from __future__ import annotations

from typing import Optional

from quant_core.curves.discount_curve import DiscountCurve
from quant_core.instruments.irs import VanillaIRS
from quant_core.pricing.irs_pricer import _bump_curve, _price_irs_core  # noqa: PLC2701

# 1 basis point in decimal.
_BUMP_1BP: float = 0.0001

# Default scenario shift set (basis points).
_DEFAULT_SHIFTS: list[int] = [-200, -100, -50, 0, 50, 100, 200]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _scenario_label(shift_bps: int) -> str:
    """Return the canonical string label for a shift in basis points."""
    return f"{shift_bps}bp"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_parallel_curve_scenarios_irs(
    swap: VanillaIRS,
    curve: DiscountCurve,
    shift_bps: Optional[list[int]] = None,
) -> dict[str, float]:
    """
    Reprice a vanilla IRS under a set of parallel curve shifts.

    For each shift *s* in *shift_bps* all continuously-compounded zero rates
    of *curve* are shifted in parallel by *s* basis points.  The original
    curve is never mutated; each shifted version is a new
    :class:`~quant_core.curves.discount_curve.DiscountCurve` instance.

    The bump formula (consistent with ``irs_pricer._bump_curve``) is::

        df_bumped_i = df_i × exp(−s × 0.0001 × τ_i)

    where τ_i = accrual_fraction(valuation_date, pillar_i, swap.day_count).

    Parameters
    ----------
    swap : VanillaIRS
        Fully-specified IRS instrument.  The swap's ``day_count`` is used
        for the zero-rate accrual fractions so the bump convention is
        consistent with the fixed-leg accrual fractions.
    curve : DiscountCurve
        Base discount curve.  Must cover all payment dates of *swap*.
    shift_bps : list[int] | None
        Integer shift values in basis points.  May include negative values
        (rate falls), zero (base case), and positive values (rate rises).
        Defaults to ``[-200, -100, -50, 0, 50, 100, 200]``.

    Returns
    -------
    dict[str, float]
        Keys are formatted as ``f"{shift_bps}bp"`` (e.g. ``"-200bp"``,
        ``"0bp"``, ``"200bp"``), in the same order as *shift_bps*.
        Values are the NPV of *swap* priced on the correspondingly shifted
        curve.

    Notes
    -----
    * For *shift_bps = 0* the result is equivalent to re-pricing on the
      original curve (base NPV), since ``exp(0) = 1`` leaves all discount
      factors unchanged.
    * The same ``_price_irs_core`` function used by :func:`price_irs` and
      :func:`pv01_ladder_irs` is used here, guaranteeing pricing consistency
      across all three functions.
    * Negative shifts (rate falls) produce bumped curves with higher discount
      factors.  For a payer IRS this decreases NPV.
    """
    if shift_bps is None:
        shift_bps = _DEFAULT_SHIFTS

    result: dict[str, float] = {}
    for shift in shift_bps:
        bump_size = shift * _BUMP_1BP
        bumped_curve = _bump_curve(curve, bump_size, swap.day_count)
        npv, _, _, _ = _price_irs_core(swap, bumped_curve)
        result[_scenario_label(shift)] = npv

    return result
