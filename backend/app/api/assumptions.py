from __future__ import annotations

from fastapi import APIRouter

from app.schemas.assumptions import AssumptionsResponse, FixedRateBounds, NotionalBounds, TenorBoundsYears
from app.services.pricer import (
    _DEFAULT_FIXED_RATE,
    _FIXED_RATE_MAX_EXCLUSIVE,
    _FIXED_RATE_MIN_EXCLUSIVE,
    _FLAT_MARKET_RATE,
    _NOTIONAL_MAX_INCLUSIVE,
    _NOTIONAL_MIN_INCLUSIVE,
    _SUPPORTED_CURRENCIES,
    _SUPPORTED_DIRECTIONS,
    _SUPPORTED_FREQUENCIES,
    _SUPPORTED_INDICES,
    _SUPPORTED_INSTRUMENTS,
    _TENOR_MAX_YEARS_INCLUSIVE,
    _TENOR_MIN_YEARS_INCLUSIVE,
)

router = APIRouter(tags=["assumptions"])


_RESPONSE = AssumptionsResponse(
    pricing_model="quant_core_flat_curve_irs_indicative_v2",
    supported_instruments=sorted(_SUPPORTED_INSTRUMENTS),
    supported_currencies=sorted(_SUPPORTED_CURRENCIES),
    supported_floating_indices=sorted(_SUPPORTED_INDICES),
    supported_payment_frequencies=sorted(_SUPPORTED_FREQUENCIES),
    supported_directions=sorted(_SUPPORTED_DIRECTIONS),
    flat_market_rate=_FLAT_MARKET_RATE,
    default_fixed_rate=_DEFAULT_FIXED_RATE,
    fixed_rate_bounds=FixedRateBounds(min_exclusive=_FIXED_RATE_MIN_EXCLUSIVE, max_exclusive=_FIXED_RATE_MAX_EXCLUSIVE),
    notional_bounds=NotionalBounds(min_inclusive=_NOTIONAL_MIN_INCLUSIVE, max_inclusive=_NOTIONAL_MAX_INCLUSIVE),
    tenor_bounds_years=TenorBoundsYears(min_inclusive=_TENOR_MIN_YEARS_INCLUSIVE, max_inclusive=_TENOR_MAX_YEARS_INCLUSIVE),
    notes=[
        "Indicative pricing only. Not suitable for production pricing or hedging decisions.",
        "Only a narrow ZAR IRS case with JIBAR floating index is currently supported.",
        "Flat curve: all cash flows discounted using quant_core.curves.build_flat (ACT/365F).",
        "Floating leg: par-floating approximation — PV_float = notional × (1 − df_end).",
        "PV01: parallel +1bp shift of all continuously-compounded zero rates.",
    ],
)


@router.get("/assumptions", response_model=AssumptionsResponse)
def get_assumptions() -> AssumptionsResponse:
    """Return the current pricing model assumptions and validation limits."""
    return _RESPONSE

