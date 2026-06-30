from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter
from pydantic import ValidationError

from app.api.price import (
    price_bond_endpoint,
    price_equity_option_endpoint,
    price_fra_endpoint,
    price_fx_forward_endpoint,
    price_fx_option_endpoint,
    price_fx_swap_endpoint,
)
from app.schemas.portfolio import (
    PortfolioPosition,
    PortfolioScenarioComparePositionDelta,
    PortfolioScenarioCompareRequest,
    PortfolioScenarioCompareResponse,
    PortfolioScenarioDefinition,
    PortfolioPositionRiskResult,
    PortfolioPositionScenarioResult,
    PortfolioPositionValueResult,
    PortfolioRiskResponse,
    PortfolioSensitivitySet,
    PortfolioScenarioRequest,
    PortfolioScenarioResponse,
    PortfolioScenarioSummary,
    PortfolioValueRequest,
    PortfolioValueResponse,
)
from app.schemas.price import (
    BondPricingRequest,
    EquityOptionPriceRequest,
    FRAPriceRequest,
    FXForwardPriceRequest,
    FXOptionPriceRequest,
    FXSwapPriceRequest,
)
from quant_core.pricing.portfolio import PositionPV, aggregate_position_pvs, infer_asset_class

router = APIRouter(tags=["portfolio"])


@dataclass(frozen=True)
class _ValuationResult:
    pv: float
    pricing_status: str
    status: str
    warnings: list[str]


_RISK_CONVENTIONS = {
    "rates_sensitivity": "PV change for a parallel +1bp rate move.",
    "fx_spot_sensitivity": "PV change for a +1% FX spot move.",
    "equity_spot_sensitivity": "PV change for a +1% equity spot move.",
    "vol_sensitivity": "PV change for a +1 vol point move (volatility +0.01).",
}

_SENSITIVITY_KEYS = (
    "rates_sensitivity",
    "fx_spot_sensitivity",
    "equity_spot_sensitivity",
    "vol_sensitivity",
)

_SCENARIO_PACK_NAME = "Core Market Moves"

_SCENARIO_CONVENTIONS = {
    "rates_bps": "Parallel rate shock in basis points.",
    "fx_spot_pct": "FX spot shock in percent; +5 means spot_rate x 1.05.",
    "equity_spot_pct": "Equity spot shock in percent; -5 means spot_price x 0.95.",
    "vol_pct": "Relative volatility shock in percent; +5 means volatility x 1.05.",
    "pack": "Core Market Moves contains Rates Up/Down, FX Up/Down, Equity Up/Down, Vol Up, and Combined Stress.",
}

_PREDEFINED_SCENARIO_PACKS: dict[str, list[PortfolioScenarioDefinition]] = {
    _SCENARIO_PACK_NAME: [
        PortfolioScenarioDefinition(
            name="Rates Up",
            description="Parallel +100bp rate shock.",
            shocks={"rates_bps": 100.0},
        ),
        PortfolioScenarioDefinition(
            name="Rates Down",
            description="Parallel -100bp rate shock.",
            shocks={"rates_bps": -100.0},
        ),
        PortfolioScenarioDefinition(
            name="FX Up",
            description="FX spot +5%.",
            shocks={"fx_spot_pct": 5.0},
        ),
        PortfolioScenarioDefinition(
            name="FX Down",
            description="FX spot -5%.",
            shocks={"fx_spot_pct": -5.0},
        ),
        PortfolioScenarioDefinition(
            name="Equity Up",
            description="Equity spot +5%.",
            shocks={"equity_spot_pct": 5.0},
        ),
        PortfolioScenarioDefinition(
            name="Equity Down",
            description="Equity spot -5%.",
            shocks={"equity_spot_pct": -5.0},
        ),
        PortfolioScenarioDefinition(
            name="Vol Up",
            description="Volatility +5%.",
            shocks={"vol_pct": 5.0},
        ),
        PortfolioScenarioDefinition(
            name="Combined Stress",
            description="Rates +100bp, FX spot +5%, equity spot -5%, volatility +5%.",
            shocks={
                "rates_bps": 100.0,
                "fx_spot_pct": 5.0,
                "equity_spot_pct": -5.0,
                "vol_pct": 5.0,
            },
        ),
    ],
}


