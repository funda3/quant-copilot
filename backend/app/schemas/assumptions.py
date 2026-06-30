from __future__ import annotations

from pydantic import BaseModel


class FixedRateBounds(BaseModel):
    min_exclusive: float
    max_exclusive: float


class NotionalBounds(BaseModel):
    min_inclusive: int
    max_inclusive: int


class TenorBoundsYears(BaseModel):
    min_inclusive: int
    max_inclusive: int


class AssumptionsResponse(BaseModel):
    pricing_model: str
    supported_instruments: list[str]
    supported_currencies: list[str]
    supported_floating_indices: list[str]
    supported_payment_frequencies: list[str]
    supported_directions: list[str]
    flat_market_rate: float
    default_fixed_rate: float
    fixed_rate_bounds: FixedRateBounds
    notional_bounds: NotionalBounds
    tenor_bounds_years: TenorBoundsYears
    notes: list[str]
