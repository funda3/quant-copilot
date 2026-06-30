from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter

from app.schemas.price import (
    BondCashflowRequest,
    BondCashflowResponse,
    BondCashflowRow,
    BondPricingRequest,
    BondPricingResponse,
    BondYTMRequest,
    BondYTMResponse,
    EquityOptionPriceRequest,
    EquityOptionPriceResponse,
    FXForwardPriceRequest,
    FXForwardPriceResponse,
    FXOptionPriceRequest,
    FXOptionPriceResponse,
    FXSwapPriceRequest,
    FXSwapPriceResponse,
    FRAPriceRequest,
    FRAPriceResponse,
    IRSBreakdownRequest,
    IRSBreakdownResponse,
    IRSCashflowRequest,
    IRSCashflowResponse,
    IRSCashflowRow,
    IRSDirectBreakdownRequest,
    IRSDirectBreakdownResponse,
    IRSDirectCashflowRequest,
    IRSDirectCashflowResponse,
    IRSDirectFairRateRequest,
    IRSDirectFairRateResponse,
    IRSDirectPriceRequest,
    IRSDirectPriceResponse,
    IRSFairRateRequest,
    IRSFairRateResponse,
    PricingRequest,
    PricingResponse,
)
from app.services.pricer import (
    _DAY_COUNT_MAP,
    _FLAT_CURVE_DAY_COUNT,
    _FLAT_MARKET_RATE,
    _build_curve,
    compute_price,
    parse_tenor_years,
)
from quant_core.conventions.day_count import accrual_fraction
from quant_core.curves.discount_curve import DiscountCurve
from quant_core.instruments.bond import FixedRateBond
from quant_core.instruments.equity_option import EuropeanEquityOption
from quant_core.instruments.fx_forward import FXForward
from quant_core.instruments.fx_option import EuropeanFXOption
from quant_core.instruments.fx_swap import FXSwap
from quant_core.instruments.fra import FRA
from quant_core.instruments.irs import VanillaIRS
from quant_core.pricing.bond_pricer import FREQ_MONTHS as _BOND_FREQ_MONTHS
from quant_core.pricing.bond_pricer import bond_cashflow_schedule, price_bond, solve_bond_ytm
from quant_core.pricing.equity_option_pricer import price_european_equity_option
from quant_core.pricing.fx_forward_pricer import price_fx_forward
from quant_core.pricing.fx_option_pricer import price_european_fx_option
from quant_core.pricing.fx_swap_pricer import price_fx_swap
from quant_core.pricing.fra_pricer import price_fra
from quant_core.pricing.irs_pricer import (
    fixed_leg_annuity,
    irs_cashflow_schedule,
    irs_valuation_breakdown,
    price_irs,
    solve_irs_fair_rate,
)
from quant_core.utils.date_utils import add_months

router = APIRouter(tags=["price"])


@router.post("/price", response_model=PricingResponse)
def price(request: PricingRequest) -> PricingResponse:
    """
    Accept extracted trade fields and return an indicative IRS price.

    Supported: instrument_type=irs, currency=ZAR, floating_index=JIBAR.
    All other combinations return status=unsupported with explanatory warnings.
    """
    result = compute_price(
        extracted_fields=request.extracted_fields,
        request_id=request.request_id,
        curve_inputs=request.curve_inputs,
    )
    return PricingResponse(**result)


# ---------------------------------------------------------------------------
# Bond pricing route
# ---------------------------------------------------------------------------


def _bond_unsupported(
    rid: str,
    warnings: list[str],
) -> BondPricingResponse:
    """Return a graceful unsupported BondPricingResponse."""
    return BondPricingResponse(
        request_id=rid,
        status="unsupported",
        clean_price=0.0,
        dirty_price=0.0,
        accrued_interest=0.0,
        n_remaining_coupons=0,
        assumptions=["Bond pricing attempted under the quant-core fixed-rate bond engine."],
        warnings=warnings,
    )


