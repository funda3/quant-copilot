from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, field_validator


SupportedPortfolioInstrument = Literal[
    "bond",
    "fra",
    "fx_forward",
    "fx_swap",
    "fx_option",
    "equity_option",
]


class PortfolioPosition(BaseModel):
    """One position entry in a manual v1 portfolio basket."""

    position_id: Optional[str] = None
    instrument_type: SupportedPortfolioInstrument
    quantity: float = 1.0
    asset_class: Optional[str] = None
    fields: Dict[str, Any]

    @field_validator("instrument_type", mode="before")
    @classmethod
    def validate_instrument_type(cls, v: str) -> str:
        return str(v).lower()

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: float) -> float:
        if v <= 0.0:
            raise ValueError(f"quantity must be > 0; got {v}")
        return v

    @field_validator("asset_class", mode="before")
    @classmethod
    def normalize_asset_class(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        value = str(v).strip().lower()
        return value or None

    @field_validator("fields")
    @classmethod
    def validate_fields_not_empty(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if not v:
            raise ValueError("fields must not be empty")
        return v


class PortfolioShockSet(BaseModel):
    """Simple parallel shock set for v1 portfolio scenarios."""

    rates_bps: float = 0.0
    fx_spot_pct: float = 0.0
    equity_spot_pct: float = 0.0
    vol_pct: float = 0.0


class PortfolioValueRequest(BaseModel):
    """Request body for POST /portfolio/value."""

    request_id: Optional[str] = None
    portfolio_name: str
    valuation_date: str
    positions: List[PortfolioPosition]

    @field_validator("portfolio_name", mode="before")
    @classmethod
    def validate_portfolio_name(cls, v: str) -> str:
        value = str(v).strip()
        if not value:
            raise ValueError("portfolio_name must not be empty")
        return value

    @field_validator("valuation_date")
    @classmethod
    def validate_valuation_date(cls, v: str) -> str:
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError(
                f"'{v}' is not a valid ISO-8601 date (expected YYYY-MM-DD)."
            )
        return v

    @field_validator("positions")
    @classmethod
    def validate_positions_not_empty(cls, v: List[PortfolioPosition]) -> List[PortfolioPosition]:
        if not v:
            raise ValueError("positions must contain at least one entry")
        return v


class PortfolioPositionValueResult(BaseModel):
    """Position-level result row for base portfolio valuation."""

    position_id: str
    instrument_type: str
    asset_class: str
    quantity: float
    pricing_status: str
    status: str
    pv: float
    warnings: List[str]


class PortfolioValueResponse(BaseModel):
    """Response body from POST /portfolio/value."""

    request_id: str
    portfolio_name: str
    valuation_date: str
    status: str
    position_count: int
    valued_count: int
    unsupported_count: int
    total_portfolio_pv: float
    grouped_pv_by_instrument_type: Dict[str, float]
    grouped_pv_by_asset_class: Dict[str, float]
    positions: List[PortfolioPositionValueResult]
    warnings: List[str]


class PortfolioScenarioRequest(PortfolioValueRequest):
    """Request body for POST /portfolio/scenario."""

    shocks: PortfolioShockSet


class PortfolioScenarioDefinition(BaseModel):
    """One named scenario for multi-scenario comparison."""

    name: str
    description: Optional[str] = None
    shocks: PortfolioShockSet

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, v: str) -> str:
        value = str(v).strip()
        if not value:
            raise ValueError("scenario name must not be empty")
        return value


class PortfolioScenarioCompareRequest(PortfolioValueRequest):
    """Request body for POST /portfolio/scenario-compare."""

    scenarios: Optional[List[PortfolioScenarioDefinition]] = None
    scenario_pack: Optional[str] = None

    @field_validator("scenario_pack", mode="before")
    @classmethod
    def normalize_scenario_pack(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        value = str(v).strip()
        return value or None


class PortfolioPositionScenarioResult(BaseModel):
    """Position-level result row for scenario valuation."""

    position_id: str
    instrument_type: str
    asset_class: str
    quantity: float
    base_pricing_status: str
    shocked_pricing_status: str
    status: str
    base_pv: float
    shocked_pv: float
    delta_pv: float
    warnings: List[str]


class PortfolioScenarioResponse(BaseModel):
    """Response body from POST /portfolio/scenario."""

    request_id: str
    portfolio_name: str
    valuation_date: str
    status: str
    position_count: int
    valued_count: int
    unsupported_count: int
    base_portfolio_pv: float
    shocked_portfolio_pv: float
    delta_portfolio_pv: float
    grouped_base_pv_by_instrument_type: Dict[str, float]
    grouped_shocked_pv_by_instrument_type: Dict[str, float]
    grouped_delta_pv_by_instrument_type: Dict[str, float]
    grouped_delta_pv_by_asset_class: Dict[str, float]
    positions: List[PortfolioPositionScenarioResult]
    warnings: List[str]


class PortfolioScenarioSummary(BaseModel):
    """Scenario-level row for scenario comparison."""

    scenario_name: str
    description: str
    shocks: PortfolioShockSet
    status: str
    base_portfolio_pv: float
    shocked_portfolio_pv: float
    delta_portfolio_pv: float
    valued_count: int
    unsupported_count: int
    largest_contributor: Optional[str] = None
    largest_contributor_delta_pv: float = 0.0
    largest_loser: Optional[str] = None
    largest_loser_delta_pv: float = 0.0
    warnings: List[str]


class PortfolioScenarioComparePositionDelta(BaseModel):
    """Position-level scenario comparison row."""

    position_id: str
    instrument_type: str
    asset_class: str
    deltas_by_scenario: Dict[str, float]
    warnings_by_scenario: Dict[str, List[str]]


class PortfolioScenarioCompareResponse(BaseModel):
    """Response body from POST /portfolio/scenario-compare."""

    request_id: str
    portfolio_name: str
    valuation_date: str
    status: str
    scenario_pack: str
    scenario_conventions: Dict[str, str]
    scenario_count: int
    position_count: int
    scenarios: List[PortfolioScenarioSummary]
    grouped_delta_by_instrument_type: Dict[str, Dict[str, float]]
    grouped_delta_by_asset_class: Dict[str, Dict[str, float]]
    positions: List[PortfolioScenarioComparePositionDelta]
    warnings: List[str]


class PortfolioSensitivitySet(BaseModel):
    """Named first-order portfolio sensitivity dimensions."""

    rates_sensitivity: float = 0.0
    fx_spot_sensitivity: float = 0.0
    equity_spot_sensitivity: float = 0.0
    vol_sensitivity: float = 0.0


class PortfolioPositionRiskResult(PortfolioSensitivitySet):
    """Position-level result row for portfolio risk decomposition."""

    position_id: str
    instrument_type: str
    asset_class: str
    quantity: float
    base_pricing_status: str
    status: str
    base_pv: float
    warnings: List[str]


class PortfolioRiskResponse(BaseModel):
    """Response body from POST /portfolio/risk."""

    request_id: str
    portfolio_name: str
    valuation_date: str
    status: str
    position_count: int
    valued_count: int
    unsupported_count: int
    total_portfolio_pv: float
    sensitivity_conventions: Dict[str, str]
    total_sensitivities: PortfolioSensitivitySet
    grouped_sensitivities_by_instrument_type: Dict[str, PortfolioSensitivitySet]
    grouped_sensitivities_by_asset_class: Dict[str, PortfolioSensitivitySet]
    positions: List[PortfolioPositionRiskResult]
    warnings: List[str]
