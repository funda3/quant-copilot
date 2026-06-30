from __future__ import annotations

import re
import uuid
from datetime import date
from typing import TYPE_CHECKING, Optional

from quant_core.conventions.day_count import DayCount
from quant_core.curves.bootstrap_mixed import (
    bootstrap_discount_curve_from_market_records,
)
from quant_core.curves.build_flat import flat_curve
from quant_core.curves.discount_curve import DiscountCurve
from quant_core.instruments.irs import VanillaIRS
from quant_core.marketdata.normalize_rates import normalize_market_quotes
from quant_core.pricing.irs_pricer import price_irs
from quant_core.schemas.market_inputs import DepositQuote, FRAQuote, ParSwapQuote

if TYPE_CHECKING:
    from app.schemas.price import CurveInputs

# ---------------------------------------------------------------------------
# Pricing constants — narrow supported case (ZAR JIBAR flat curve)
# ---------------------------------------------------------------------------
_FLAT_MARKET_RATE: float = 0.08   # 8% flat ZAR JIBAR proxy
_DEFAULT_FIXED_RATE: float = 0.085  # 8.5% default fixed coupon
_FLAT_CURVE_DAY_COUNT: DayCount = DayCount.ACT_365F

_SUPPORTED_CURRENCIES: frozenset[str] = frozenset({"ZAR"})
_SUPPORTED_INSTRUMENTS: frozenset[str] = frozenset({"irs"})
_SUPPORTED_INDICES: frozenset[str] = frozenset({"JIBAR"})
_SUPPORTED_DIRECTIONS: frozenset[str] = frozenset({"payer", "receiver"})
_SUPPORTED_FREQUENCIES: frozenset[str] = frozenset({"quarterly", "semiannual", "annual"})

# Validation bounds
_FIXED_RATE_MIN_EXCLUSIVE: float = 0.0
_FIXED_RATE_MAX_EXCLUSIVE: float = 1.0
_NOTIONAL_MIN_INCLUSIVE: int = 1_000
_NOTIONAL_MAX_INCLUSIVE: int = 100_000_000_000
_TENOR_MIN_YEARS_INCLUSIVE: int = 1
_TENOR_MAX_YEARS_INCLUSIVE: int = 50

# ---------------------------------------------------------------------------
# Bootstrap-path constants — day-count map and supported frequencies
# ---------------------------------------------------------------------------

_DAY_COUNT_MAP: dict[str, DayCount] = {
    "ACT_365F": DayCount.ACT_365F,
    "ACT_360": DayCount.ACT_360,
    "30_360": DayCount.THIRTY_360,
    "ACT_ACT_ISDA": DayCount.ACT_ACT_ISDA,
}

