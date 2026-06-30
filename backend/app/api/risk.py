"""
POST /risk/ladder — bucketed key-rate PV01 ladder for vanilla IRS.

Thin orchestration layer that:
  1. Validates the trade via the existing _check_supported() helper.
  2. Builds a discount curve via _build_curve() (flat or bootstrapped).
  3. Constructs a VanillaIRS using the resolved day-count (Step-12 fix).
  4. Delegates all risk maths to quant_core.risk.ladder.pv01_ladder_irs().
  5. Returns a typed LadderResponse.

No risk maths live here.
"""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter

from app.schemas.risk import (
    BondRiskRequest,
    BondRiskResponse,
    IRSDirectLadderRequest,
    IRSDirectLadderResponse,
    IRSDirectScenarioRequest,
    IRSDirectScenarioResponse,
    LadderRequest,
    LadderResponse,
    ScenarioRequest,
    ScenarioResponse,
)
from app.services.pricer import (
    _DEFAULT_FIXED_RATE,
    _FLAT_CURVE_DAY_COUNT,
    _build_curve,
    _check_supported,
    parse_tenor_years,
)
from quant_core.conventions.day_count import accrual_fraction
from quant_core.curves.discount_curve import DiscountCurve
from quant_core.instruments.bond import FixedRateBond
from quant_core.instruments.irs import VanillaIRS
from quant_core.pricing.bond_pricer import FREQ_MONTHS as _BOND_FREQ_MONTHS
from quant_core.pricing.bond_pricer import price_bond
from quant_core.risk.bond_risk import (
    bond_convexity,
    bond_dv01,
    macaulay_duration as bond_macaulay_duration,
    modified_duration as bond_modified_duration,
)
from quant_core.risk.ladder import pv01_ladder_irs
from quant_core.risk.scenario import run_parallel_curve_scenarios_irs
from quant_core.utils.date_utils import add_months