def _format_validation_error(exc: ValidationError) -> str:
    if not exc.errors():
        return "Schema validation error."
    first = exc.errors()[0]
    loc = ".".join(str(x) for x in first.get("loc", []))
    msg = first.get("msg", "Invalid value")
    return f"Schema validation error at '{loc}': {msg}"


def _extract_pv(instrument_type: str, response_model: Any) -> float:
    instrument = instrument_type.lower()
    if instrument == "bond":
        return float(response_model.dirty_price)
    if instrument == "fra":
        return float(response_model.pv)
    if instrument == "fx_forward":
        return float(response_model.present_value_domestic)
    if instrument == "fx_swap":
        return float(response_model.present_value_domestic)
    if instrument == "fx_option":
        return float(response_model.premium_domestic)
    if instrument == "equity_option":
        return float(response_model.premium)
    raise ValueError(f"Unsupported instrument_type '{instrument_type}'.")


def _value_single_position(
    position: PortfolioPosition,
    valuation_date: str,
    request_id: str,
    request_suffix: str,
    fields_override: dict[str, Any] | None = None,
) -> _ValuationResult:
    instrument_type = position.instrument_type.lower()
    payload = copy.deepcopy(fields_override if fields_override is not None else position.fields)
    payload["instrument_type"] = instrument_type
    payload.setdefault("valuation_date", valuation_date)
    payload.setdefault("request_id", f"{request_id}:{request_suffix}")

    try:
        if instrument_type == "bond":
            req = BondPricingRequest(**payload)
            resp = price_bond_endpoint(req)
        elif instrument_type == "fra":
            req = FRAPriceRequest(**payload)
            resp = price_fra_endpoint(req)
        elif instrument_type == "fx_forward":
            req = FXForwardPriceRequest(**payload)
            resp = price_fx_forward_endpoint(req)
        elif instrument_type == "fx_swap":
            req = FXSwapPriceRequest(**payload)
            resp = price_fx_swap_endpoint(req)
        elif instrument_type == "fx_option":
            req = FXOptionPriceRequest(**payload)
            resp = price_fx_option_endpoint(req)
        elif instrument_type == "equity_option":
            req = EquityOptionPriceRequest(**payload)
            resp = price_equity_option_endpoint(req)
        else:
            return _ValuationResult(
                pv=0.0,
                pricing_status="unsupported",
                status="unsupported",
                warnings=[f"Unsupported instrument_type '{instrument_type}'."],
            )
    except ValidationError as exc:
        return _ValuationResult(
            pv=0.0,
            pricing_status="validation_error",
            status="unsupported",
            warnings=[_format_validation_error(exc)],
        )
    except Exception as exc:  # defensive catch for robust basket processing
        return _ValuationResult(
            pv=0.0,
            pricing_status="error",
            status="unsupported",
            warnings=[f"Pricing error: {exc}"],
        )

    pricing_status = str(getattr(resp, "status", "unknown"))
    is_valued = pricing_status in {"indicative", "solved"}
    scaled_pv = _extract_pv(instrument_type, resp) * float(position.quantity) if is_valued else 0.0

    return _ValuationResult(
        pv=scaled_pv,
        pricing_status=pricing_status,
        status="valued" if is_valued else "unsupported",
        warnings=list(getattr(resp, "warnings", []) or []),
    )


def _shift_curve_inputs_rates(curve_inputs: dict[str, Any], rates_shift: float) -> bool:
    changed = False
    for list_name, rate_key in (
        ("deposits", "rate"),
        ("fras", "rate"),
        ("swaps", "par_rate"),
    ):
        for row in curve_inputs.get(list_name) or []:
            if isinstance(row, dict) and rate_key in row:
                row[rate_key] = float(row[rate_key]) + rates_shift
                changed = True
    return changed