def _build_bond_curve(
    curve_inputs,
    val_date: date,
    issue_date: date,
    maturity_date: date,
    coupon_frequency: str,
    resolved_day_count,
) -> tuple[DiscountCurve, bool, date]:
    """
    Build a discount curve for bond pricing or cashflow scheduling.

    When *curve_inputs* is ``None`` a flat 8% ZAR JIBAR proxy curve is
    constructed with pillars aligned to the bond's issue-date-relative coupon
    schedule so that ``DiscountCurve.df()`` never fails for seasoned bonds.

    When *curve_inputs* is supplied the existing mixed deposit/FRA/swap
    bootstrap path is used.

    Returns ``(curve, is_bootstrapped, curve_val_date)``.
    Raises ``ValueError`` with a descriptive message on failure.
    """
    if curve_inputs is None:
        _step = _BOND_FREQ_MONTHS[coupon_frequency]
        _sched: list[date] = []
        _k = 1
        while True:
            _d = add_months(issue_date, _k * _step)
            if _d >= maturity_date:
                break
            _sched.append(_d)
            _k += 1
        _sched.append(maturity_date)
        # Retain only dates strictly after val_date (DiscountCurve invariant).
        _pillar_dates = [d for d in _sched if d > val_date]
        if not _pillar_dates:
            raise ValueError("No remaining cashflow dates after valuation_date.")
        _pillar_dfs = [
            1.0 / (1.0 + _FLAT_MARKET_RATE * accrual_fraction(val_date, d, resolved_day_count))
            for d in _pillar_dates
        ]
        return DiscountCurve(val_date, _pillar_dates, _pillar_dfs), False, val_date
    else:
        delta_days = (maturity_date - val_date).days
        tenor_years = max(1, -(-delta_days // 365))
        try:
            curve, is_bootstrapped, curve_val_date, _ = _build_curve(
                curve_inputs,
                val_date,
                tenor_years,
                coupon_frequency,
                _FLAT_CURVE_DAY_COUNT,
            )
        except ValueError as exc:
            raise ValueError(f"Curve construction error: {exc}") from exc
        return curve, is_bootstrapped, curve_val_date


def _fra_error(rid: str, warnings: list[str]) -> FRAPriceResponse:
    """Return a graceful FRA pricing error response."""
    return FRAPriceResponse(
        request_id=rid,
        status="error",
        forward_rate=0.0,
        year_fraction=0.0,
        discount_factor_to_payment=0.0,
        payoff_undiscounted=0.0,
        pv=0.0,
        curve_source="none",
        assumptions=[],
        warnings=warnings,
    )


def _fx_forward_error(
    rid: str,
    domestic_currency: str,
    foreign_currency: str,
    warnings: list[str],
) -> FXForwardPriceResponse:
    """Return a graceful FX forward pricing error response."""
    return FXForwardPriceResponse(
        request_id=rid,
        status="error",
        domestic_currency=domestic_currency,
        foreign_currency=foreign_currency,
        year_fraction=0.0,
        domestic_discount_factor=0.0,
        foreign_discount_factor=0.0,
        implied_forward_rate=0.0,
        forward_points=0.0,
        payoff_undiscounted_domestic=0.0,
        present_value_domestic=0.0,
        pv_currency=domestic_currency,
        rate_source="none",
        assumptions=[],
        warnings=warnings,
    )


def _fx_swap_error(
    rid: str,
    domestic_currency: str,
    foreign_currency: str,
    warnings: list[str],
) -> FXSwapPriceResponse:
    """Return a graceful FX swap pricing error response."""
    return FXSwapPriceResponse(
        request_id=rid,
        status="error",
        domestic_currency=domestic_currency,
        foreign_currency=foreign_currency,
        year_fraction_near=0.0,
        year_fraction_far=0.0,
        domestic_discount_factor_near=0.0,
        domestic_discount_factor_far=0.0,
        near_leg_value_domestic=0.0,
        far_leg_value_domestic=0.0,
        swap_points=0.0,
        present_value_domestic=0.0,
        pv_currency=domestic_currency,
        rate_source="none",
        assumptions=[],
        warnings=warnings,
    )


def _fx_option_error(
    rid: str,
    domestic_currency: str,
    foreign_currency: str,
    warnings: list[str],
) -> FXOptionPriceResponse:
    """Return a graceful FX option pricing error response."""
    return FXOptionPriceResponse(
        request_id=rid,
        status="error",
        domestic_currency=domestic_currency,
        foreign_currency=foreign_currency,
        year_fraction=0.0,
        settlement_year_fraction=0.0,
        domestic_discount_factor=0.0,
        foreign_discount_factor=0.0,
        forward_rate=0.0,
        premium_domestic=0.0,
        premium_foreign=0.0,
        delta=0.0,
        gamma=0.0,
        vega=0.0,
        pv_currency=domestic_currency,
        model_source="none",
        assumptions=[],
        warnings=warnings,
    )


def _equity_option_error(
    rid: str,
    currency: str,
    underlying_name: str | None,
    warnings: list[str],
) -> EquityOptionPriceResponse:
    """Return a graceful equity option pricing error response."""
    return EquityOptionPriceResponse(
        request_id=rid,
        status="error",
        underlying_name=underlying_name,
        currency=currency,
        year_fraction=0.0,
        discount_factor=0.0,
        dividend_discount_factor=0.0,
        forward_price=0.0,
        premium=0.0,
        delta=0.0,
        gamma=0.0,
        vega=0.0,
        pv_currency=currency,
        model_source="none",
        assumptions=[],
        warnings=warnings,
    )


def _build_fra_flat_curve(
    val_date: date,
    start_date: date,
    end_date: date,
    resolved_day_count,
) -> DiscountCurve:
    """
    Build a flat fallback curve with exact FRA start/end pillars.

    This avoids out-of-domain errors for short-dated FRAs where the generic
    flat-curve schedule may not include the exact accrual start date.
    """
    pillar_dates = [start_date, end_date]
    discount_factors = [
        1.0 / (1.0 + _FLAT_MARKET_RATE * accrual_fraction(val_date, d, resolved_day_count))
        for d in pillar_dates
    ]
    return DiscountCurve(val_date, pillar_dates, discount_factors)


@router.post("/price/fra", response_model=FRAPriceResponse)
def price_fra_endpoint(request: FRAPriceRequest) -> FRAPriceResponse:
    """
    Price a deterministic FRA from a fully structured request.

    The backend remains a thin orchestration layer: it resolves dates and day
    count, builds either the flat fallback curve or the existing bootstrapped
    mixed curve, constructs ``quant_core.instruments.fra.FRA``, and delegates
    pricing to ``quant_core.pricing.fra_pricer.price_fra``.
    """
    rid = request.request_id or str(uuid.uuid4())

    try:
        val_date = date.fromisoformat(request.valuation_date)
        start_date = date.fromisoformat(request.start_date)
        end_date = date.fromisoformat(request.end_date)
    except ValueError as exc:
        return _fra_error(rid, [f"Date parse error: {exc}"])

    resolved_day_count = _DAY_COUNT_MAP.get(request.day_count)
    if resolved_day_count is None:
        return _fra_error(rid, [f"Unsupported day_count '{request.day_count}'."])

    try:
        if request.curve_inputs is None:
            curve = _build_fra_flat_curve(
                val_date,
                start_date,
                end_date,
                resolved_day_count,
            )
            is_bootstrapped = False
            curve_val_date = val_date
        else:
            delta_days = (end_date - val_date).days
            tenor_years = max(1, -(-delta_days // 365))
            curve, is_bootstrapped, curve_val_date, _ = _build_curve(
                request.curve_inputs,
                val_date,
                tenor_years,
                "annual",
                resolved_day_count,
            )
    except ValueError as exc:
        return _fra_error(rid, [f"Curve construction error: {exc}"])

    curve_source = "bootstrapped_mixed_curve" if is_bootstrapped else "flat_fallback"

    try:
        fra = FRA(
            valuation_date=curve_val_date,
            start_date=start_date,
            end_date=end_date,
            notional=request.notional,
            contract_rate=request.contract_rate,
            day_count=resolved_day_count,
            position=request.position,
        )
        result = price_fra(fra, curve)
    except ValueError as exc:
        return _fra_error(rid, [f"Pricing error: {exc}"])

    if is_bootstrapped:
        ci = request.curve_inputs  # type: ignore[union-attr]
        assumptions = [
            (
                f"Bootstrapped mixed curve: {len(ci.deposits or [])} deposit(s), "
                f"{len(ci.fras or [])} FRA quote(s), {len(ci.swaps or [])} swap(s)."
            ),
            f"Curve: valuation date {curve_val_date.isoformat()}, {ci.payment_frequency} coupons, {ci.day_count}.",
            "FRA convention: payer = pay fixed / receive floating; receiver = receive fixed / pay floating.",
            "Forward rate inferred from curve discount factors: (df(start)/df(end) - 1) / accrual_fraction.",
            "Payoff discounted from payment date end_date back to valuation_date using df(end_date).",
            "Indicative only. Not suitable for production pricing or trading decisions.",
        ]
    else:
        assumptions = [
            f"Flat annual market rate: {_FLAT_MARKET_RATE:.4%} (ZAR JIBAR proxy).",
            "FRA convention: payer = pay fixed / receive floating; receiver = receive fixed / pay floating.",
            "Forward rate inferred from curve discount factors: (df(start)/df(end) - 1) / accrual_fraction.",
            "Payoff discounted from payment date end_date back to valuation_date using df(end_date).",
            "Flat fallback curve is built with exact FRA start and end pillars.",
            "Indicative only. Not suitable for production pricing or trading decisions.",
        ]

    return FRAPriceResponse(
        request_id=rid,
        status="indicative",
        forward_rate=result.forward_rate,
        year_fraction=result.year_fraction,
        discount_factor_to_payment=result.discount_factor_to_payment,
        payoff_undiscounted=result.payoff_undiscounted,
        pv=result.pv,
        curve_source=curve_source,
        assumptions=assumptions,
        warnings=[],
    )


@router.post("/price/fx-forward", response_model=FXForwardPriceResponse)
def price_fx_forward_endpoint(request: FXForwardPriceRequest) -> FXForwardPriceResponse:
    """Price a deterministic FX forward from flat domestic and foreign simple rates."""
    rid = request.request_id or str(uuid.uuid4())

    resolved_day_count = _DAY_COUNT_MAP.get(request.day_count)
    if resolved_day_count is None:
        return _fx_forward_error(
            rid,
            request.domestic_currency,
            request.foreign_currency,
            [f"Unsupported day_count: {request.day_count}"],
        )

    try:
        fx_forward = FXForward(
            valuation_date=date.fromisoformat(request.valuation_date),
            maturity_date=date.fromisoformat(request.maturity_date),
            notional_foreign=request.notional_foreign,
            spot_rate=request.spot_rate,
            contract_forward_rate=request.contract_forward_rate,
            domestic_rate=request.domestic_rate,
            foreign_rate=request.foreign_rate,
            domestic_currency=request.domestic_currency,
            foreign_currency=request.foreign_currency,
            day_count=resolved_day_count,
            position=request.position,
        )
        result = price_fx_forward(fx_forward)
    except ValueError as exc:
        return _fx_forward_error(
            rid,
            request.domestic_currency,
            request.foreign_currency,
            [f"Pricing error: {exc}"],
        )

    assumptions = [
        (
            "Quote convention: "
            f"{request.domestic_currency}/{request.foreign_currency} means domestic-currency units per 1 foreign unit."
        ),
        "FX forward convention: long_foreign = buy foreign / sell domestic at maturity; short_foreign = opposite.",
        "Domestic and foreign discount factors use flat simple annualized rates: df = 1 / (1 + r * t).",
        "Implied forward is computed from covered interest parity: spot * df_foreign / df_domestic.",
        f"Present value is reported in {request.domestic_currency}.",
        "Indicative only. Not suitable for production pricing or trading decisions.",
    ]

    return FXForwardPriceResponse(
        request_id=rid,
        status="indicative",
        domestic_currency=request.domestic_currency,
        foreign_currency=request.foreign_currency,
        year_fraction=result.year_fraction,
        domestic_discount_factor=result.domestic_discount_factor,
        foreign_discount_factor=result.foreign_discount_factor,
        implied_forward_rate=result.implied_forward_rate,
        forward_points=result.forward_points,
        payoff_undiscounted_domestic=result.payoff_undiscounted_domestic,
        present_value_domestic=result.present_value_domestic,
        pv_currency=request.domestic_currency,
        rate_source="flat_interest_rate_inputs",
        assumptions=assumptions,
        warnings=[],
    )


@router.post("/price/fx-swap", response_model=FXSwapPriceResponse)
def price_fx_swap_endpoint(request: FXSwapPriceRequest) -> FXSwapPriceResponse:
    """Price a deterministic deliverable FX swap from flat domestic discounting."""
    rid = request.request_id or str(uuid.uuid4())

    resolved_day_count = _DAY_COUNT_MAP.get(request.day_count)
    if resolved_day_count is None:
        return _fx_swap_error(
            rid,
            request.domestic_currency,
            request.foreign_currency,
            [f"Unsupported day_count: {request.day_count}"],
        )

    try:
        fx_swap = FXSwap(
            valuation_date=date.fromisoformat(request.valuation_date),
            near_settlement_date=date.fromisoformat(request.near_settlement_date),
            far_settlement_date=date.fromisoformat(request.far_settlement_date),
            spot_rate=request.spot_rate,
            near_rate=request.near_rate,
            far_rate=request.far_rate,
            notional_foreign=request.notional_foreign,
            domestic_currency=request.domestic_currency,
            foreign_currency=request.foreign_currency,
            domestic_rate=request.domestic_rate,
            day_count=resolved_day_count,
            position=request.position,
        )
        result = price_fx_swap(fx_swap)
    except ValueError as exc:
        return _fx_swap_error(
            rid,
            request.domestic_currency,
            request.foreign_currency,
            [f"Pricing error: {exc}"],
        )

    assumptions = [
        (
            "Quote convention: "
            f"{request.domestic_currency}/{request.foreign_currency} means domestic-currency units per 1 foreign unit."
        ),
        "FX swap convention: long_foreign = receive foreign / pay domestic on the near leg, then reverse on the far leg; short_foreign = opposite.",
        "Near and far leg domestic values are computed from fixed exchange rates against current spot.",
        "Domestic discounting uses a flat simple annualized rate: df = 1 / (1 + r_dom * t).",
        f"Present value is reported in {request.domestic_currency}.",
        "Indicative only. Not suitable for production pricing or trading decisions.",
    ]

    return FXSwapPriceResponse(
        request_id=rid,
        status="indicative",
        domestic_currency=request.domestic_currency,
        foreign_currency=request.foreign_currency,
        year_fraction_near=result.year_fraction_near,
        year_fraction_far=result.year_fraction_far,
        domestic_discount_factor_near=result.domestic_discount_factor_near,
        domestic_discount_factor_far=result.domestic_discount_factor_far,
        near_leg_value_domestic=result.near_leg_value_domestic,
        far_leg_value_domestic=result.far_leg_value_domestic,
        swap_points=result.swap_points,
        present_value_domestic=result.present_value_domestic,
        pv_currency=request.domestic_currency,
        rate_source="flat_domestic_discount_rate_input",
        assumptions=assumptions,
        warnings=[],
    )


@router.post("/price/fx-option", response_model=FXOptionPriceResponse)
def price_fx_option_endpoint(request: FXOptionPriceRequest) -> FXOptionPriceResponse:
    """Price a European deliverable FX option under Garman-Kohlhagen."""
    rid = request.request_id or str(uuid.uuid4())

    resolved_day_count = _DAY_COUNT_MAP.get(request.day_count)
    if resolved_day_count is None:
        return _fx_option_error(
            rid,
            request.domestic_currency,
            request.foreign_currency,
            [f"Unsupported day_count: {request.day_count}"],
        )

    try:
        expiry_date = date.fromisoformat(request.expiry_date)
        settlement_date = (
            date.fromisoformat(request.settlement_date)
            if request.settlement_date is not None
            else expiry_date
        )
        fx_option = EuropeanFXOption(
            valuation_date=date.fromisoformat(request.valuation_date),
            expiry_date=expiry_date,
            settlement_date=settlement_date,
            spot_rate=request.spot_rate,
            strike_rate=request.strike_rate,
            domestic_rate=request.domestic_rate,
            foreign_rate=request.foreign_rate,
            volatility=request.volatility,
            notional_foreign=request.notional_foreign,
            option_type=request.option_type,
            position=request.position,
            domestic_currency=request.domestic_currency,
            foreign_currency=request.foreign_currency,
            day_count=resolved_day_count,
        )
        result = price_european_fx_option(fx_option)
    except ValueError as exc:
        return _fx_option_error(
            rid,
            request.domestic_currency,
            request.foreign_currency,
            [f"Pricing error: {exc}"],
        )

    assumptions = [
        (
            "Quote convention: "
            f"{request.domestic_currency}/{request.foreign_currency} means domestic-currency units per 1 foreign unit."
        ),
        "Option convention: call = right to buy foreign / sell domestic at the strike; put = right to sell foreign / buy domestic.",
        "Position convention: long = own the option; short = written option with opposite premium and Greeks.",
        "Model: vanilla European FX option priced under Garman-Kohlhagen with flat continuously compounded domestic and foreign rates.",
        (
            f"Settlement date used for forward and discount factors: {settlement_date.isoformat()}. "
            "If settlement_date is omitted, it defaults to expiry_date."
        ),
        "premium_foreign is derived by converting domestic premium at the current spot rate.",
        f"Present value is reported in {request.domestic_currency}.",
        "Indicative only. Not suitable for production pricing or trading decisions.",
    ]

    return FXOptionPriceResponse(
        request_id=rid,
        status="indicative",
        domestic_currency=request.domestic_currency,
        foreign_currency=request.foreign_currency,
        year_fraction=result.year_fraction,
        settlement_year_fraction=result.settlement_year_fraction,
        domestic_discount_factor=result.domestic_discount_factor,
        foreign_discount_factor=result.foreign_discount_factor,
        forward_rate=result.forward_rate,
        premium_domestic=result.premium_domestic,
        premium_foreign=result.premium_foreign,
        delta=result.delta,
        gamma=result.gamma,
        vega=result.vega,
        pv_currency=request.domestic_currency,
        model_source="garman_kohlhagen",
        assumptions=assumptions,
        warnings=[],
    )


@router.post("/price/equity-option", response_model=EquityOptionPriceResponse)
def price_equity_option_endpoint(
    request: EquityOptionPriceRequest,
) -> EquityOptionPriceResponse:
    """Price a European equity option under Black-Scholes-Merton."""
    rid = request.request_id or str(uuid.uuid4())

    resolved_day_count = _DAY_COUNT_MAP.get(request.day_count)
    if resolved_day_count is None:
        return _equity_option_error(
            rid,
            request.currency,
            request.underlying_name,
            [f"Unsupported day_count: {request.day_count}"],
        )

    try:
        equity_option = EuropeanEquityOption(
            valuation_date=date.fromisoformat(request.valuation_date),
            expiry_date=date.fromisoformat(request.expiry_date),
            spot_price=request.spot_price,
            strike_price=request.strike_price,
            risk_free_rate=request.risk_free_rate,
            dividend_yield=request.dividend_yield,
            volatility=request.volatility,
            quantity_shares=request.quantity_shares,
            option_type=request.option_type,
            position=request.position,
            currency=request.currency,
            day_count=resolved_day_count,
            underlying_name=request.underlying_name,
        )
        result = price_european_equity_option(equity_option)
    except ValueError as exc:
        return _equity_option_error(
            rid,
            request.currency,
            request.underlying_name,
            [f"Pricing error: {exc}"],
        )

    assumptions = [
        "Option convention: call = right to buy the underlying at strike on expiry; put = right to sell the underlying at strike on expiry.",
        "Quantity convention: quantity_shares scales premium and Greeks by the number of underlying shares.",
        "Position convention: long = own the option; short = written option with opposite premium and Greeks.",
        "Model: vanilla European equity option priced under Black-Scholes-Merton with flat continuously compounded risk-free rate and dividend yield.",
        (
            f"Underlying label: {request.underlying_name}."
            if request.underlying_name
            else "Underlying label omitted; pricing uses the supplied spot, strike, rates, and volatility only."
        ),
        f"Present value is reported in {request.currency}.",
        "Indicative only. Not suitable for production pricing or trading decisions.",
    ]

    return EquityOptionPriceResponse(
        request_id=rid,
        status="indicative",
        underlying_name=request.underlying_name,
        currency=request.currency,
        year_fraction=result.year_fraction,
        discount_factor=result.discount_factor,
        dividend_discount_factor=result.dividend_discount_factor,
        forward_price=result.forward_price,
        premium=result.premium,
        delta=result.delta,
        gamma=result.gamma,
        vega=result.vega,
        pv_currency=request.currency,
        model_source="black_scholes_merton",
        assumptions=assumptions,
        warnings=[],
    )


@router.post("/price/bond", response_model=BondPricingResponse)
def price_bond_endpoint(request: BondPricingRequest) -> BondPricingResponse:
    """
    Price a fixed-rate bond off a discount curve.

    Accepts a fully-specified ``BondPricingRequest`` (all dates, face value,
    coupon, frequency, day count) plus an optional ``curve_inputs`` block.

    When ``curve_inputs`` is supplied a mixed deposit/FRA/swap discount curve
    is bootstrapped; otherwise the flat 8% ZAR JIBAR proxy is used.

    No YTM solver.  Returns clean price, dirty price, accrued interest, and
    remaining coupon count.
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
        return _bond_unsupported(rid, [f"Date parse error: {exc}"])

    # ------------------------------------------------------------------ #
    # Step 2: resolve day count
    # ------------------------------------------------------------------ #
    resolved_day_count = _DAY_COUNT_MAP.get(request.day_count)
    if resolved_day_count is None:
        return _bond_unsupported(
            rid, [f"Unsupported day_count '{request.day_count}'."]
        )

    # ------------------------------------------------------------------ #
    # Step 3: construct FixedRateBond (validates economics)
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
        return _bond_unsupported(rid, [f"Bond construction error: {exc}"])

    # ------------------------------------------------------------------ #
    # Step 4: build discount curve
    # ------------------------------------------------------------------ #
    try:
        curve, is_bootstrapped, curve_val_date = _build_bond_curve(
            request.curve_inputs,
            val_date,
            issue_date,
            maturity_date,
            request.coupon_frequency,
            resolved_day_count,
        )
    except ValueError as exc:
        return _bond_unsupported(rid, [str(exc)])

    # ------------------------------------------------------------------ #
    # Step 5: price
    # ------------------------------------------------------------------ #
    try:
        result = price_bond(bond, curve)
    except ValueError as exc:
        return _bond_unsupported(rid, [f"Pricing error: {exc}"])

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
            "Dirty price = PV of all remaining cashflows (coupons + principal).",
            "Clean price = dirty price − accrued interest.",
            "Indicative only. Not suitable for production pricing or trading decisions.",
        ]
    else:
        assumptions = [
            "Flat discount curve: 8.00% (ZAR JIBAR proxy).",
            f"Bond day-count: {request.day_count}.",
            f"Coupon frequency: {request.coupon_frequency}.",
            "Dirty price = PV of all remaining cashflows (coupons + principal).",
            "Clean price = dirty price − accrued interest.",
            "Indicative only. Not suitable for production pricing or trading decisions.",
        ]

    return BondPricingResponse(
        request_id=rid,
        status="indicative",
        clean_price=result.clean_price,
        dirty_price=result.dirty_price,
        accrued_interest=result.accrued_interest,
        n_remaining_coupons=result.n_remaining_coupons,
        assumptions=assumptions,
        warnings=[],
    )


# ---------------------------------------------------------------------------
# Bond YTM solver route
# ---------------------------------------------------------------------------


def _bond_ytm_error(rid: str, market_dirty_price: float, warnings: list[str]) -> BondYTMResponse:
    """Return a graceful error BondYTMResponse."""
    return BondYTMResponse(
        request_id=rid,
        status="error",
        market_dirty_price=market_dirty_price,
        ytm=float("nan"),
        assumptions=[],
        warnings=warnings,
    )


@router.post("/price/bond/ytm", response_model=BondYTMResponse)
def price_bond_ytm_endpoint(request: BondYTMRequest) -> BondYTMResponse:
    """
    Solve for the flat annual yield-to-maturity (YTM) of a fixed-rate bond.

    Accepts a fully-specified ``BondYTMRequest`` (all dates, face value, coupon,
    frequency, day count) plus the observed *market_dirty_price*.

    The YTM *y* satisfies::

        price_bond(bond, flat_curve(valuation_date, y, tenor, freq, dc)).dirty_price
            == market_dirty_price

    where ``flat_curve`` uses the simple-rate convention
    ``df(t) = 1 / (1 + y × τ)``.

    A deterministic bisection solver is used; convergence tolerance is 1e-10
    in price units.  If the market price cannot be bracketed by any yield in
    [0%, 500%] the endpoint returns ``status="error"`` with an explanatory
    warning.
    """
    rid = request.request_id or str(uuid.uuid4())

    # Parse dates (schema already validates ISO format).
    try:
        val_date = date.fromisoformat(request.valuation_date)
        issue_date = date.fromisoformat(request.issue_date)
        maturity_date = date.fromisoformat(request.maturity_date)
    except ValueError as exc:
        return _bond_ytm_error(rid, request.market_dirty_price, [f"Date parse error: {exc}"])

    # Resolve day count.
    resolved_day_count = _DAY_COUNT_MAP.get(request.day_count)
    if resolved_day_count is None:
        return _bond_ytm_error(
            rid, request.market_dirty_price,
            [f"Unsupported day_count '{request.day_count}'."],
        )

    # Construct bond (validates economics).
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
        return _bond_ytm_error(rid, request.market_dirty_price, [f"Bond construction error: {exc}"])

    # Solve YTM via bisection.
    try:
        ytm = solve_bond_ytm(bond, request.market_dirty_price)
    except ValueError as exc:
        return _bond_ytm_error(rid, request.market_dirty_price, [f"YTM solver error: {exc}"])

    assumptions = [
        "YTM solved by bisection against a flat simple-rate discount curve.",
        f"Bond day-count: {request.day_count}.",
        f"Coupon frequency: {request.coupon_frequency}.",
        "Flat yield convention: df(t) = 1 / (1 + y × τ), where τ is the year fraction.",
        "Convergence tolerance: 1e-10 price units.",
        "Indicative only. Not suitable for production pricing or trading decisions.",
    ]

    return BondYTMResponse(
        request_id=rid,
        status="solved",
        market_dirty_price=request.market_dirty_price,
        ytm=ytm,
        assumptions=assumptions,
        warnings=[],
    )


# ---------------------------------------------------------------------------
# Bond cashflow schedule route
# ---------------------------------------------------------------------------


def _bond_cashflows_error(rid: str, warnings: list[str]) -> BondCashflowResponse:
    """Return a graceful error BondCashflowResponse."""
    return BondCashflowResponse(
        request_id=rid,
        status="error",
        dirty_price=0.0,
        n_remaining_coupons=0,
        cashflows=[],
        assumptions=[],
        warnings=warnings,
    )


@router.post("/price/bond/cashflows", response_model=BondCashflowResponse)
def price_bond_cashflows_endpoint(request: BondCashflowRequest) -> BondCashflowResponse:
    """
    Return the full remaining cashflow schedule for a fixed-rate bond.

    Each row exposes payment date, accrual period, year fraction, coupon and
    principal cashflows, discount factor, present value, and time-to-payment.
    The sum of ``pv_cashflow`` across all rows equals the bond's dirty price.

    Accepts an optional ``curve_inputs`` block; when omitted the flat 8% ZAR
    JIBAR proxy curve is used.
    """
    rid = request.request_id or str(uuid.uuid4())

    # Step 1: parse dates
    try:
        val_date = date.fromisoformat(request.valuation_date)
        issue_date = date.fromisoformat(request.issue_date)
        maturity_date = date.fromisoformat(request.maturity_date)
    except ValueError as exc:
        return _bond_cashflows_error(rid, [f"Date parse error: {exc}"])

    # Step 2: resolve day count
    resolved_day_count = _DAY_COUNT_MAP.get(request.day_count)
    if resolved_day_count is None:
        return _bond_cashflows_error(
            rid, [f"Unsupported day_count '{request.day_count}'."]
        )

    # Step 3: construct FixedRateBond
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
        return _bond_cashflows_error(rid, [f"Bond construction error: {exc}"])

    # Step 4: build discount curve
    try:
        curve, is_bootstrapped, curve_val_date = _build_bond_curve(
            request.curve_inputs,
            val_date,
            issue_date,
            maturity_date,
            request.coupon_frequency,
            resolved_day_count,
        )
    except ValueError as exc:
        return _bond_cashflows_error(rid, [str(exc)])

    # Step 5: price (for dirty_price and n_remaining_coupons)
    try:
        pricing_result = price_bond(bond, curve)
    except ValueError as exc:
        return _bond_cashflows_error(rid, [f"Pricing error: {exc}"])

    # Step 6: cashflow schedule
    try:
        rows = bond_cashflow_schedule(bond, curve)
    except ValueError as exc:
        return _bond_cashflows_error(rid, [f"Cashflow schedule error: {exc}"])

    # Step 7: serialise rows
    cashflow_rows = [
        BondCashflowRow(
            payment_date=r.payment_date.isoformat(),
            accrual_start=r.accrual_start.isoformat(),
            accrual_end=r.accrual_end.isoformat(),
            year_fraction=r.year_fraction,
            coupon_cashflow=r.coupon_cashflow,
            principal_cashflow=r.principal_cashflow,
            total_cashflow=r.total_cashflow,
            discount_factor=r.discount_factor,
            pv_cashflow=r.pv_cashflow,
            time_to_payment_years=r.time_to_payment_years,
        )
        for r in rows
    ]

    # Step 8: assumptions
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
            "pv_cashflow per row = total_cashflow × discount_factor.",
            "Sum of pv_cashflow = dirty price.",
            "Indicative only. Not suitable for production pricing or trading decisions.",
        ]
    else:
        assumptions = [
            "Flat discount curve: 8.00% (ZAR JIBAR proxy).",
            f"Bond day-count: {request.day_count}.",
            f"Coupon frequency: {request.coupon_frequency}.",
            "pv_cashflow per row = total_cashflow × discount_factor.",
            "Sum of pv_cashflow = dirty price.",
            "Indicative only. Not suitable for production pricing or trading decisions.",
        ]

    return BondCashflowResponse(
        request_id=rid,
        status="indicative",
        dirty_price=pricing_result.dirty_price,
        n_remaining_coupons=pricing_result.n_remaining_coupons,
        cashflows=cashflow_rows,
        assumptions=assumptions,
        warnings=[],
    )


# ---------------------------------------------------------------------------
# IRS cashflow schedule route
# ---------------------------------------------------------------------------

_DEFAULT_IRS_FIXED_RATE: float = 0.085


def _irs_cashflows_error(
    rid: str,
    currency: str | None,
    warnings: list[str],
) -> IRSCashflowResponse:
    """Return a graceful error IRSCashflowResponse."""
    return IRSCashflowResponse(
        request_id=rid,
        instrument_type="irs",
        currency=currency,
        status="unsupported",
        fixed_leg_pv=0.0,
        n_payments=0,
        cashflows=[],
        assumptions=["IRS cashflow schedule attempted under the quant-core engine scope."],
        warnings=warnings,
    )


@router.post("/price/irs/cashflows", response_model=IRSCashflowResponse)
def price_irs_cashflows_endpoint(request: IRSCashflowRequest) -> IRSCashflowResponse:
    """
    Return the full fixed-leg cashflow schedule for a vanilla IRS.

    Accepts the same ``extracted_fields`` dict as ``POST /price`` (i.e. the
    output of the NLP extraction step) plus an optional ``curve_inputs`` block.
    The trade must be a supported ZAR IRS JIBAR instrument.

    Each row exposes the payment date, accrual period, year fraction, fixed
    cashflow, discount factor, present value, and time-to-payment.
    The sum of ``pv_cashflow`` across all rows equals ``fixed_leg_pv`` in
    the response.
    """
    rid = request.request_id or str(uuid.uuid4())
    extracted_fields = request.extracted_fields
    currency = extracted_fields.get("currency")

    # ------------------------------------------------------------------ #
    # Step 1: validate via compute_price (guards all field checks)
    # ------------------------------------------------------------------ #
    price_result = compute_price(
        extracted_fields=extracted_fields,
        request_id=rid,
        curve_inputs=request.curve_inputs,
    )
    if price_result["status"] != "indicative":
        return _irs_cashflows_error(rid, currency, price_result["warnings"])

    # ------------------------------------------------------------------ #
    # Step 2: parse validated fields (safe to cast after status=indicative)
    # ------------------------------------------------------------------ #
    notional = float(extracted_fields["notional"])
    tenor_years = parse_tenor_years(extracted_fields["tenor"])
    frequency = str(extracted_fields["payment_frequency"]).lower()
    direction = extracted_fields["direction"]
    fixed_rate_provided = "fixed_rate" in extracted_fields
    fixed_rate = (
        float(extracted_fields["fixed_rate"])
        if fixed_rate_provided
        else _DEFAULT_IRS_FIXED_RATE
    )
    valuation_date = date.today()

    # ------------------------------------------------------------------ #
    # Step 3: build discount curve
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
        return _irs_cashflows_error(rid, currency, [f"Curve construction error: {exc}"])

    # ------------------------------------------------------------------ #
    # Step 4: construct VanillaIRS and compute cashflow schedule
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
        rows = irs_cashflow_schedule(swap, curve)
    except ValueError as exc:
        return _irs_cashflows_error(rid, currency, [f"Cashflow schedule error: {exc}"])

    # ------------------------------------------------------------------ #
    # Step 5: serialise rows
    # ------------------------------------------------------------------ #
    cashflow_rows = [
        IRSCashflowRow(
            payment_date=r.payment_date.isoformat(),
            accrual_start=r.accrual_start.isoformat(),
            accrual_end=r.accrual_end.isoformat(),
            year_fraction=r.year_fraction,
            fixed_rate=r.fixed_rate,
            notional=r.notional,
            fixed_cashflow=r.fixed_cashflow,
            discount_factor=r.discount_factor,
            pv_cashflow=r.pv_cashflow,
            time_to_payment_years=r.time_to_payment_years,
        )
        for r in rows
    ]
    n_payments = len(cashflow_rows)
    fixed_leg_pv = round(sum(r.pv_cashflow for r in rows), 2)

    # ------------------------------------------------------------------ #
    # Step 6: build assumptions
    # ------------------------------------------------------------------ #
    fixed_rate_note = (
        f"Fixed coupon rate: {fixed_rate:.4%} (provided by caller)."
        if fixed_rate_provided
        else f"Fixed coupon rate: {fixed_rate:.4%} (default assumption; not provided in prompt)."
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
            "pv_cashflow per row = fixed_cashflow \u00d7 discount_factor.",
            "Sum of pv_cashflow = fixed_leg_pv.",
            "Indicative only. Not suitable for production pricing or hedging decisions.",
            "Model scope: ZAR IRS with JIBAR floating leg, quant-core bootstrapped-curve engine.",
        ]
    else:
        assumptions = [
            f"Flat annual market rate: {_FLAT_MARKET_RATE:.4%} (ZAR JIBAR proxy).",
            fixed_rate_note,
            "pv_cashflow per row = fixed_cashflow \u00d7 discount_factor.",
            "Sum of pv_cashflow = fixed_leg_pv.",
            "Indicative only. Not suitable for production pricing or hedging decisions.",
            "Model scope: ZAR IRS with JIBAR floating leg, quant-core flat-curve engine.",
        ]

    return IRSCashflowResponse(
        request_id=rid,
        instrument_type=extracted_fields.get("instrument_type", "irs"),
        currency=currency,
        status="indicative",
        fixed_leg_pv=fixed_leg_pv,
        n_payments=n_payments,
        cashflows=cashflow_rows,
        assumptions=assumptions,
        warnings=[],
    )


# ---------------------------------------------------------------------------
# IRS valuation breakdown route
# ---------------------------------------------------------------------------


def _irs_breakdown_error(
    rid: str,
    currency: str | None,
    warnings: list[str],
) -> IRSBreakdownResponse:
    """Return a graceful error IRSBreakdownResponse."""
    return IRSBreakdownResponse(
        request_id=rid,
        instrument_type="irs",
        currency=currency,
        status="unsupported",
        fixed_leg_pv=0.0,
        floating_leg_pv=0.0,
        npv=0.0,
        n_payments=0,
        curve_source="none",
        floating_leg_method="par_floating_approximation",
        assumptions=[],
        warnings=warnings,
    )


@router.post("/price/irs/breakdown", response_model=IRSBreakdownResponse)
def price_irs_breakdown_endpoint(request: IRSBreakdownRequest) -> IRSBreakdownResponse:
    """
    Return a desk-level NPV breakdown for a vanilla IRS.

    Exposes the fixed-leg PV, floating-leg PV (par-floating approximation),
    NPV, payment count, curve source, and floating-leg method label.

    The trade must be a supported ZAR IRS JIBAR instrument.
    When ``curve_inputs`` is supplied a bootstrapped mixed discount curve
    is used; otherwise the flat 8% ZAR JIBAR proxy is used.
    """
    rid = request.request_id or str(uuid.uuid4())
    extracted_fields = request.extracted_fields
    currency = extracted_fields.get("currency")

    # ------------------------------------------------------------------ #
    # Step 1: validate via compute_price (guards all field checks)
    # ------------------------------------------------------------------ #
    price_result = compute_price(
        extracted_fields=extracted_fields,
        request_id=rid,
        curve_inputs=request.curve_inputs,
    )
    if price_result["status"] != "indicative":
        return _irs_breakdown_error(rid, currency, price_result["warnings"])

    # ------------------------------------------------------------------ #
    # Step 2: parse validated fields
    # ------------------------------------------------------------------ #
    notional = float(extracted_fields["notional"])
    tenor_years = parse_tenor_years(extracted_fields["tenor"])
    frequency = str(extracted_fields["payment_frequency"]).lower()
    direction = extracted_fields["direction"]
    fixed_rate_provided = "fixed_rate" in extracted_fields
    fixed_rate = (
        float(extracted_fields["fixed_rate"])
        if fixed_rate_provided
        else _DEFAULT_IRS_FIXED_RATE
    )
    valuation_date = date.today()

    # ------------------------------------------------------------------ #
    # Step 3: build discount curve
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
        return _irs_breakdown_error(rid, currency, [f"Curve construction error: {exc}"])

    curve_source = "bootstrapped_mixed_curve" if is_bootstrapped else "flat_fallback"

    # ------------------------------------------------------------------ #
    # Step 4: construct VanillaIRS and compute breakdown
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
        breakdown = irs_valuation_breakdown(swap, curve)
    except ValueError as exc:
        return _irs_breakdown_error(rid, currency, [f"Breakdown error: {exc}"])

    # ------------------------------------------------------------------ #
    # Step 5: build assumptions
    # ------------------------------------------------------------------ #
    fixed_rate_note = (
        f"Fixed coupon rate: {fixed_rate:.4%} (provided by caller)."
        if fixed_rate_provided
        else f"Fixed coupon rate: {fixed_rate:.4%} (default assumption; not provided in prompt)."
    )
    float_method_note = (
        "Floating leg: par-floating approximation "
        "— PV_float = notional × (df(start) − df(maturity))."
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
            float_method_note,
            "NPV sign: payer = float_pv − fixed_pv; receiver = fixed_pv − float_pv.",
            "Indicative only. Not suitable for production pricing or hedging decisions.",
            "Model scope: ZAR IRS with JIBAR floating leg, quant-core engine.",
        ]
    else:
        assumptions = [
            f"Flat annual market rate: {_FLAT_MARKET_RATE:.4%} (ZAR JIBAR proxy).",
            fixed_rate_note,
            float_method_note,
            "NPV sign: payer = float_pv − fixed_pv; receiver = fixed_pv − float_pv.",
            "Indicative only. Not suitable for production pricing or hedging decisions.",
            "Model scope: ZAR IRS with JIBAR floating leg, quant-core flat-curve engine.",
        ]

    return IRSBreakdownResponse(
        request_id=rid,
        instrument_type=extracted_fields.get("instrument_type", "irs"),
        currency=currency,
        status="indicative",
        fixed_leg_pv=round(breakdown.fixed_leg_pv, 2),
        floating_leg_pv=round(breakdown.floating_leg_pv, 2),
        npv=round(breakdown.npv, 2),
        n_payments=breakdown.n_payments,
        curve_source=curve_source,
        floating_leg_method=breakdown.floating_leg_method,
        assumptions=assumptions,
        warnings=[],
    )


# ---------------------------------------------------------------------------
# IRS fair-rate solver route
# ---------------------------------------------------------------------------


def _irs_fair_rate_error(
    rid: str,
    currency: str | None,
    warnings: list[str],
) -> IRSFairRateResponse:
    """Return a graceful error IRSFairRateResponse."""
    return IRSFairRateResponse(
        request_id=rid,
        instrument_type="irs",
        currency=currency,
        status="unsupported",
        fair_rate=0.0,
        fixed_leg_annuity=0.0,
        curve_source="none",
        assumptions=[],
        warnings=warnings,
    )


@router.post("/price/irs/fair-rate", response_model=IRSFairRateResponse)
def price_irs_fair_rate_endpoint(request: IRSFairRateRequest) -> IRSFairRateResponse:
    """
    Solve for the fair fixed rate (par swap rate) of a vanilla IRS.

    Returns the fixed rate at which the swap NPV equals zero under the
    existing pricing model and the supplied (or default) discount curve.

    The trade must be a supported ZAR IRS JIBAR instrument.
    When ``curve_inputs`` is supplied a bootstrapped mixed discount curve
    is used; otherwise the flat 8% ZAR JIBAR proxy is used.
    """
    rid = request.request_id or str(uuid.uuid4())
    extracted_fields = request.extracted_fields
    currency = extracted_fields.get("currency")

    # ------------------------------------------------------------------ #
    # Step 1: validate via compute_price (guards all field checks)
    # ------------------------------------------------------------------ #
    price_result = compute_price(
        extracted_fields=extracted_fields,
        request_id=rid,
        curve_inputs=request.curve_inputs,
    )
    if price_result["status"] != "indicative":
        return _irs_fair_rate_error(rid, currency, price_result["warnings"])

    # ------------------------------------------------------------------ #
    # Step 2: parse validated fields
    # ------------------------------------------------------------------ #
    notional = float(extracted_fields["notional"])
    tenor_years = parse_tenor_years(extracted_fields["tenor"])
    frequency = str(extracted_fields["payment_frequency"]).lower()
    direction = extracted_fields["direction"]
    valuation_date = date.today()

    # ------------------------------------------------------------------ #
    # Step 3: build discount curve
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
        return _irs_fair_rate_error(rid, currency, [f"Curve construction error: {exc}"])

    curve_source = "bootstrapped_mixed_curve" if is_bootstrapped else "flat_fallback"

    # ------------------------------------------------------------------ #
    # Step 4: construct VanillaIRS and solve for fair rate
    # The fixed_rate here is only a placeholder — solve_irs_fair_rate
    # ignores it and uses the schedule + curve only.
    # ------------------------------------------------------------------ #
    try:
        swap = VanillaIRS(
            valuation_date=curve_val_date,
            start_date=curve_val_date,
            tenor_years=tenor_years,  # type: ignore[arg-type]
            notional=notional,
            fixed_rate=_DEFAULT_IRS_FIXED_RATE,  # placeholder; overridden by solver
            payment_frequency=frequency,
            day_count=resolved_day_count,
            pay_receive=direction,
        )
        fair = solve_irs_fair_rate(swap, curve)
        annuity = fixed_leg_annuity(swap, curve)
    except ValueError as exc:
        return _irs_fair_rate_error(rid, currency, [f"Fair-rate solver error: {exc}"])

    # ------------------------------------------------------------------ #
    # Step 5: build assumptions
    # ------------------------------------------------------------------ #
    float_method_note = (
        "Floating leg: par-floating approximation "
        "— PV_float = notional × (df(start) − df(maturity))."
    )
    fair_rate_note = (
        "Fair rate solved algebraically: "
        "fair_rate = PV_float / (notional × fixed_leg_annuity)."
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
            float_method_note,
            fair_rate_note,
            "Indicative only. Not suitable for production pricing or hedging decisions.",
            "Model scope: ZAR IRS with JIBAR floating leg, quant-core bootstrapped-curve engine.",
        ]
    else:
        assumptions = [
            f"Flat annual market rate: {_FLAT_MARKET_RATE:.4%} (ZAR JIBAR proxy).",
            float_method_note,
            fair_rate_note,
            "Indicative only. Not suitable for production pricing or hedging decisions.",
            "Model scope: ZAR IRS with JIBAR floating leg, quant-core flat-curve engine.",
        ]

    return IRSFairRateResponse(
        request_id=rid,
        instrument_type=extracted_fields.get("instrument_type", "irs"),
        currency=currency,
        status="indicative",
        fair_rate=round(fair, 8),
        fixed_leg_annuity=round(annuity, 8),
        curve_source=curve_source,
        assumptions=assumptions,
        warnings=[],
    )


# ---------------------------------------------------------------------------
# IRS direct pricing route (structured, no NLP extraction)
# ---------------------------------------------------------------------------


def _irs_direct_error(
    rid: str,
    currency: str | None,
    warnings: list[str],
) -> IRSDirectPriceResponse:
    """Return a graceful error IRSDirectPriceResponse."""
    return IRSDirectPriceResponse(
        request_id=rid,
        instrument_type="irs",
        currency=currency,
        status="error",
        price=0.0,
        pv01=0.0,
        curve_source="none",
        assumptions=[],
        warnings=warnings,
    )


@router.post("/price/irs", response_model=IRSDirectPriceResponse)
def price_irs_direct_endpoint(request: IRSDirectPriceRequest) -> IRSDirectPriceResponse:
    """
    Price a vanilla ZAR JIBAR IRS from a fully-structured request.

    Unlike ``POST /price`` (which accepts untyped ``extracted_fields`` from
    the NLP extraction step), this endpoint receives explicit typed fields
    and validates them at the Pydantic schema level.  All other pricing logic
    is identical: the same quant-core engine, the same flat/bootstrapped curve
    paths, and the same ``price_irs`` function.

    When ``curve_inputs`` is supplied a bootstrapped mixed discount curve is
    used; otherwise the flat 8% ZAR JIBAR proxy is used.

    ``fixed_rate`` is optional; when omitted the default 8.5% coupon is used
    as a placeholder (visible in assumptions).
    """
    rid = request.request_id or str(uuid.uuid4())

    # ------------------------------------------------------------------ #
    # Step 1: parse fields (all validated by Pydantic schema already)
    # ------------------------------------------------------------------ #
    notional = request.notional
    tenor_years = parse_tenor_years(request.tenor)  # safe — schema validates pattern
    frequency = request.payment_frequency
    direction = request.direction
    fixed_rate_provided = request.fixed_rate is not None
    fixed_rate = request.fixed_rate if fixed_rate_provided else _DEFAULT_IRS_FIXED_RATE
    valuation_date = date.today()

    # ------------------------------------------------------------------ #
    # Step 2: build discount curve
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
        return _irs_direct_error(rid, request.currency, [f"Curve construction error: {exc}"])

    curve_source = "bootstrapped_mixed_curve" if is_bootstrapped else "flat_fallback"

    # ------------------------------------------------------------------ #
    # Step 3: construct VanillaIRS and price
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
        result = price_irs(swap, curve)
    except ValueError as exc:
        return _irs_direct_error(rid, request.currency, [f"Pricing error: {exc}"])

    # ------------------------------------------------------------------ #
    # Step 4: build assumptions (consistent with the existing /price path)
    # ------------------------------------------------------------------ #
    fixed_rate_note = (
        f"Fixed coupon rate: {fixed_rate:.4%} (provided by caller)."
        if fixed_rate_provided
        else f"Fixed coupon rate: {fixed_rate:.4%} (default assumption; not provided)."
    )
    float_method_note = (
        "Floating leg: par-floating approximation "
        "\u2014 PV_float = notional \u00d7 (df(start) \u2212 df(maturity))."
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
            float_method_note,
            "NPV sign: payer = float_pv \u2212 fixed_pv; receiver = fixed_pv \u2212 float_pv.",
            "PV01: parallel +1bp shift of all continuously-compounded zero rates.",
            "Indicative only. Not suitable for production pricing or hedging decisions.",
            "Model scope: ZAR IRS with JIBAR floating leg, quant-core bootstrapped-curve engine.",
        ]
    else:
        assumptions = [
            f"Flat annual market rate: {_FLAT_MARKET_RATE:.4%} (ZAR JIBAR proxy).",
            fixed_rate_note,
            float_method_note,
            "NPV sign: payer = float_pv \u2212 fixed_pv; receiver = fixed_pv \u2212 float_pv.",
            "PV01: parallel +1bp shift of all continuously-compounded zero rates.",
            "Indicative only. Not suitable for production pricing or hedging decisions.",
            "Model scope: ZAR IRS with JIBAR floating leg, quant-core flat-curve engine.",
        ]

    return IRSDirectPriceResponse(
        request_id=rid,
        instrument_type="irs",
        currency=request.currency,
        status="indicative",
        price=round(result.npv, 2),
        pv01=round(result.pv01, 2),
        curve_source=curve_source,
        assumptions=assumptions,
        warnings=[],
    )


# ---------------------------------------------------------------------------
# IRS direct cashflow schedule route (structured, no NLP extraction)
# ---------------------------------------------------------------------------


def _irs_direct_cashflows_error(
    rid: str,
    currency: str | None,
    warnings: list[str],
) -> IRSDirectCashflowResponse:
    """Return a graceful error IRSDirectCashflowResponse."""
    return IRSDirectCashflowResponse(
        request_id=rid,
        instrument_type="irs",
        currency=currency,
        status="error",
        fixed_leg_pv=0.0,
        n_payments=0,
        cashflows=[],
        curve_source="none",
        assumptions=[],
        warnings=warnings,
    )


@router.post("/price/irs/cashflows/direct", response_model=IRSDirectCashflowResponse)
def price_irs_cashflows_direct_endpoint(
    request: IRSDirectCashflowRequest,
) -> IRSDirectCashflowResponse:
    """
    Return the fixed-leg cashflow schedule for a vanilla IRS from a
    fully-structured request.

    Unlike ``POST /price/irs/cashflows`` (which accepts an untyped
    ``extracted_fields`` dict from the NLP extraction step), this endpoint
    receives explicit typed fields validated at the Pydantic schema level.
    All other cashflow logic is identical: the same quant-core
    ``irs_cashflow_schedule`` function, the same flat/bootstrapped curve
    paths, and the same serialisation as the existing cashflow endpoint.

    The response includes ``curve_source`` (``flat_fallback`` or
    ``bootstrapped_mixed_curve``) to make the curve path transparent.
    """
    rid = request.request_id or str(uuid.uuid4())

    # ------------------------------------------------------------------ #
    # Step 1: parse fields (all validated by Pydantic schema already)
    # ------------------------------------------------------------------ #
    notional = request.notional
    tenor_years = parse_tenor_years(request.tenor)  # safe — schema validates pattern
    frequency = request.payment_frequency
    direction = request.direction
    fixed_rate_provided = request.fixed_rate is not None
    fixed_rate = request.fixed_rate if fixed_rate_provided else _DEFAULT_IRS_FIXED_RATE
    valuation_date = date.today()

    # ------------------------------------------------------------------ #
    # Step 2: build discount curve
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
        return _irs_direct_cashflows_error(
            rid, request.currency, [f"Curve construction error: {exc}"]
        )

    curve_source = "bootstrapped_mixed_curve" if is_bootstrapped else "flat_fallback"

    # ------------------------------------------------------------------ #
    # Step 3: construct VanillaIRS and compute cashflow schedule
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
        rows = irs_cashflow_schedule(swap, curve)
    except ValueError as exc:
        return _irs_direct_cashflows_error(
            rid, request.currency, [f"Cashflow schedule error: {exc}"]
        )

    # ------------------------------------------------------------------ #
    # Step 4: serialise rows
    # ------------------------------------------------------------------ #
    cashflow_rows = [
        IRSCashflowRow(
            payment_date=r.payment_date.isoformat(),
            accrual_start=r.accrual_start.isoformat(),
            accrual_end=r.accrual_end.isoformat(),
            year_fraction=r.year_fraction,
            fixed_rate=r.fixed_rate,
            notional=r.notional,
            fixed_cashflow=r.fixed_cashflow,
            discount_factor=r.discount_factor,
            pv_cashflow=r.pv_cashflow,
            time_to_payment_years=r.time_to_payment_years,
        )
        for r in rows
    ]
    n_payments = len(cashflow_rows)
    fixed_leg_pv = round(sum(r.pv_cashflow for r in rows), 2)

    # ------------------------------------------------------------------ #
    # Step 5: build assumptions (consistent with existing cashflow path)
    # ------------------------------------------------------------------ #
    fixed_rate_note = (
        f"Fixed coupon rate: {fixed_rate:.4%} (provided by caller)."
        if fixed_rate_provided
        else f"Fixed coupon rate: {fixed_rate:.4%} (default assumption; not provided)."
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
            "pv_cashflow per row = fixed_cashflow \u00d7 discount_factor.",
            "Sum of pv_cashflow = fixed_leg_pv.",
            "Indicative only. Not suitable for production pricing or hedging decisions.",
            "Model scope: ZAR IRS with JIBAR floating leg, quant-core bootstrapped-curve engine.",
        ]
    else:
        assumptions = [
            f"Flat annual market rate: {_FLAT_MARKET_RATE:.4%} (ZAR JIBAR proxy).",
            fixed_rate_note,
            "pv_cashflow per row = fixed_cashflow \u00d7 discount_factor.",
            "Sum of pv_cashflow = fixed_leg_pv.",
            "Indicative only. Not suitable for production pricing or hedging decisions.",
            "Model scope: ZAR IRS with JIBAR floating leg, quant-core flat-curve engine.",
        ]

    return IRSDirectCashflowResponse(
        request_id=rid,
        instrument_type="irs",
        currency=request.currency,
        status="indicative",
        fixed_leg_pv=fixed_leg_pv,
        n_payments=n_payments,
        cashflows=cashflow_rows,
        curve_source=curve_source,
        assumptions=assumptions,
        warnings=[],
    )


# ---------------------------------------------------------------------------
# IRS direct breakdown route (structured, no NLP extraction)
# ---------------------------------------------------------------------------


def _irs_direct_breakdown_error(
    rid: str,
    currency: str | None,
    warnings: list[str],
) -> IRSDirectBreakdownResponse:
    """Return a graceful error IRSDirectBreakdownResponse."""
    return IRSDirectBreakdownResponse(
        request_id=rid,
        instrument_type="irs",
        currency=currency,
        status="error",
        fixed_leg_pv=0.0,
        floating_leg_pv=0.0,
        npv=0.0,
        n_payments=0,
        curve_source="none",
        floating_leg_method="par_floating_approximation",
        assumptions=[],
        warnings=warnings,
    )


@router.post("/price/irs/breakdown/direct", response_model=IRSDirectBreakdownResponse)
def price_irs_breakdown_direct_endpoint(
    request: IRSDirectBreakdownRequest,
) -> IRSDirectBreakdownResponse:
    """
    Return a desk-level NPV breakdown for a vanilla IRS from a
    fully-structured request.

    Unlike ``POST /price/irs/breakdown`` (which accepts an untyped
    ``extracted_fields`` dict from the NLP extraction step), this endpoint
    receives explicit typed fields validated at the Pydantic schema level.
    All other breakdown logic is identical: the same quant-core
    ``irs_valuation_breakdown`` function, the same flat/bootstrapped curve
    paths, and the same assumptions as the existing breakdown endpoint.

    The response includes ``curve_source`` to make the curve path transparent.
    """
    rid = request.request_id or str(uuid.uuid4())

    # ------------------------------------------------------------------ #
    # Step 1: parse fields (all validated by Pydantic schema already)
    # ------------------------------------------------------------------ #
    notional = request.notional
    tenor_years = parse_tenor_years(request.tenor)  # safe — schema validates pattern
    frequency = request.payment_frequency
    direction = request.direction
    fixed_rate_provided = request.fixed_rate is not None
    fixed_rate = request.fixed_rate if fixed_rate_provided else _DEFAULT_IRS_FIXED_RATE
    valuation_date = date.today()

    # ------------------------------------------------------------------ #
    # Step 2: build discount curve
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
        return _irs_direct_breakdown_error(
            rid, request.currency, [f"Curve construction error: {exc}"]
        )

    curve_source = "bootstrapped_mixed_curve" if is_bootstrapped else "flat_fallback"

    # ------------------------------------------------------------------ #
    # Step 3: construct VanillaIRS and compute breakdown
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
        breakdown = irs_valuation_breakdown(swap, curve)
    except ValueError as exc:
        return _irs_direct_breakdown_error(
            rid, request.currency, [f"Breakdown error: {exc}"]
        )

    # ------------------------------------------------------------------ #
    # Step 4: build assumptions (consistent with existing breakdown path)
    # ------------------------------------------------------------------ #
    fixed_rate_note = (
        f"Fixed coupon rate: {fixed_rate:.4%} (provided by caller)."
        if fixed_rate_provided
        else f"Fixed coupon rate: {fixed_rate:.4%} (default assumption; not provided)."
    )
    float_method_note = (
        "Floating leg: par-floating approximation "
        "\u2014 PV_float = notional \u00d7 (df(start) \u2212 df(maturity))."
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
            float_method_note,
            "NPV sign: payer = float_pv \u2212 fixed_pv; receiver = fixed_pv \u2212 float_pv.",
            "Indicative only. Not suitable for production pricing or hedging decisions.",
            "Model scope: ZAR IRS with JIBAR floating leg, quant-core engine.",
        ]
    else:
        assumptions = [
            f"Flat annual market rate: {_FLAT_MARKET_RATE:.4%} (ZAR JIBAR proxy).",
            fixed_rate_note,
            float_method_note,
            "NPV sign: payer = float_pv \u2212 fixed_pv; receiver = fixed_pv \u2212 float_pv.",
            "Indicative only. Not suitable for production pricing or hedging decisions.",
            "Model scope: ZAR IRS with JIBAR floating leg, quant-core flat-curve engine.",
        ]

    return IRSDirectBreakdownResponse(
        request_id=rid,
        instrument_type="irs",
        currency=request.currency,
        status="indicative",
        fixed_leg_pv=round(breakdown.fixed_leg_pv, 2),
        floating_leg_pv=round(breakdown.floating_leg_pv, 2),
        npv=round(breakdown.npv, 2),
        n_payments=breakdown.n_payments,
        curve_source=curve_source,
        floating_leg_method=breakdown.floating_leg_method,
        assumptions=assumptions,
        warnings=[],
    )


# ---------------------------------------------------------------------------
# IRS direct fair-rate route (structured, no NLP extraction)
# ---------------------------------------------------------------------------


def _irs_direct_fair_rate_error(
    rid: str,
    currency: str | None,
    warnings: list[str],
) -> IRSDirectFairRateResponse:
    """Return a graceful error IRSDirectFairRateResponse."""
    return IRSDirectFairRateResponse(
        request_id=rid,
        instrument_type="irs",
        currency=currency,
        status="error",
        fair_rate=0.0,
        fixed_leg_annuity=0.0,
        curve_source="none",
        assumptions=[],
        warnings=warnings,
    )


@router.post("/price/irs/fair-rate/direct", response_model=IRSDirectFairRateResponse)
def price_irs_fair_rate_direct_endpoint(
    request: IRSDirectFairRateRequest,
) -> IRSDirectFairRateResponse:
    """
    Solve for the fair fixed rate (par swap rate) of a vanilla IRS from a
    fully-structured request.

    Unlike ``POST /price/irs/fair-rate`` (which accepts an untyped
    ``extracted_fields`` dict from the NLP extraction step), this endpoint
    receives explicit typed fields validated at the Pydantic schema level.
    All other fair-rate logic is identical: the same quant-core
    ``solve_irs_fair_rate`` and ``fixed_leg_annuity`` functions, the same
    flat/bootstrapped curve paths, and the same assumptions as the existing
    fair-rate endpoint.

    ``fixed_rate`` in the request, if supplied, is accepted but **ignored**
    during solving — a warning is added to the response when this happens.

    The response includes ``curve_source`` to make the curve path transparent.
    """
    rid = request.request_id or str(uuid.uuid4())

    # ------------------------------------------------------------------ #
    # Step 1: parse fields (all validated by Pydantic schema already)
    # ------------------------------------------------------------------ #
    notional = request.notional
    tenor_years = parse_tenor_years(request.tenor)  # safe — schema validates pattern
    frequency = request.payment_frequency
    direction = request.direction
    fixed_rate_provided = request.fixed_rate is not None
    valuation_date = date.today()

    # ------------------------------------------------------------------ #
    # Step 2: build discount curve
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
        return _irs_direct_fair_rate_error(
            rid, request.currency, [f"Curve construction error: {exc}"]
        )

    curve_source = "bootstrapped_mixed_curve" if is_bootstrapped else "flat_fallback"

    # ------------------------------------------------------------------ #
    # Step 3: construct VanillaIRS and solve for fair rate
    # fixed_rate is a placeholder here — solve_irs_fair_rate ignores it.
    # ------------------------------------------------------------------ #
    try:
        swap = VanillaIRS(
            valuation_date=curve_val_date,
            start_date=curve_val_date,
            tenor_years=tenor_years,  # type: ignore[arg-type]
            notional=notional,
            fixed_rate=_DEFAULT_IRS_FIXED_RATE,  # placeholder; overridden by solver
            payment_frequency=frequency,
            day_count=resolved_day_count,
            pay_receive=direction,
        )
        fair = solve_irs_fair_rate(swap, curve)
        annuity = fixed_leg_annuity(swap, curve)
    except ValueError as exc:
        return _irs_direct_fair_rate_error(
            rid, request.currency, [f"Fair-rate solver error: {exc}"]
        )

    # ------------------------------------------------------------------ #
    # Step 4: build assumptions (consistent with existing fair-rate path)
    # ------------------------------------------------------------------ #
    float_method_note = (
        "Floating leg: par-floating approximation "
        "\u2014 PV_float = notional \u00d7 (df(start) \u2212 df(maturity))."
    )
    fair_rate_note = (
        "Fair rate solved algebraically: "
        "fair_rate = PV_float / (notional \u00d7 fixed_leg_annuity)."
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
            float_method_note,
            fair_rate_note,
            "Indicative only. Not suitable for production pricing or hedging decisions.",
            "Model scope: ZAR IRS with JIBAR floating leg, quant-core bootstrapped-curve engine.",
        ]
    else:
        assumptions = [
            f"Flat annual market rate: {_FLAT_MARKET_RATE:.4%} (ZAR JIBAR proxy).",
            float_method_note,
            fair_rate_note,
            "Indicative only. Not suitable for production pricing or hedging decisions.",
            "Model scope: ZAR IRS with JIBAR floating leg, quant-core flat-curve engine.",
        ]

    # Warn if the caller supplied fixed_rate (it was not used)
    extra_warnings: list[str] = []
    if fixed_rate_provided:
        extra_warnings.append(
            f"fixed_rate={request.fixed_rate:.4%} was supplied but ignored; "
            "fair-rate solving is independent of any pre-specified fixed coupon."
        )

    return IRSDirectFairRateResponse(
        request_id=rid,
        instrument_type="irs",
        currency=request.currency,
        status="indicative",
        fair_rate=round(fair, 8),
        fixed_leg_annuity=round(annuity, 8),
        curve_source=curve_source,
        assumptions=assumptions,
        warnings=extra_warnings,
    )

