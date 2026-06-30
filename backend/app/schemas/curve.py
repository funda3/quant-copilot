from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Existing swap-only schemas — UNCHANGED for backward compatibility
# ---------------------------------------------------------------------------


class CurveQuoteInput(BaseModel):
    """A single par-swap market quote: tenor in whole years and par rate as a decimal."""

    tenor_years: int
    par_rate: float


class CurveRequest(BaseModel):
    """
    Request body for POST /curve (swap-only, legacy endpoint).

    swap_quotes     : Ladder of par-swap quotes (at least one, no duplicate tenors).
    payment_frequency : Fixed-leg payment frequency.  One of: annual, semiannual,
                        quarterly, monthly.  Defaults to "annual".
    day_count       : Day-count convention string.  One of: ACT_365F, ACT_360,
                        30_360, ACT_ACT_ISDA.  Defaults to "ACT_365F".
    """

    swap_quotes: List[CurveQuoteInput]
    payment_frequency: str = "annual"
    day_count: str = "ACT_365F"


class CurveResponse(BaseModel):
    """Response body for POST /curve (swap-only, legacy endpoint)."""

    request_id: str
    valuation_date: str          # ISO-8601 date used as bootstrap anchor
    pillar_dates: List[str]      # ISO-8601 dates of solved pillars
    discount_factors: List[float]
    status: str                  # "ok"
    warnings: List[str]


# ---------------------------------------------------------------------------
# Mixed-instrument schemas — Step 9
# ---------------------------------------------------------------------------


class DepositInput(BaseModel):
    """A single cash-deposit / money-market quote."""

    tenor_months: int
    rate: float


class FRAInput(BaseModel):
    """A single Forward Rate Agreement quote."""

    start_months: int
    end_months: int
    rate: float


class SwapInput(BaseModel):
    """A single par-swap quote for the mixed bootstrap."""

    tenor_years: int
    par_rate: float


class MixedCurveRequest(BaseModel):
    """
    Request body for POST /api/mixed-curve.

    At least one of ``deposits``, ``fras``, or ``swaps`` must be non-empty.
    All rates are decimals (e.g. 0.08 for 8 %).

    valuation_date    : ISO-8601 date string (e.g. "2024-01-15").
                        If omitted, defaults to today.
    payment_frequency : Fixed-leg coupon frequency for swap records.
                        One of: annual, semiannual, quarterly, monthly.
                        Defaults to "annual".
    day_count         : Day-count convention string.
                        One of: ACT_365F, ACT_360, 30_360, ACT_ACT_ISDA.
                        Defaults to "ACT_365F".
    deposits          : List of cash-deposit quotes (optional).
    fras              : List of FRA quotes (optional).
    swaps             : List of par-swap quotes (optional).
    """

    valuation_date: Optional[str] = None
    payment_frequency: str = "annual"
    day_count: str = "ACT_365F"
    deposits: Optional[List[DepositInput]] = None
    fras: Optional[List[FRAInput]] = None
    swaps: Optional[List[SwapInput]] = None


class MixedCurveResponse(BaseModel):
    """Response body for POST /api/mixed-curve."""

    request_id: str
    valuation_date: str          # ISO-8601 date used as bootstrap anchor
    pillar_dates: List[str]      # ISO-8601 dates of solved pillars, ascending
    discount_factors: List[float]  # aligned with pillar_dates
    n_pillars: int
    status: str                  # "ok"
    warnings: List[str]