def _apply_scenario_shocks(
    instrument_type: str,
    base_fields: dict[str, Any],
    shocks: dict[str, float],
) -> tuple[dict[str, Any], list[str]]:
    shocked = copy.deepcopy(base_fields)
    warnings: list[str] = []
    instrument = instrument_type.lower()

    rates_shift = float(shocks.get("rates_bps", 0.0)) / 10000.0
    fx_spot_multiplier = 1.0 + float(shocks.get("fx_spot_pct", 0.0)) / 100.0
    eq_spot_multiplier = 1.0 + float(shocks.get("equity_spot_pct", 0.0)) / 100.0
    vol_multiplier = 1.0 + float(shocks.get("vol_pct", 0.0)) / 100.0

    if rates_shift != 0.0:
        if instrument == "fx_forward":
            shocked["domestic_rate"] = float(shocked["domestic_rate"]) + rates_shift
            shocked["foreign_rate"] = float(shocked["foreign_rate"]) + rates_shift
        elif instrument == "fx_swap":
            shocked["domestic_rate"] = float(shocked["domestic_rate"]) + rates_shift
        elif instrument == "fx_option":
            shocked["domestic_rate"] = float(shocked["domestic_rate"]) + rates_shift
            shocked["foreign_rate"] = float(shocked["foreign_rate"]) + rates_shift
        elif instrument == "equity_option":
            shocked["risk_free_rate"] = float(shocked["risk_free_rate"]) + rates_shift
        elif instrument in {"bond", "fra"}:
            curve_inputs = shocked.get("curve_inputs")
            if isinstance(curve_inputs, dict):
                changed = _shift_curve_inputs_rates(curve_inputs, rates_shift)
                if not changed:
                    warnings.append(
                        "rates_bps shock did not modify bond/FRA curve_inputs because no quote rows were provided."
                    )
            else:
                warnings.append(
                    "rates_bps shock ignored for bond/FRA position without curve_inputs."
                )

    if fx_spot_multiplier != 1.0 and instrument in {"fx_forward", "fx_swap", "fx_option"}:
        if "spot_rate" in shocked:
            shocked["spot_rate"] = float(shocked["spot_rate"]) * fx_spot_multiplier
        else:
            warnings.append("fx_spot_pct shock ignored because spot_rate is missing.")

    if eq_spot_multiplier != 1.0 and instrument == "equity_option":
        if "spot_price" in shocked:
            shocked["spot_price"] = float(shocked["spot_price"]) * eq_spot_multiplier
        else:
            warnings.append("equity_spot_pct shock ignored because spot_price is missing.")

    if vol_multiplier != 1.0 and instrument in {"fx_option", "equity_option"}:
        if "volatility" in shocked:
            shocked["volatility"] = float(shocked["volatility"]) * vol_multiplier
        else:
            warnings.append("vol_pct shock ignored because volatility is missing.")

    return shocked, warnings


def _bumped_fields_for_sensitivity(
    instrument_type: str,
    base_fields: dict[str, Any],
    sensitivity_key: str,
) -> tuple[dict[str, Any], list[str]]:
    bumped = copy.deepcopy(base_fields)
    warnings: list[str] = []
    instrument = instrument_type.lower()

    if sensitivity_key == "rates_sensitivity":
        if instrument == "fx_forward":
            bumped["domestic_rate"] = float(bumped["domestic_rate"]) + 0.0001
            bumped["foreign_rate"] = float(bumped["foreign_rate"]) + 0.0001
        elif instrument == "fx_swap":
            bumped["domestic_rate"] = float(bumped["domestic_rate"]) + 0.0001
        elif instrument == "fx_option":
            bumped["domestic_rate"] = float(bumped["domestic_rate"]) + 0.0001
            bumped["foreign_rate"] = float(bumped["foreign_rate"]) + 0.0001
        elif instrument == "equity_option":
            bumped["risk_free_rate"] = float(bumped["risk_free_rate"]) + 0.0001
        elif instrument in {"bond", "fra"}:
            curve_inputs = bumped.get("curve_inputs")
            if isinstance(curve_inputs, dict):
                changed = _shift_curve_inputs_rates(curve_inputs, 0.0001)
                if not changed:
                    warnings.append(
                        "rates_sensitivity is zero because curve_inputs had no quote rows to bump."
                    )
            else:
                warnings.append(
                    "rates_sensitivity ignored for bond/FRA position without curve_inputs."
                )
        else:
            warnings.append(f"rates_sensitivity unsupported for {instrument}.")
    elif sensitivity_key == "fx_spot_sensitivity":
        if instrument in {"fx_forward", "fx_swap", "fx_option"}:
            if "spot_rate" in bumped:
                bumped["spot_rate"] = float(bumped["spot_rate"]) * 1.01
            else:
                warnings.append("fx_spot_sensitivity ignored because spot_rate is missing.")
        else:
            warnings.append(f"fx_spot_sensitivity not applicable to {instrument}.")
    elif sensitivity_key == "equity_spot_sensitivity":
        if instrument == "equity_option":
            if "spot_price" in bumped:
                bumped["spot_price"] = float(bumped["spot_price"]) * 1.01
            else:
                warnings.append("equity_spot_sensitivity ignored because spot_price is missing.")
        else:
            warnings.append(f"equity_spot_sensitivity not applicable to {instrument}.")
    elif sensitivity_key == "vol_sensitivity":
        if instrument in {"fx_option", "equity_option"}:
            if "volatility" in bumped:
                bumped["volatility"] = float(bumped["volatility"]) + 0.01
            else:
                warnings.append("vol_sensitivity ignored because volatility is missing.")
        else:
            warnings.append(f"vol_sensitivity not applicable to {instrument}.")
    else:
        warnings.append(f"Unknown sensitivity '{sensitivity_key}'.")

    return bumped, warnings


