from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, HTTPException

from app.schemas.curve import (
    CurveRequest,
    CurveResponse,
    MixedCurveRequest,
    MixedCurveResponse,
)
from quant_core.conventions.day_count import DayCount
from quant_core.curves.bootstrap_mixed import (
    bootstrap_discount_curve_from_market_records,
)
from quant_core.curves.bootstrap_swap import bootstrap_discount_curve_from_swaps
from quant_core.marketdata.normalize_rates import normalize_market_quotes
from quant_core.schemas.market_inputs import (
    DepositQuote,
    FRAQuote,
    ParSwapQuote,
)

router = APIRouter(tags=["curve"])

# ---------------------------------------------------------------------------
# Shared parameter maps
# ---------------------------------------------------------------------------

_DAY_COUNT_MAP: dict[str, DayCount] = {
    "ACT_365F": DayCount.ACT_365F,
    "ACT_360": DayCount.ACT_360,
    "30_360": DayCount.THIRTY_360,
    "ACT_ACT_ISDA": DayCount.ACT_ACT_ISDA,
}

_SUPPORTED_FREQUENCIES: frozenset[str] = frozenset(
    {"annual", "semiannual", "quarterly", "monthly"}
)


# ---------------------------------------------------------------------------
# Existing swap-only endpoint — UNCHANGED
# ---------------------------------------------------------------------------


@router.post("/curve/swap", response_model=CurveResponse)
def bootstrap_curve(request: CurveRequest) -> CurveResponse:
    """
    Bootstrap a discount curve from a ladder of par vanilla swap quotes.

    The endpoint solves discount factors sequentially from the shortest to the
    longest tenor using the algebraic par-swap identity (Newton's method for
    non-contiguous ladders).  The resulting pillar dates and discount factors are
    returned for downstream use.

    Returns HTTP 422 on any invalid input (empty quote list, duplicate tenors,
    out-of-range rates/tenors, unsupported frequency or day-count convention).
    """
    # ------------------------------------------------------------------
    # Validate frequency and day-count before delegating to quant-core
    # ------------------------------------------------------------------
    if request.payment_frequency not in _SUPPORTED_FREQUENCIES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unsupported payment_frequency '{request.payment_frequency}'. "
                f"Supported values: {sorted(_SUPPORTED_FREQUENCIES)}."
            ),
        )

    day_count = _DAY_COUNT_MAP.get(request.day_count)
    if day_count is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unsupported day_count '{request.day_count}'. "
                f"Supported values: {sorted(_DAY_COUNT_MAP.keys())}."
            ),
        )

    # ------------------------------------------------------------------
    # Convert request inputs to quant-core domain objects
    # ValueError from ParSwapQuote.__post_init__ → 422
    # ------------------------------------------------------------------
    try:
        quotes = [
            ParSwapQuote(tenor_years=q.tenor_years, par_rate=q.par_rate)
            for q in request.swap_quotes
        ]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------
    valuation_date = date.today()

    try:
        curve = bootstrap_discount_curve_from_swaps(
            valuation_date=valuation_date,
            swap_quotes=quotes,
            payment_frequency=request.payment_frequency,
            day_count=day_count,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return CurveResponse(
        request_id=str(uuid.uuid4()),
        valuation_date=valuation_date.isoformat(),
        pillar_dates=[d.isoformat() for d in curve.pillar_dates],
        discount_factors=list(curve.discount_factors),
        status="ok",
        warnings=[],
    )


# ---------------------------------------------------------------------------
# Mixed-instrument endpoint — Step 9
# ---------------------------------------------------------------------------


@router.post("/curve", response_model=MixedCurveResponse)
def bootstrap_mixed_curve(request: MixedCurveRequest) -> MixedCurveResponse:
    """
    Bootstrap a discount curve from a mixed ladder of deposit, FRA, and
    par-swap market quotes.

    At least one of ``deposits``, ``fras``, or ``swaps`` must be non-empty.
    Records are sorted by instrument type (deposits first, FRAs second, swaps
    last) inside quant-core before solving, so the caller may supply them in
    any order.

    Returns HTTP 422 on invalid inputs or bootstrap failures.
    """
    # ------------------------------------------------------------------
    # Validate payment_frequency and day_count
    # ------------------------------------------------------------------
    if request.payment_frequency not in _SUPPORTED_FREQUENCIES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unsupported payment_frequency '{request.payment_frequency}'. "
                f"Supported values: {sorted(_SUPPORTED_FREQUENCIES)}."
            ),
        )

    day_count = _DAY_COUNT_MAP.get(request.day_count)
    if day_count is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unsupported day_count '{request.day_count}'. "
                f"Supported values: {sorted(_DAY_COUNT_MAP.keys())}."
            ),
        )

    # ------------------------------------------------------------------
    # Reject if all instrument lists are empty / absent
    # ------------------------------------------------------------------
    has_deposits = bool(request.deposits)
    has_fras = bool(request.fras)
    has_swaps = bool(request.swaps)

    if not (has_deposits or has_fras or has_swaps):
        raise HTTPException(
            status_code=422,
            detail=(
                "At least one of 'deposits', 'fras', or 'swaps' must be "
                "provided and non-empty."
            ),
        )

    # ------------------------------------------------------------------
    # Parse valuation_date (default = today)
    # ------------------------------------------------------------------
    if request.valuation_date is not None:
        try:
            valuation_date = date.fromisoformat(request.valuation_date)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid valuation_date format: {exc}",
            ) from exc
    else:
        valuation_date = date.today()

    # ------------------------------------------------------------------
    # Convert backend request items → quant-core domain objects
    # ValueError from dataclass __post_init__ → 422
    # ------------------------------------------------------------------
    try:
        deposit_quotes = [
            DepositQuote(tenor_months=d.tenor_months, rate=d.rate)
            for d in (request.deposits or [])
        ]
        fra_quotes = [
            FRAQuote(start_months=f.start_months, end_months=f.end_months, rate=f.rate)
            for f in (request.fras or [])
        ]
        swap_quotes = [
            ParSwapQuote(tenor_years=s.tenor_years, par_rate=s.par_rate)
            for s in (request.swaps or [])
        ]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # Normalize into NormalizedRateRecord sequence
    # ValueError from duplicate detection → 422
    # ------------------------------------------------------------------
    try:
        records = normalize_market_quotes(
            deposits=deposit_quotes,
            fras=fra_quotes,
            swaps=swap_quotes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # Bootstrap
    # ValueError from bootstrap engine (bad inputs, unsolvable curve) → 422
    # ------------------------------------------------------------------
    try:
        curve = bootstrap_discount_curve_from_market_records(
            valuation_date=valuation_date,
            records=records,
            payment_frequency=request.payment_frequency,
            day_count=day_count,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    pillar_dates_iso = [d.isoformat() for d in curve.pillar_dates]
    dfs = list(curve.discount_factors)

    return MixedCurveResponse(
        request_id=str(uuid.uuid4()),
        valuation_date=valuation_date.isoformat(),
        pillar_dates=pillar_dates_iso,
        discount_factors=dfs,
        n_pillars=len(dfs),
        status="ok",
        warnings=[],
    )