router = APIRouter(tags=["risk"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unsupported(
    rid: str,
    fields: dict,
    warnings: list[str],
) -> LadderResponse:
    """Return a graceful unsupported response."""
    return LadderResponse(
        request_id=rid,
        instrument_type=fields.get("instrument_type"),
        currency=fields.get("currency"),
        bucket_pv01={},
        total_abs_pv01=0.0,
        status="unsupported",
        assumptions=["Risk ladder attempted under the ZAR IRS quant-core engine scope."],
        warnings=warnings,
    )


def _direct_ladder_error(
    rid: str,
    currency: str | None,
    warnings: list[str],
) -> IRSDirectLadderResponse:
    """Return a graceful error response for ``POST /risk/ladder/direct``."""
    return IRSDirectLadderResponse(
        request_id=rid,
        instrument_type="irs",
        currency=currency,
        bucket_pv01={},
        total_abs_pv01=0.0,
        curve_source="none",
        status="error",
        assumptions=[],
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post("/risk/ladder", response_model=LadderResponse)
def risk_ladder(request: LadderRequest) -> LadderResponse:
    """
    Compute a bucketed key-rate PV01 ladder for a ZAR vanilla IRS.

    The endpoint accepts the same narrow trade inputs as ``POST /price``
    plus an optional ``bucket_years`` list and returns signed PV01 values
    per tenor bucket.

    Supported: instrument_type=irs, currency=ZAR, floating_index=JIBAR.
    All other combinations return status=unsupported with explanatory warnings.
    """
    rid = request.request_id or str(uuid.uuid4())
    fields = request.extracted_fields

    # ------------------------------------------------------------------ #
    # Step 1: validate trade
    # ------------------------------------------------------------------ #
    reasons = _check_supported(fields)
    if reasons:
        return _unsupported(rid, fields, reasons)

    # ------------------------------------------------------------------ #
    # Step 2: parse trade fields (all validated by _check_supported)
    # ------------------------------------------------------------------ #
    notional = float(fields["notional"])
    tenor_years = parse_tenor_years(fields["tenor"])  # type: ignore[arg-type]
    frequency = str(fields["payment_frequency"]).lower()
    direction = fields["direction"]

    fixed_rate_provided = "fixed_rate" in fields
    if fixed_rate_provided:
        try:
            fixed_rate = float(fields["fixed_rate"])
        except (TypeError, ValueError):
            return _unsupported(
                rid,
                fields,
                [
                    f"Invalid fixed_rate '{fields['fixed_rate']}'. "
                    "Expected a numeric value (e.g. 0.085 for 8.5%)."
                ],
            )
    else:
        fixed_rate = _DEFAULT_FIXED_RATE

    valuation_date = date.today()

    # ------------------------------------------------------------------ #
    # Step 3: build curve
    # ------------------------------------------------------------------ #
    try:
        curve, is_bootstrapped, curve_val_date, resolved_day_count = _build_curve(
            request.curve_inputs,
            valuation_date,
            tenor_years,  # type: ignore[arg-type]
            frequency,
            _FLAT_CURVE_DAY_COUNT,
        )
    except ValueError as exc:
        return _unsupported(rid, fields, [f"Curve construction error: {exc}"])

    # ------------------------------------------------------------------ #
    # Step 4: construct VanillaIRS
    # ------------------------------------------------------------------ #
    try:
        swap = VanillaIRS(
            valuation_date=curve_val_date,
            start_date=curve_val_date,
            tenor_years=tenor_years,  # type: ignore[arg-type]
            notional=notional,
            fixed_rate=fixed_rate,
            payment_frequency=frequency,
            day_count=resolved_day_count,
            pay_receive=direction,
        )
    except ValueError as exc:
        return _unsupported(rid, fields, [f"Swap construction error: {exc}"])

    # ------------------------------------------------------------------ #
    # Step 5: compute ladder
    # ------------------------------------------------------------------ #
    try:
        bucket_pv01 = pv01_ladder_irs(swap, curve, request.bucket_years)
    except ValueError as exc:
        return _unsupported(rid, fields, [f"Ladder error: {exc}"])

    total_abs_pv01 = sum(abs(v) for v in bucket_pv01.values())

    # ------------------------------------------------------------------ #
    # Step 6: build assumptions
    # ------------------------------------------------------------------ #
    fixed_rate_note = (
        f"Fixed coupon rate: {fixed_rate:.4%} (provided by caller)."
        if fixed_rate_provided
        else f"Fixed coupon rate: {fixed_rate:.4%} (default assumption; not provided in prompt)."
    )

    bucket_note = (
        f"Buckets: {', '.join(bucket_pv01.keys())}."
    )

    if is_bootstrapped:
        ci = request.curve_inputs  # type: ignore[union-attr]
        n_dep = len(ci.deposits or [])
        n_fra = len(ci.fras or [])
        n_swp = len(ci.swaps or [])
        assumptions = [
            f"Bootstrapped mixed curve: {n_dep} deposit(s), {n_fra} FRA(s), {n_swp} swap(s).",
            (
                f"Curve: valuation date {curve_val_date.isoformat()}, "
                f"{ci.payment_frequency} coupons, {ci.day_count}."
            ),
            fixed_rate_note,
            bucket_note,
            "Key-rate PV01: nearest-pillar +1bp bump in continuously-compounded zero-rate space.",
            "Signed convention: positive for payer (rate rise benefits payer); "
            "negative for receiver.",
            "Indicative only. Not suitable for production risk management or hedging decisions.",
        ]
    else:
        assumptions = [
            f"Flat annual market rate: 8.00% (ZAR JIBAR proxy).",
            fixed_rate_note,
            bucket_note,
            "Key-rate PV01: nearest-pillar +1bp bump in continuously-compounded zero-rate space.",
            "Signed convention: positive for payer (rate rise benefits payer); "
            "negative for receiver.",
            "Indicative only. Not suitable for production risk management or hedging decisions.",
        ]

    return LadderResponse(
        request_id=rid,
        instrument_type=fields.get("instrument_type"),
        currency=fields.get("currency"),
        bucket_pv01=bucket_pv01,
        total_abs_pv01=total_abs_pv01,
        status="indicative",
        assumptions=assumptions,
        warnings=[],
    )


@router.post("/risk/ladder/direct", response_model=IRSDirectLadderResponse)
def risk_ladder_direct(request: IRSDirectLadderRequest) -> IRSDirectLadderResponse:
    """
    Compute a bucketed key-rate PV01 ladder for a ZAR vanilla IRS from a
    fully-structured request.

    Unlike ``POST /risk/ladder`` this endpoint accepts explicit typed IRS
    fields validated at the schema level. All ladder logic remains identical:
    the same flat/bootstrapped curve construction path, the same VanillaIRS
    instrument construction, and the same quant-core ``pv01_ladder_irs``
    function.
    """
    rid = request.request_id or str(uuid.uuid4())

    notional = request.notional
    tenor_years = parse_tenor_years(request.tenor)  # safe — schema validates pattern
    frequency = request.payment_frequency
    direction = request.direction
    fixed_rate_provided = request.fixed_rate is not None
    fixed_rate = request.fixed_rate if fixed_rate_provided else _DEFAULT_FIXED_RATE
    valuation_date = date.today()

    try:
        curve, is_bootstrapped, curve_val_date, resolved_day_count = _build_curve(
            request.curve_inputs,
            valuation_date,
            tenor_years,  # type: ignore[arg-type]
            frequency,
            _FLAT_CURVE_DAY_COUNT,
        )
    except ValueError as exc:
        return _direct_ladder_error(
            rid, request.currency, [f"Curve construction error: {exc}"]
        )

    curve_source = "bootstrapped_mixed_curve" if is_bootstrapped else "flat_fallback"

    try:
        swap = VanillaIRS(
            valuation_date=curve_val_date,
            start_date=curve_val_date,
            tenor_years=tenor_years,  # type: ignore[arg-type]
            notional=notional,
            fixed_rate=fixed_rate,
            payment_frequency=frequency,
            day_count=resolved_day_count,
            pay_receive=direction,
        )
    except ValueError as exc:
        return _direct_ladder_error(
            rid, request.currency, [f"Swap construction error: {exc}"]
        )

    try:
        bucket_pv01 = pv01_ladder_irs(swap, curve, request.bucket_years)
    except ValueError as exc:
        return _direct_ladder_error(rid, request.currency, [f"Ladder error: {exc}"])

    total_abs_pv01 = sum(abs(v) for v in bucket_pv01.values())

    fixed_rate_note = (
        f"Fixed coupon rate: {fixed_rate:.4%} (provided by caller)."
        if fixed_rate_provided
        else f"Fixed coupon rate: {fixed_rate:.4%} (default assumption; not provided)."
    )
    bucket_note = f"Buckets: {', '.join(bucket_pv01.keys())}."

    if is_bootstrapped:
        ci = request.curve_inputs  # type: ignore[union-attr]
        n_dep = len(ci.deposits or [])
        n_fra = len(ci.fras or [])
        n_swp = len(ci.swaps or [])
        assumptions = [
            f"Bootstrapped mixed curve: {n_dep} deposit(s), {n_fra} FRA(s), {n_swp} swap(s).",
            (
                f"Curve: valuation date {curve_val_date.isoformat()}, "
                f"{ci.payment_frequency} coupons, {ci.day_count}."
            ),
            fixed_rate_note,
            bucket_note,
            "Key-rate PV01: nearest-pillar +1bp bump in continuously-compounded zero-rate space.",
            "Signed convention: positive for payer (rate rise benefits payer); negative for receiver.",
            "Indicative only. Not suitable for production risk management or hedging decisions.",
        ]
    else:
        assumptions = [
            "Flat annual market rate: 8.00% (ZAR JIBAR proxy).",
            fixed_rate_note,
            bucket_note,
            "Key-rate PV01: nearest-pillar +1bp bump in continuously-compounded zero-rate space.",
            "Signed convention: positive for payer (rate rise benefits payer); negative for receiver.",
            "Indicative only. Not suitable for production risk management or hedging decisions.",
        ]

    return IRSDirectLadderResponse(
        request_id=rid,
        instrument_type="irs",
        currency=request.currency,
        bucket_pv01=bucket_pv01,
        total_abs_pv01=total_abs_pv01,
        curve_source=curve_source,
        status="indicative",
        assumptions=assumptions,
        warnings=[],
    )


# ---------------------------------------------------------------------------
# Scenario helpers
# ---------------------------------------------------------------------------


def _unsupported_scenario(
    rid: str,
    fields: dict,
    warnings: list[str],
) -> ScenarioResponse:
    """Return a graceful unsupported response for the scenario endpoint."""
    return ScenarioResponse(
        request_id=rid,
        instrument_type=fields.get("instrument_type"),
        currency=fields.get("currency"),
        scenario_npv={},
        base_npv=0.0,
        status="unsupported",
        assumptions=["Scenario analysis attempted under the ZAR IRS quant-core engine scope."],
        warnings=warnings,
    )


def _direct_scenario_error(
    rid: str,
    currency: str | None,
    warnings: list[str],
) -> IRSDirectScenarioResponse:
    """Return a graceful error response for ``POST /risk/scenario/direct``."""
    return IRSDirectScenarioResponse(
        request_id=rid,
        instrument_type="irs",
        currency=currency,
        status="error",
        scenario_npv={},
        base_npv=0.0,
        curve_source="none",
        assumptions=[],
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Scenario route
# ---------------------------------------------------------------------------


@router.post("/risk/scenario", response_model=ScenarioResponse)
def risk_scenario(request: ScenarioRequest) -> ScenarioResponse:
    """
    Compute scenario NPVs for a ZAR vanilla IRS under parallel curve shifts.

    For each requested shift (in basis points) all continuously-compounded
    zero rates of the discount curve are shifted in parallel and the swap is
    repriced.  The endpoint returns the NPV at each shift level together with
    the unshifted base NPV.

    Supported: instrument_type=irs, currency=ZAR, floating_index=JIBAR.
    All other combinations return status=unsupported with explanatory warnings.
    """
    rid = request.request_id or str(uuid.uuid4())
    fields = request.extracted_fields

    # ------------------------------------------------------------------ #
    # Step 1: validate trade
    # ------------------------------------------------------------------ #
    reasons = _check_supported(fields)
    if reasons:
        return _unsupported_scenario(rid, fields, reasons)

    # ------------------------------------------------------------------ #
    # Step 2: parse trade fields
    # ------------------------------------------------------------------ #
    notional = float(fields["notional"])
    tenor_years = parse_tenor_years(fields["tenor"])  # type: ignore[arg-type]
    frequency = str(fields["payment_frequency"]).lower()
    direction = fields["direction"]

    fixed_rate_provided = "fixed_rate" in fields
    if fixed_rate_provided:
        try:
            fixed_rate = float(fields["fixed_rate"])
        except (TypeError, ValueError):
            return _unsupported_scenario(
                rid,
                fields,
                [
                    f"Invalid fixed_rate '{fields['fixed_rate']}'. "
                    "Expected a numeric value (e.g. 0.085 for 8.5%)."
                ],
            )
    else:
        fixed_rate = _DEFAULT_FIXED_RATE

    valuation_date = date.today()

    # ------------------------------------------------------------------ #
    # Step 3: build curve
    # ------------------------------------------------------------------ #
    try:
        curve, is_bootstrapped, curve_val_date, resolved_day_count = _build_curve(
            request.curve_inputs,
            valuation_date,
            tenor_years,  # type: ignore[arg-type]
            frequency,
            _FLAT_CURVE_DAY_COUNT,
        )
    except ValueError as exc:
        return _unsupported_scenario(rid, fields, [f"Curve construction error: {exc}"])

    # ------------------------------------------------------------------ #
    # Step 4: construct VanillaIRS
    # ------------------------------------------------------------------ #
    try:
        swap = VanillaIRS(
            valuation_date=curve_val_date,
            start_date=curve_val_date,
            tenor_years=tenor_years,  # type: ignore[arg-type]
            notional=notional,
            fixed_rate=fixed_rate,
            payment_frequency=frequency,
            day_count=resolved_day_count,
            pay_receive=direction,
        )
    except ValueError as exc:
        return _unsupported_scenario(rid, fields, [f"Swap construction error: {exc}"])

    # ------------------------------------------------------------------ #
    # Step 5: compute base NPV (shift = 0) and scenario NPVs
    # ------------------------------------------------------------------ #
    try:
        base_result = run_parallel_curve_scenarios_irs(swap, curve, shift_bps=[0])
        base_npv = base_result["0bp"]
        scenario_npv = run_parallel_curve_scenarios_irs(swap, curve, request.shift_bps)
    except ValueError as exc:
        return _unsupported_scenario(rid, fields, [f"Scenario error: {exc}"])

    # ------------------------------------------------------------------ #
    # Step 6: build assumptions
    # ------------------------------------------------------------------ #
    fixed_rate_note = (
        f"Fixed coupon rate: {fixed_rate:.4%} (provided by caller)."
        if fixed_rate_provided
        else f"Fixed coupon rate: {fixed_rate:.4%} (default assumption; not provided in prompt)."
    )

    shift_labels = ", ".join(scenario_npv.keys())
    shift_note = f"Scenario shifts: {shift_labels}."

    if is_bootstrapped:
        ci = request.curve_inputs  # type: ignore[union-attr]
        n_dep = len(ci.deposits or [])
        n_fra = len(ci.fras or [])
        n_swp = len(ci.swaps or [])
        assumptions = [
            f"Bootstrapped mixed curve: {n_dep} deposit(s), {n_fra} FRA(s), {n_swp} swap(s).",
            (
                f"Curve: valuation date {curve_val_date.isoformat()}, "
                f"{ci.payment_frequency} coupons, {ci.day_count}."
            ),
            fixed_rate_note,
            shift_note,
            "Parallel shift: all continuously-compounded zero rates shifted by the same amount.",
            "Indicative only. Not suitable for production risk management or hedging decisions.",
        ]
    else:
        assumptions = [
            "Flat annual market rate: 8.00% (ZAR JIBAR proxy).",
            fixed_rate_note,
            shift_note,
            "Parallel shift: all continuously-compounded zero rates shifted by the same amount.",
            "Indicative only. Not suitable for production risk management or hedging decisions.",
        ]

    return ScenarioResponse(
        request_id=rid,
        instrument_type=fields.get("instrument_type"),
        currency=fields.get("currency"),
        status="indicative",
        scenario_npv=scenario_npv,
        base_npv=base_npv,
        assumptions=assumptions,
        warnings=[],
    )


@router.post("/risk/scenario/direct", response_model=IRSDirectScenarioResponse)
def risk_scenario_direct(
    request: IRSDirectScenarioRequest,
) -> IRSDirectScenarioResponse:
    """
    Compute parallel curve-shift scenario NPVs for a ZAR vanilla IRS from a
    fully-structured request.

    Unlike ``POST /risk/scenario`` this endpoint accepts explicit typed IRS
    fields validated at the schema level. All scenario logic remains
    identical: the same flat/bootstrapped curve construction path, the same
    VanillaIRS instrument construction, and the same quant-core
    ``run_parallel_curve_scenarios_irs`` function.
    """
    rid = request.request_id or str(uuid.uuid4())

    notional = request.notional
    tenor_years = parse_tenor_years(request.tenor)  # safe — schema validates pattern
    frequency = request.payment_frequency
    direction = request.direction
    fixed_rate_provided = request.fixed_rate is not None
    fixed_rate = request.fixed_rate if fixed_rate_provided else _DEFAULT_FIXED_RATE
    valuation_date = date.today()

    try:
        curve, is_bootstrapped, curve_val_date, resolved_day_count = _build_curve(
            request.curve_inputs,
            valuation_date,
            tenor_years,  # type: ignore[arg-type]
            frequency,
            _FLAT_CURVE_DAY_COUNT,
        )
    except ValueError as exc:
        return _direct_scenario_error(
            rid, request.currency, [f"Curve construction error: {exc}"]
        )

    curve_source = "bootstrapped_mixed_curve" if is_bootstrapped else "flat_fallback"

    try:
        swap = VanillaIRS(
            valuation_date=curve_val_date,
            start_date=curve_val_date,
            tenor_years=tenor_years,  # type: ignore[arg-type]
            notional=notional,
            fixed_rate=fixed_rate,
            payment_frequency=frequency,
            day_count=resolved_day_count,
            pay_receive=direction,
        )
    except ValueError as exc:
        return _direct_scenario_error(
            rid, request.currency, [f"Swap construction error: {exc}"]
        )

    try:
        base_result = run_parallel_curve_scenarios_irs(swap, curve, shift_bps=[0])
        base_npv = base_result["0bp"]
        scenario_npv = run_parallel_curve_scenarios_irs(swap, curve, request.shift_bps)
    except ValueError as exc:
        return _direct_scenario_error(
            rid, request.currency, [f"Scenario error: {exc}"]
        )

    fixed_rate_note = (
        f"Fixed coupon rate: {fixed_rate:.4%} (provided by caller)."
        if fixed_rate_provided
        else f"Fixed coupon rate: {fixed_rate:.4%} (default assumption; not provided)."
    )
    shift_labels = ", ".join(scenario_npv.keys())
    shift_note = f"Scenario shifts: {shift_labels}."

    if is_bootstrapped:
        ci = request.curve_inputs  # type: ignore[union-attr]
        n_dep = len(ci.deposits or [])
        n_fra = len(ci.fras or [])
        n_swp = len(ci.swaps or [])
        assumptions = [
            f"Bootstrapped mixed curve: {n_dep} deposit(s), {n_fra} FRA(s), {n_swp} swap(s).",
            (
                f"Curve: valuation date {curve_val_date.isoformat()}, "
                f"{ci.payment_frequency} coupons, {ci.day_count}."
            ),
            fixed_rate_note,
            shift_note,
            "Parallel shift: all continuously-compounded zero rates shifted by the same amount.",
            "Indicative only. Not suitable for production risk management or hedging decisions.",
        ]
    else:
        assumptions = [
            "Flat annual market rate: 8.00% (ZAR JIBAR proxy).",
            fixed_rate_note,
            shift_note,
            "Parallel shift: all continuously-compounded zero rates shifted by the same amount.",
            "Indicative only. Not suitable for production risk management or hedging decisions.",
        ]

    return IRSDirectScenarioResponse(
        request_id=rid,
        instrument_type="irs",
        currency=request.currency,
        status="indicative",
        scenario_npv=scenario_npv,
        base_npv=base_npv,
        curve_source=curve_source,
        assumptions=assumptions,
        warnings=[],
    )


# ---------------------------------------------------------------------------
# Bond risk helpers
# ---------------------------------------------------------------------------


def _bond_risk_unsupported(
    rid: str,
    warnings: list[str],
) -> BondRiskResponse:
    """Return a graceful unsupported BondRiskResponse."""
    return BondRiskResponse(
        request_id=rid,
        status="unsupported",
        dirty_price=0.0,
        dv01=0.0,
        modified_duration=0.0,
        macaulay_duration=0.0,
        convexity=0.0,
        assumptions=["Bond risk attempted under the quant-core fixed-rate bond engine."],
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Bond risk route
# ---------------------------------------------------------------------------


@router.post("/risk/bond", response_model=BondRiskResponse)
def risk_bond(request: BondRiskRequest) -> BondRiskResponse:
    """
    Compute DV01 and modified duration for a fixed-rate bond.

    Accepts a fully-specified ``BondRiskRequest`` and an optional
    ``curve_inputs`` block.  When ``curve_inputs`` is supplied a mixed
    deposit/FRA/swap discount curve is bootstrapped; otherwise the flat 8%
    ZAR JIBAR proxy is used.

    DV01 and modified duration are computed by bump-and-reprice: all
    continuously-compounded zero rates are shifted by +1 bp in parallel and
    the bond is repriced.  DV01 = price_base − price_bumped;
    modified_duration = dv01 / dirty_price_base × 10,000.
    """
    rid = request.request_id or str(uuid.uuid4())

    # ------------------------------------------------------------------ #
    # Step 1: parse dates (already ISO-validated by schema)
    # ------------------------------------------------------------------ #
    try:
        val_date = date.fromisoformat(request.valuation_date)
        issue_date = date.fromisoformat(request.issue_date)
        maturity_date = date.fromisoformat(request.maturity_date)
    except ValueError as exc:
        return _bond_risk_unsupported(rid, [f"Date parse error: {exc}"])

    # ------------------------------------------------------------------ #
    # Step 2: resolve day count
    # ------------------------------------------------------------------ #
    from app.services.pricer import _DAY_COUNT_MAP  # local import to avoid circular
    resolved_day_count = _DAY_COUNT_MAP.get(request.day_count)
    if resolved_day_count is None:
        return _bond_risk_unsupported(
            rid, [f"Unsupported day_count '{request.day_count}'."]
        )

    # ------------------------------------------------------------------ #
    # Step 3: construct FixedRateBond
    # ------------------------------------------------------------------ #
    try:
        bond = FixedRateBond(
            valuation_date=val_date,
            issue_date=issue_date,
            maturity_date=maturity_date,
            face_value=request.face_value,
            coupon_rate=request.coupon_rate,
            coupon_frequency=request.coupon_frequency,
            day_count=resolved_day_count,
        )
    except ValueError as exc:
        return _bond_risk_unsupported(rid, [f"Bond construction error: {exc}"])

    # ------------------------------------------------------------------ #
    # Step 4: build discount curve (flat or bootstrapped)
    # ------------------------------------------------------------------ #
    from app.services.pricer import (  # local import to avoid circular
        _FLAT_CURVE_DAY_COUNT,
        _FLAT_MARKET_RATE,
        _build_curve,
    )

    if request.curve_inputs is None:
        # Flat proxy curve aligned with bond coupon schedule (same as /price/bond).
        _step = _BOND_FREQ_MONTHS[request.coupon_frequency]
        _sched: list[date] = []
        _k = 1
        while True:
            _d = add_months(issue_date, _k * _step)
            if _d >= maturity_date:
                break
            _sched.append(_d)
            _k += 1
        _sched.append(maturity_date)
        _pillar_dates = [d for d in _sched if d > val_date]
        if not _pillar_dates:
            return _bond_risk_unsupported(
                rid, ["No remaining cashflow dates after valuation_date."]
            )
        _pillar_dfs = [
            1.0 / (1.0 + _FLAT_MARKET_RATE * accrual_fraction(
                val_date, d, resolved_day_count
            ))
            for d in _pillar_dates
        ]
        curve: DiscountCurve = DiscountCurve(val_date, _pillar_dates, _pillar_dfs)
        is_bootstrapped = False
        curve_val_date = val_date
    else:
        delta_days = (maturity_date - val_date).days
        tenor_years = max(1, -(-delta_days // 365))
        try:
            curve, is_bootstrapped, curve_val_date, _ = _build_curve(
                request.curve_inputs,
                val_date,
                tenor_years,
                request.coupon_frequency,
                _FLAT_CURVE_DAY_COUNT,
            )
        except ValueError as exc:
            return _bond_risk_unsupported(rid, [f"Curve construction error: {exc}"])

    # ------------------------------------------------------------------ #
    # Step 5: price and compute risk
    # ------------------------------------------------------------------ #
    try:
        pricing_result = price_bond(bond, curve)
        dv01_value = bond_dv01(bond, curve)
        duration_value = bond_modified_duration(bond, curve)
        macaulay_value = bond_macaulay_duration(bond, curve)
        convexity_value = bond_convexity(bond, curve)
    except ValueError as exc:
        return _bond_risk_unsupported(rid, [f"Pricing/risk error: {exc}"])

    # ------------------------------------------------------------------ #
    # Step 6: build assumptions
    # ------------------------------------------------------------------ #
    if is_bootstrapped:
        ci = request.curve_inputs  # type: ignore[union-attr]
        n_dep = len(ci.deposits or [])
        n_fra = len(ci.fras or [])
        n_swp = len(ci.swaps or [])
        assumptions = [
            f"Bootstrapped mixed curve: {n_dep} deposit(s), {n_fra} FRA(s), {n_swp} swap(s).",
            f"Curve: valuation date {curve_val_date.isoformat()}, "
            f"{ci.payment_frequency} coupons, {ci.day_count}.",
            f"Bond day-count: {request.day_count}.",
            f"Coupon frequency: {request.coupon_frequency}.",
            "DV01: parallel +1bp CC zero-rate bump; DV01 = dirty_price_base − dirty_price_bumped.",
            "Modified duration = DV01 / dirty_price × 10,000.",
            "Macaulay duration = weighted-average time to cashflows (sum(t_i * PV_i) / sum(PV_i)).",
            "Convexity: central finite-difference (P_minus + P_plus - 2*P0) / (P0 * dy²).",
            "Indicative only. Not suitable for production risk management or hedging decisions.",
        ]
    else:
        assumptions = [
            "Flat discount curve: 8.00% (ZAR JIBAR proxy).",
            f"Bond day-count: {request.day_count}.",
            f"Coupon frequency: {request.coupon_frequency}.",
            "DV01: parallel +1bp CC zero-rate bump; DV01 = dirty_price_base − dirty_price_bumped.",
            "Modified duration = DV01 / dirty_price × 10,000.",
            "Macaulay duration = weighted-average time to cashflows (sum(t_i * PV_i) / sum(PV_i)).",
            "Convexity: central finite-difference (P_minus + P_plus - 2*P0) / (P0 * dy²).",
            "Indicative only. Not suitable for production risk management or hedging decisions.",
        ]

    return BondRiskResponse(
        request_id=rid,
        status="indicative",
        dirty_price=pricing_result.dirty_price,
        dv01=dv01_value,
        modified_duration=duration_value,
        macaulay_duration=macaulay_value,
        convexity=convexity_value,
        assumptions=assumptions,
        warnings=[],
    )