def _empty_sensitivities() -> dict[str, float]:
    return {key: 0.0 for key in _SENSITIVITY_KEYS}


def _sensitivity_set(values: dict[str, float]) -> PortfolioSensitivitySet:
    return PortfolioSensitivitySet(**{key: float(values.get(key, 0.0)) for key in _SENSITIVITY_KEYS})


def _add_sensitivities(target: dict[str, float], source: dict[str, float]) -> None:
    for key in _SENSITIVITY_KEYS:
        target[key] = target.get(key, 0.0) + float(source.get(key, 0.0))


@router.post("/portfolio/value", response_model=PortfolioValueResponse)
def value_portfolio(request: PortfolioValueRequest) -> PortfolioValueResponse:
    rid = request.request_id or str(uuid.uuid4())

    position_rows: list[PortfolioPositionValueResult] = []
    normalized_rows: list[PositionPV] = []

    for idx, position in enumerate(request.positions, start=1):
        position_id = position.position_id or f"pos-{idx}"
        asset_class = position.asset_class or infer_asset_class(position.instrument_type)

        result = _value_single_position(
            position=position,
            valuation_date=request.valuation_date,
            request_id=rid,
            request_suffix=position_id,
        )

        position_rows.append(
            PortfolioPositionValueResult(
                position_id=position_id,
                instrument_type=position.instrument_type,
                asset_class=asset_class,
                quantity=position.quantity,
                pricing_status=result.pricing_status,
                status=result.status,
                pv=result.pv,
                warnings=result.warnings,
            )
        )

        normalized_rows.append(
            PositionPV(
                position_id=position_id,
                instrument_type=position.instrument_type,
                pv=result.pv,
                status=result.status,
                asset_class=asset_class,
            )
        )

    agg = aggregate_position_pvs(normalized_rows)

    return PortfolioValueResponse(
        request_id=rid,
        portfolio_name=request.portfolio_name,
        valuation_date=request.valuation_date,
        status="indicative" if agg.unsupported_count == 0 else "partial",
        position_count=agg.position_count,
        valued_count=agg.valued_count,
        unsupported_count=agg.unsupported_count,
        total_portfolio_pv=agg.total_pv,
        grouped_pv_by_instrument_type=agg.grouped_pv_by_instrument_type,
        grouped_pv_by_asset_class=agg.grouped_pv_by_asset_class,
        positions=position_rows,
        warnings=[],
    )