_BOOTSTRAP_SUPPORTED_FREQUENCIES: frozenset[str] = frozenset(
    {"annual", "semiannual", "quarterly", "monthly"}
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_tenor_years(tenor: str) -> int | None:
    """Parse a tenor string like '5Y' or '10Y' into integer years.

    Returns None for '0Y' and any non-positive value.
    """
    match = re.match(r"^(\d+)[Yy]$", str(tenor).strip())
    if match:
        years = int(match.group(1))
        return years if years > 0 else None
    return None


def _build_curve(
    curve_inputs: Optional["CurveInputs"],
    default_valuation_date: date,
    flat_tenor_years: int,
    flat_frequency: str,
    flat_day_count: DayCount,
) -> tuple[DiscountCurve, bool, date, DayCount]:
    """
    Build a discount curve for IRS pricing.

    Returns ``(curve, is_bootstrapped, effective_valuation_date, resolved_day_count)``.

    * ``is_bootstrapped=False`` — flat ACT/365F proxy curve (ZAR JIBAR 8%).
      ``resolved_day_count`` equals ``flat_day_count``.
    * ``is_bootstrapped=True``  — mixed deposit/FRA/swap bootstrapped curve.
      ``resolved_day_count`` is the ``DayCount`` resolved from
      ``curve_inputs.day_count``; callers **must** pass this same value to
      ``VanillaIRS`` so that fixed-leg accrual fractions are consistent with
      the curve.

    Raises :exc:`ValueError` with a clear message on any construction
    failure so that callers can surface the reason in a pricing warning.
    """
    if curve_inputs is None:
        return (
            flat_curve(
                default_valuation_date,
                _FLAT_MARKET_RATE,
                flat_tenor_years,
                flat_frequency,
                flat_day_count,
            ),
            False,
            default_valuation_date,
            flat_day_count,
        )

    # --- Bootstrapped path ---
    # payment_frequency and day_count are already validated by the Pydantic
    # schema; these checks are a defensive fallback for non-HTTP call sites.
    ci_freq = str(curve_inputs.payment_frequency).lower()
    if ci_freq not in _BOOTSTRAP_SUPPORTED_FREQUENCIES:
        raise ValueError(
            f"curve_inputs.payment_frequency '{curve_inputs.payment_frequency}' "
            f"is not supported. Supported values: {sorted(_BOOTSTRAP_SUPPORTED_FREQUENCIES)}."
        )

    ci_day_count = _DAY_COUNT_MAP.get(curve_inputs.day_count)
    if ci_day_count is None:
        raise ValueError(
            f"curve_inputs.day_count '{curve_inputs.day_count}' is not supported. "
            f"Supported values: {sorted(_DAY_COUNT_MAP.keys())}."
        )

    if not (
        bool(curve_inputs.deposits)
        or bool(curve_inputs.fras)
        or bool(curve_inputs.swaps)
    ):
        raise ValueError(
            "curve_inputs must contain at least one non-empty instrument list "
            "(deposits, fras, or swaps)."
        )

    if curve_inputs.valuation_date is not None:
        try:
            ci_val_date = date.fromisoformat(curve_inputs.valuation_date)
        except ValueError as exc:
            raise ValueError(f"curve_inputs.valuation_date: {exc}") from exc
    else:
        ci_val_date = default_valuation_date

    deposit_quotes = [
        DepositQuote(tenor_months=d.tenor_months, rate=d.rate)
        for d in (curve_inputs.deposits or [])
    ]
    fra_quotes = [
        FRAQuote(start_months=f.start_months, end_months=f.end_months, rate=f.rate)
        for f in (curve_inputs.fras or [])
    ]
    swap_quotes_qc = [
        ParSwapQuote(tenor_years=s.tenor_years, par_rate=s.par_rate)
        for s in (curve_inputs.swaps or [])
    ]

    records = normalize_market_quotes(
        deposits=deposit_quotes,
        fras=fra_quotes,
        swaps=swap_quotes_qc,
    )

    curve = bootstrap_discount_curve_from_market_records(
        valuation_date=ci_val_date,
        records=records,
        payment_frequency=ci_freq,
        day_count=ci_day_count,
    )

    return curve, True, ci_val_date, ci_day_count


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _check_supported(fields: dict) -> list[str]:
    """Return a list of reasons the request is unsupported; empty = supported."""
    reasons: list[str] = []

    if fields.get("instrument_type") not in _SUPPORTED_INSTRUMENTS:
        reasons.append(
            f"Unsupported instrument_type '{fields.get('instrument_type')}'. "
            "Only 'irs' is currently supported."
        )
    if fields.get("currency") not in _SUPPORTED_CURRENCIES:
        reasons.append(
            f"Unsupported currency '{fields.get('currency')}'. "
            "Only 'ZAR' is currently supported."
        )
    if fields.get("floating_index") not in _SUPPORTED_INDICES:
        reasons.append(
            f"Unsupported floating_index '{fields.get('floating_index')}'. "
            "Only 'JIBAR' is currently supported."
        )
    freq = str(fields.get("payment_frequency", "") or "").lower()
    if freq not in _SUPPORTED_FREQUENCIES:
        reasons.append(
            f"Unsupported payment_frequency '{fields.get('payment_frequency')}'. "
            "Supported values: quarterly, semiannual, annual."
        )
    _tenor_years = parse_tenor_years(fields.get("tenor", "") or "")
    if _tenor_years is None:
        reasons.append(
            f"Cannot parse tenor '{fields.get('tenor')}'. "
            "Expected format: '5Y', '10Y', etc."
        )
    elif _tenor_years < _TENOR_MIN_YEARS_INCLUSIVE:
        reasons.append(
            f"tenor '{fields.get('tenor')}' ({_tenor_years}Y) is below the minimum "
            f"supported tenor of {_TENOR_MIN_YEARS_INCLUSIVE} years."
        )
    elif _tenor_years > _TENOR_MAX_YEARS_INCLUSIVE:
        reasons.append(
            f"tenor '{fields.get('tenor')}' ({_tenor_years}Y) exceeds the maximum "
            f"supported tenor of {_TENOR_MAX_YEARS_INCLUSIVE} years."
        )
    if fields.get("direction") not in _SUPPORTED_DIRECTIONS:
        reasons.append(
            f"Unsupported direction '{fields.get('direction')}'. "
            "Expected 'payer' or 'receiver'."
        )
    try:
        notional = float(fields.get("notional") or 0)
        if notional <= 0:
            reasons.append("notional must be a positive number.")
        elif notional < _NOTIONAL_MIN_INCLUSIVE:
            reasons.append(
                f"notional {notional:,.0f} is implausibly small. "
                f"Expected at least {_NOTIONAL_MIN_INCLUSIVE:,} in the trade currency."
            )
        elif notional > _NOTIONAL_MAX_INCLUSIVE:
            reasons.append(
                f"notional {notional:,.0f} exceeds the maximum supported value "
                f"of {_NOTIONAL_MAX_INCLUSIVE:,} ({_NOTIONAL_MAX_INCLUSIVE // 1_000_000_000} billion)."
            )
    except (TypeError, ValueError):
        reasons.append(f"Invalid notional '{fields.get('notional')}'.")

    if "fixed_rate" in fields:
        try:
            fr = float(fields["fixed_rate"])
            if not (_FIXED_RATE_MIN_EXCLUSIVE < fr < _FIXED_RATE_MAX_EXCLUSIVE):
                reasons.append(
                    f"fixed_rate {fr:.6g} is out of range. "
                    f"Expected a decimal between {_FIXED_RATE_MIN_EXCLUSIVE} (exclusive) "
                    f"and {_FIXED_RATE_MAX_EXCLUSIVE} (exclusive), "
                    "e.g. 0.085 for 8.5%."
                )
        except (TypeError, ValueError):
            pass  # non-numeric fixed_rate is caught later in compute_price

    return reasons


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def compute_price(
    extracted_fields: dict,
    request_id: str | None = None,
    curve_inputs: Optional["CurveInputs"] = None,
) -> dict:
    """
    Compute an indicative IRS price for the supported narrow case.

    Delegates all pricing math to quant_core.pricing.irs_pricer.  The
    discount curve is either:

    * **flat-curve fallback** (``curve_inputs=None``) — an 8% flat ZAR
      JIBAR proxy built by ``quant_core.curves.build_flat.flat_curve``.
    * **bootstrapped curve** (``curve_inputs`` supplied) — a mixed
      deposit/FRA/swap curve built by
      ``quant_core.curves.bootstrap_mixed.bootstrap_discount_curve_from_market_records``.

    Returns status='indicative' for supported ZAR IRS JIBAR trades.
    Returns status='unsupported' for anything else — never raises.
    """
    rid = request_id if request_id else str(uuid.uuid4())
    reasons = _check_supported(extracted_fields)

    if reasons:
        return {
            "request_id": rid,
            "instrument_type": extracted_fields.get("instrument_type"),
            "currency": extracted_fields.get("currency"),
            "price": 0.0,
            "pv01": 0.0,
            "status": "unsupported",
            "assumptions": ["Pricing attempted under the ZAR IRS quant-core engine scope."],
            "warnings": reasons,
        }

    # All fields validated — safe to cast
    notional = float(extracted_fields["notional"])
    tenor_years = parse_tenor_years(extracted_fields["tenor"])  # type: ignore[arg-type]
    frequency = str(extracted_fields["payment_frequency"]).lower()
    direction = extracted_fields["direction"]

    fixed_rate_provided = "fixed_rate" in extracted_fields
    if fixed_rate_provided:
        try:
            fixed_rate = float(extracted_fields["fixed_rate"])
        except (TypeError, ValueError):
            return {
                "request_id": rid,
                "instrument_type": extracted_fields.get("instrument_type"),
                "currency": extracted_fields.get("currency"),
                "price": 0.0,
                "pv01": 0.0,
                "status": "unsupported",
                "assumptions": ["Pricing attempted under the ZAR IRS quant-core engine scope."],
                "warnings": [
                    f"Invalid fixed_rate '{extracted_fields['fixed_rate']}'. "
                    "Expected a numeric value (e.g. 0.085 for 8.5%)."
                ],
            }
    else:
        fixed_rate = _DEFAULT_FIXED_RATE

    valuation_date = date.today()  # NOTE: date.today() fallback — tests must not assert exact NPV values against this path

    try:
        curve, is_bootstrapped, curve_val_date, resolved_day_count = _build_curve(
            curve_inputs,
            valuation_date,
            tenor_years,  # type: ignore[arg-type]
            frequency,
            _FLAT_CURVE_DAY_COUNT,
        )
    except ValueError as exc:
        return {
            "request_id": rid,
            "instrument_type": extracted_fields.get("instrument_type"),
            "currency": extracted_fields.get("currency"),
            "price": 0.0,
            "pv01": 0.0,
            "status": "unsupported",
            "assumptions": ["Pricing attempted under the ZAR IRS quant-core engine scope."],
            "warnings": [f"Curve construction error: {exc}"],
        }

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
        return {
            "request_id": rid,
            "instrument_type": extracted_fields.get("instrument_type"),
            "currency": extracted_fields.get("currency"),
            "price": 0.0,
            "pv01": 0.0,
            "status": "unsupported",
            "assumptions": ["Pricing attempted under the ZAR IRS quant-core engine scope."],
            "warnings": [f"Pricing engine error: {exc}"],
        }

    fixed_rate_note = (
        f"Fixed coupon rate: {fixed_rate:.4%} (provided by caller)."
        if fixed_rate_provided
        else f"Fixed coupon rate: {fixed_rate:.4%} (default assumption; not provided in prompt)."
    )

    if is_bootstrapped:
        n_dep = len(curve_inputs.deposits or [])  # type: ignore[union-attr]
        n_fra = len(curve_inputs.fras or [])  # type: ignore[union-attr]
        n_swp = len(curve_inputs.swaps or [])  # type: ignore[union-attr]
        assumptions = [
            f"Bootstrapped mixed curve: {n_dep} deposit(s), {n_fra} FRA(s), {n_swp} swap(s).",
            (
                f"Curve: valuation date {curve_val_date.isoformat()}, "
                f"{curve_inputs.payment_frequency} coupons, "  # type: ignore[union-attr]
                f"{curve_inputs.day_count}."  # type: ignore[union-attr]
            ),
            fixed_rate_note,
            "Par-floating approximation: floating leg PV = notional \u00d7 (1 \u2212 df_end).",
            "Discount factors from bootstrapped mixed deposit/FRA/swap curve (quant-core engine).",
            "PV01: parallel +1bp shift of all continuously-compounded zero rates.",
            "Indicative only. Not suitable for production pricing or hedging decisions.",
            "Model scope: ZAR IRS with JIBAR floating leg, quant-core bootstrapped-curve engine.",
        ]
    else:
        assumptions = [
            f"Flat annual market rate: {_FLAT_MARKET_RATE:.4%} (ZAR JIBAR proxy).",
            fixed_rate_note,
            "Par-floating approximation: floating leg PV = notional \u00d7 (1 \u2212 df_end).",
            "Discount factors from flat simple-rate curve (ACT/365F).",
            "PV01: parallel +1bp shift of all continuously-compounded zero rates.",
            "Indicative only. Not suitable for production pricing or hedging decisions.",
            "Model scope: ZAR IRS with JIBAR floating leg, quant-core flat-curve engine.",
        ]

    return {
        "request_id": rid,
        "instrument_type": extracted_fields.get("instrument_type"),
        "currency": extracted_fields.get("currency"),
        "price": round(result.npv, 2),
        "pv01": round(result.pv01, 2),
        "status": "indicative",
        "assumptions": assumptions,
        "warnings": [],
    }