@router.post("/portfolio/risk", response_model=PortfolioRiskResponse)
def risk_portfolio(request: PortfolioValueRequest) -> PortfolioRiskResponse:
    rid = request.request_id or str(uuid.uuid4())

    positions: list[PortfolioPositionRiskResult] = []
    total_sensitivities = _empty_sensitivities()
    grouped_by_instrument: dict[str, dict[str, float]] = {}
    grouped_by_asset: dict[str, dict[str, float]] = {}
    total_pv = 0.0
    valued_count = 0
    unsupported_count = 0

    for idx, position in enumerate(request.positions, start=1):
        position_id = position.position_id or f"pos-{idx}"
        instrument_type = position.instrument_type.lower()
        asset_class = position.asset_class or infer_asset_class(instrument_type)

        base_result = _value_single_position(
            position=position,
            valuation_date=request.valuation_date,
            request_id=rid,
            request_suffix=f"{position_id}:risk-base",
        )
        row_warnings = list(base_result.warnings)
        row_sensitivities = _empty_sensitivities()

        if base_result.status == "valued":
            valued_count += 1
            total_pv += base_result.pv
            for sensitivity_key in _SENSITIVITY_KEYS:
                bumped_fields, bump_warnings = _bumped_fields_for_sensitivity(
                    instrument_type=instrument_type,
                    base_fields=position.fields,
                    sensitivity_key=sensitivity_key,
                )
                row_warnings.extend(bump_warnings)
                if bump_warnings:
                    continue

                bumped_result = _value_single_position(
                    position=position,
                    valuation_date=request.valuation_date,
                    request_id=rid,
                    request_suffix=f"{position_id}:{sensitivity_key}",
                    fields_override=bumped_fields,
                )
                row_warnings.extend(bumped_result.warnings)
                if bumped_result.status == "valued":
                    row_sensitivities[sensitivity_key] = bumped_result.pv - base_result.pv
                else:
                    row_warnings.append(
                        f"{sensitivity_key} could not be computed because bumped valuation status was {bumped_result.pricing_status}."
                    )
        else:
            unsupported_count += 1
            row_warnings.append("Risk sensitivities not computed because base valuation was unsupported.")

        _add_sensitivities(total_sensitivities, row_sensitivities)
        _add_sensitivities(
            grouped_by_instrument.setdefault(instrument_type, _empty_sensitivities()),
            row_sensitivities,
        )
        _add_sensitivities(
            grouped_by_asset.setdefault(asset_class, _empty_sensitivities()),
            row_sensitivities,
        )

        positions.append(
            PortfolioPositionRiskResult(
                position_id=position_id,
                instrument_type=instrument_type,
                asset_class=asset_class,
                quantity=position.quantity,
                base_pricing_status=base_result.pricing_status,
                status=base_result.status,
                base_pv=base_result.pv,
                warnings=row_warnings,
                **row_sensitivities,
            )
        )

    return PortfolioRiskResponse(
        request_id=rid,
        portfolio_name=request.portfolio_name,
        valuation_date=request.valuation_date,
        status="indicative" if unsupported_count == 0 else "partial",
        position_count=len(request.positions),
        valued_count=valued_count,
        unsupported_count=unsupported_count,
        total_portfolio_pv=total_pv,
        sensitivity_conventions=_RISK_CONVENTIONS,
        total_sensitivities=_sensitivity_set(total_sensitivities),
        grouped_sensitivities_by_instrument_type={
            key: _sensitivity_set(value) for key, value in grouped_by_instrument.items()
        },
        grouped_sensitivities_by_asset_class={
            key: _sensitivity_set(value) for key, value in grouped_by_asset.items()
        },
        positions=positions,
        warnings=[],
    )


@router.post("/portfolio/scenario", response_model=PortfolioScenarioResponse)
def scenario_portfolio(request: PortfolioScenarioRequest) -> PortfolioScenarioResponse:
    rid = request.request_id or str(uuid.uuid4())

    scenario_rows: list[PortfolioPositionScenarioResult] = []
    base_rows: list[PositionPV] = []
    shocked_rows: list[PositionPV] = []

    shocks_dict = request.shocks.model_dump()

    for idx, position in enumerate(request.positions, start=1):
        position_id = position.position_id or f"pos-{idx}"
        asset_class = position.asset_class or infer_asset_class(position.instrument_type)

        base_result = _value_single_position(
            position=position,
            valuation_date=request.valuation_date,
            request_id=rid,
            request_suffix=f"{position_id}:base",
        )

        shocked_fields, shock_warnings = _apply_scenario_shocks(
            instrument_type=position.instrument_type,
            base_fields=position.fields,
            shocks=shocks_dict,
        )

        shocked_result = _value_single_position(
            position=position,
            valuation_date=request.valuation_date,
            request_id=rid,
            request_suffix=f"{position_id}:shock",
            fields_override=shocked_fields,
        )

        combined_warnings = base_result.warnings + shock_warnings + shocked_result.warnings
        row_status = "valued" if (base_result.status == "valued" and shocked_result.status == "valued") else "unsupported"

        delta = shocked_result.pv - base_result.pv

        scenario_rows.append(
            PortfolioPositionScenarioResult(
                position_id=position_id,
                instrument_type=position.instrument_type,
                asset_class=asset_class,
                quantity=position.quantity,
                base_pricing_status=base_result.pricing_status,
                shocked_pricing_status=shocked_result.pricing_status,
                status=row_status,
                base_pv=base_result.pv,
                shocked_pv=shocked_result.pv,
                delta_pv=delta,
                warnings=combined_warnings,
            )
        )

        base_rows.append(
            PositionPV(
                position_id=position_id,
                instrument_type=position.instrument_type,
                pv=base_result.pv,
                status=base_result.status,
                asset_class=asset_class,
            )
        )
        shocked_rows.append(
            PositionPV(
                position_id=position_id,
                instrument_type=position.instrument_type,
                pv=shocked_result.pv,
                status=shocked_result.status,
                asset_class=asset_class,
            )
        )

    base_agg = aggregate_position_pvs(base_rows)
    shocked_agg = aggregate_position_pvs(shocked_rows)

    delta_by_instrument = {
        key: shocked_agg.grouped_pv_by_instrument_type.get(key, 0.0)
        - base_agg.grouped_pv_by_instrument_type.get(key, 0.0)
        for key in set(base_agg.grouped_pv_by_instrument_type) | set(shocked_agg.grouped_pv_by_instrument_type)
    }
    delta_by_asset_class = {
        key: shocked_agg.grouped_pv_by_asset_class.get(key, 0.0)
        - base_agg.grouped_pv_by_asset_class.get(key, 0.0)
        for key in set(base_agg.grouped_pv_by_asset_class) | set(shocked_agg.grouped_pv_by_asset_class)
    }

    return PortfolioScenarioResponse(
        request_id=rid,
        portfolio_name=request.portfolio_name,
        valuation_date=request.valuation_date,
        status="indicative" if (base_agg.unsupported_count == 0 and shocked_agg.unsupported_count == 0) else "partial",
        position_count=base_agg.position_count,
        valued_count=min(base_agg.valued_count, shocked_agg.valued_count),
        unsupported_count=max(base_agg.unsupported_count, shocked_agg.unsupported_count),
        base_portfolio_pv=base_agg.total_pv,
        shocked_portfolio_pv=shocked_agg.total_pv,
        delta_portfolio_pv=shocked_agg.total_pv - base_agg.total_pv,
        grouped_base_pv_by_instrument_type=base_agg.grouped_pv_by_instrument_type,
        grouped_shocked_pv_by_instrument_type=shocked_agg.grouped_pv_by_instrument_type,
        grouped_delta_pv_by_instrument_type=delta_by_instrument,
        grouped_delta_pv_by_asset_class=delta_by_asset_class,
        positions=scenario_rows,
        warnings=[],
    )


def _resolve_scenario_definitions(
    request: PortfolioScenarioCompareRequest,
) -> tuple[str, list[PortfolioScenarioDefinition], list[str]]:
    warnings: list[str] = []
    pack_name = request.scenario_pack or _SCENARIO_PACK_NAME
    scenarios = request.scenarios

    if scenarios:
        return "Custom scenarios", scenarios, warnings

    if pack_name not in _PREDEFINED_SCENARIO_PACKS:
        warnings.append(
            f"Unknown scenario_pack '{pack_name}', using {_SCENARIO_PACK_NAME}."
        )
        pack_name = _SCENARIO_PACK_NAME

    return pack_name, _PREDEFINED_SCENARIO_PACKS[pack_name], warnings


def _largest_positive_position(
    scenario: PortfolioScenarioResponse,
) -> tuple[str | None, float]:
    valued_rows = [row for row in scenario.positions if row.status == "valued"]
    if not valued_rows:
        return None, 0.0
    row = max(valued_rows, key=lambda item: item.delta_pv)
    if row.delta_pv <= 0.0:
        return None, 0.0
    return row.position_id, row.delta_pv


def _largest_negative_position(
    scenario: PortfolioScenarioResponse,
) -> tuple[str | None, float]:
    valued_rows = [row for row in scenario.positions if row.status == "valued"]
    if not valued_rows:
        return None, 0.0
    row = min(valued_rows, key=lambda item: item.delta_pv)
    if row.delta_pv >= 0.0:
        return None, 0.0
    return row.position_id, row.delta_pv


@router.post("/portfolio/scenario-compare", response_model=PortfolioScenarioCompareResponse)
def scenario_compare_portfolio(
    request: PortfolioScenarioCompareRequest,
) -> PortfolioScenarioCompareResponse:
    rid = request.request_id or str(uuid.uuid4())
    pack_name, scenario_definitions, response_warnings = _resolve_scenario_definitions(request)

    seen_names: set[str] = set()
    scenario_summaries: list[PortfolioScenarioSummary] = []
    grouped_by_instrument: dict[str, dict[str, float]] = {}
    grouped_by_asset: dict[str, dict[str, float]] = {}
    position_grid: dict[str, dict[str, Any]] = {}
    has_partial = False

    for index, scenario_def in enumerate(scenario_definitions, start=1):
        scenario_name = scenario_def.name
        if scenario_name in seen_names:
            scenario_name = f"{scenario_name} ({index})"
            response_warnings.append(
                f"Duplicate scenario name '{scenario_def.name}' renamed to '{scenario_name}'."
            )
        seen_names.add(scenario_name)

        scenario_response = scenario_portfolio(
            PortfolioScenarioRequest(
                request_id=f"{rid}:{index}",
                portfolio_name=request.portfolio_name,
                valuation_date=request.valuation_date,
                positions=request.positions,
                shocks=scenario_def.shocks,
            )
        )
        has_partial = has_partial or scenario_response.status != "indicative"

        largest_contributor, largest_contributor_delta = _largest_positive_position(scenario_response)
        largest_loser, largest_loser_delta = _largest_negative_position(scenario_response)
        scenario_warnings = [
            f"{row.position_id}: {warning}"
            for row in scenario_response.positions
            for warning in row.warnings
        ]

        scenario_summaries.append(
            PortfolioScenarioSummary(
                scenario_name=scenario_name,
                description=scenario_def.description or scenario_name,
                shocks=scenario_def.shocks,
                status=scenario_response.status,
                base_portfolio_pv=scenario_response.base_portfolio_pv,
                shocked_portfolio_pv=scenario_response.shocked_portfolio_pv,
                delta_portfolio_pv=scenario_response.delta_portfolio_pv,
                valued_count=scenario_response.valued_count,
                unsupported_count=scenario_response.unsupported_count,
                largest_contributor=largest_contributor,
                largest_contributor_delta_pv=largest_contributor_delta,
                largest_loser=largest_loser,
                largest_loser_delta_pv=largest_loser_delta,
                warnings=scenario_warnings,
            )
        )

        grouped_by_instrument[scenario_name] = scenario_response.grouped_delta_pv_by_instrument_type
        grouped_by_asset[scenario_name] = scenario_response.grouped_delta_pv_by_asset_class

        for row in scenario_response.positions:
            entry = position_grid.setdefault(
                row.position_id,
                {
                    "position_id": row.position_id,
                    "instrument_type": row.instrument_type,
                    "asset_class": row.asset_class,
                    "deltas_by_scenario": {},
                    "warnings_by_scenario": {},
                },
            )
            entry["deltas_by_scenario"][scenario_name] = row.delta_pv
            entry["warnings_by_scenario"][scenario_name] = row.warnings

    return PortfolioScenarioCompareResponse(
        request_id=rid,
        portfolio_name=request.portfolio_name,
        valuation_date=request.valuation_date,
        status="partial" if has_partial else "indicative",
        scenario_pack=pack_name,
        scenario_conventions=_SCENARIO_CONVENTIONS,
        scenario_count=len(scenario_summaries),
        position_count=len(request.positions),
        scenarios=scenario_summaries,
        grouped_delta_by_instrument_type=grouped_by_instrument,
        grouped_delta_by_asset_class=grouped_by_asset,
        positions=[
            PortfolioScenarioComparePositionDelta(**entry)
            for entry in position_grid.values()
        ],
        warnings=response_warnings,
    )
