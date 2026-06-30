from __future__ import annotations

import re as _re
from datetime import date
from typing import Any, Dict, List, Literal, Optional, TypeAlias

from pydantic import BaseModel, field_validator, model_validator

_SUPPORTED_CURVE_FREQUENCIES: frozenset[str] = frozenset(
    {"annual", "semiannual", "quarterly", "monthly"}
)
InstrumentDayCount: TypeAlias = Literal[
    "ACT_365F",
    "ACT_360",
    "30_360",
    "ACT_ACT_ISDA",
]
FRADayCount: TypeAlias = InstrumentDayCount
BondDayCount: TypeAlias = InstrumentDayCount

_SUPPORTED_INSTRUMENT_DAY_COUNTS: frozenset[str] = frozenset(
    {"ACT_365F", "ACT_360", "30_360", "ACT_ACT_ISDA"}
)
_SUPPORTED_BOND_DAY_COUNTS: frozenset[str] = _SUPPORTED_INSTRUMENT_DAY_COUNTS
_SUPPORTED_CURVE_DAY_COUNTS: frozenset[str] = frozenset(
    {"ACT_365F", "ACT_360", "30_360", "ACT_ACT_ISDA"}
)


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
    """A single par-swap quote."""

    tenor_years: int
    par_rate: float


class CurveInputs(BaseModel):
    """
    Optional market-data block supplied to /price or /quote to drive
    bootstrapped-curve pricing.

    When present, a discount curve is bootstrapped from these market
    quotes (using quant_core.curves.bootstrap_mixed) instead of the
    default flat 8% ZAR JIBAR proxy.

    At least one of ``deposits``, ``fras``, or ``swaps`` must be
    non-empty (enforced at pricing time so the warning is part of the
    pricing response, not a bare 422).
    """

    valuation_date: Optional[str] = None
    payment_frequency: str = "annual"
    day_count: InstrumentDayCount = "ACT_365F"
    deposits: Optional[List[DepositInput]] = None
    fras: Optional[List[FRAInput]] = None
    swaps: Optional[List[SwapInput]] = None

    @field_validator("payment_frequency", mode="before")
    @classmethod
    def validate_payment_frequency(cls, v: str) -> str:
        normalised = str(v).lower()
        if normalised not in _SUPPORTED_CURVE_FREQUENCIES:
            raise ValueError(
                f"payment_frequency '{v}' is not supported. "
                f"Supported values: {sorted(_SUPPORTED_CURVE_FREQUENCIES)}."
            )
        return normalised

    @field_validator("day_count")
    @classmethod
    def validate_day_count(cls, v: str) -> str:
        if v not in _SUPPORTED_CURVE_DAY_COUNTS:
            raise ValueError(
                f"day_count '{v}' is not supported. "
                f"Supported values: {sorted(_SUPPORTED_CURVE_DAY_COUNTS)}."
            )
        return v

    @field_validator("valuation_date")
    @classmethod
    def validate_valuation_date(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            try:
                date.fromisoformat(v)
            except ValueError:
                raise ValueError(
                    f"valuation_date '{v}' is not a valid ISO-8601 date "
                    "(expected format: YYYY-MM-DD)."
                )
        return v


class PricingRequest(BaseModel):
    request_id: Optional[str] = None
    extracted_fields: Dict[str, Any]
    curve_inputs: Optional[CurveInputs] = None


class PricingResponse(BaseModel):
    request_id: str
    instrument_type: Optional[str] = None
    currency: Optional[str] = None
    price: float
    pv01: float
    status: str
    assumptions: List[str]
    warnings: List[str]


# ---------------------------------------------------------------------------
# Bond pricing schemas
# ---------------------------------------------------------------------------

_SUPPORTED_BOND_FREQUENCIES: frozenset[str] = frozenset(
    {"annual", "semiannual", "quarterly"}
)


class BondPricingRequest(BaseModel):
    """
    Request body for ``POST /price/bond``.

    All date fields must be ISO-8601 strings (``YYYY-MM-DD``).
    ``curve_inputs`` is optional; when omitted the flat 8% ZAR JIBAR proxy
    curve is used.
    """

    request_id: Optional[str] = None
    instrument_type: str = "bond"
    valuation_date: str
    issue_date: str
    maturity_date: str
    face_value: float
    coupon_rate: float
    coupon_frequency: str
    day_count: BondDayCount
    curve_inputs: Optional[CurveInputs] = None

    @field_validator("valuation_date", "issue_date", "maturity_date")
    @classmethod
    def validate_iso_date(cls, v: str) -> str:
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError(
                f"'{v}' is not a valid ISO-8601 date (expected YYYY-MM-DD)."
            )
        return v

    @field_validator("face_value")
    @classmethod
    def validate_face_value(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"face_value must be > 0; got {v}")
        return v

    @field_validator("coupon_rate")
    @classmethod
    def validate_coupon_rate(cls, v: float) -> float:
        if not (0.0 <= v < 1.0):
            raise ValueError(
                f"coupon_rate must be >= 0 and < 1; got {v}"
            )
        return v

    @field_validator("coupon_frequency", mode="before")
    @classmethod
    def validate_coupon_frequency(cls, v: str) -> str:
        normalised = str(v).lower()
        if normalised not in _SUPPORTED_BOND_FREQUENCIES:
            raise ValueError(
                f"coupon_frequency '{v}' is not supported. "
                f"Supported values: {sorted(_SUPPORTED_BOND_FREQUENCIES)}."
            )
        return normalised

    @field_validator("day_count")
    @classmethod
    def validate_day_count(cls, v: str) -> str:
        if v not in _SUPPORTED_INSTRUMENT_DAY_COUNTS:
            raise ValueError(
                f"day_count '{v}' is not supported. "
                f"Supported values: {sorted(_SUPPORTED_INSTRUMENT_DAY_COUNTS)}."
            )
        return v


class BondPricingResponse(BaseModel):
    """Response body from ``POST /price/bond``."""

    request_id: str
    instrument_type: str = "bond"
    status: str
    clean_price: float
    dirty_price: float
    accrued_interest: float
    n_remaining_coupons: int
    assumptions: List[str]
    warnings: List[str]


# ---------------------------------------------------------------------------
# FRA pricing schemas
# ---------------------------------------------------------------------------

_SUPPORTED_FRA_POSITIONS: frozenset[str] = frozenset({"payer", "receiver"})
_SUPPORTED_FX_FORWARD_POSITIONS: frozenset[str] = frozenset(
    {"long_foreign", "short_foreign"}
)
_SUPPORTED_FX_SWAP_POSITIONS: frozenset[str] = frozenset(
    {"long_foreign", "short_foreign"}
)
_SUPPORTED_FX_OPTION_TYPES: frozenset[str] = frozenset({"call", "put"})
_SUPPORTED_FX_OPTION_POSITIONS: frozenset[str] = frozenset({"long", "short"})
_SUPPORTED_EQUITY_OPTION_TYPES: frozenset[str] = frozenset({"call", "put"})
_SUPPORTED_EQUITY_OPTION_POSITIONS: frozenset[str] = frozenset({"long", "short"})


class FRAPriceRequest(BaseModel):
    """
    Request body for ``POST /price/fra``.

    If ``curve_inputs.valuation_date`` is supplied, it must equal the FRA
    request ``valuation_date``. This keeps the pricing contract explicit and
    prevents silent divergence between trade valuation and curve valuation.
    """

    request_id: Optional[str] = None
    instrument_type: str = "fra"
    valuation_date: str
    start_date: str
    end_date: str
    notional: float
    contract_rate: float
    day_count: FRADayCount
    position: str
    curve_inputs: Optional[CurveInputs] = None

    @field_validator("instrument_type", mode="before")
    @classmethod
    def validate_instrument_type(cls, v: str) -> str:
        if str(v).lower() != "fra":
            raise ValueError(f"instrument_type must be 'fra'; got '{v}'.")
        return "fra"

    @field_validator("valuation_date", "start_date", "end_date")
    @classmethod
    def validate_iso_date(cls, v: str) -> str:
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError(
                f"'{v}' is not a valid ISO-8601 date (expected YYYY-MM-DD)."
            )
        return v

    @field_validator("notional")
    @classmethod
    def validate_notional(cls, v: float) -> float:
        if v <= 0.0:
            raise ValueError(f"notional must be > 0; got {v}")
        return v

    @field_validator("contract_rate")
    @classmethod
    def validate_contract_rate(cls, v: float) -> float:
        if not (0.0 <= v < 1.0):
            raise ValueError(
                f"contract_rate must be >= 0 and < 1; got {v}"
            )
        return v

    @field_validator("day_count")
    @classmethod
    def validate_day_count(cls, v: str) -> str:
        if v not in _SUPPORTED_INSTRUMENT_DAY_COUNTS:
            raise ValueError(
                f"day_count '{v}' is not supported. "
                f"Supported values: {sorted(_SUPPORTED_INSTRUMENT_DAY_COUNTS)}."
            )
        return v

    @field_validator("position", mode="before")
    @classmethod
    def validate_position(cls, v: str) -> str:
        normalised = str(v).lower()
        if normalised not in _SUPPORTED_FRA_POSITIONS:
            raise ValueError(
                f"position '{v}' is not supported. Expected 'payer' or 'receiver'."
            )
        return normalised

    @model_validator(mode="after")
    def validate_date_ordering(self) -> "FRAPriceRequest":
        valuation_date = date.fromisoformat(self.valuation_date)
        start_date = date.fromisoformat(self.start_date)
        end_date = date.fromisoformat(self.end_date)

        if (
            self.curve_inputs is not None
            and self.curve_inputs.valuation_date is not None
            and self.curve_inputs.valuation_date != self.valuation_date
        ):
            raise ValueError(
                "curve_inputs.valuation_date must equal valuation_date for FRA requests; "
                f"got curve_inputs.valuation_date={self.curve_inputs.valuation_date} "
                f"and valuation_date={self.valuation_date}."
            )

        if start_date <= valuation_date:
            raise ValueError(
                f"start_date {self.start_date} must be > valuation_date {self.valuation_date}"
            )
        if end_date <= start_date:
            raise ValueError(
                f"end_date {self.end_date} must be > start_date {self.start_date}"
            )
        return self


class FRAPriceResponse(BaseModel):
    """Response body from ``POST /price/fra``."""

    request_id: str
    instrument_type: str = "fra"
    status: str
    forward_rate: float
    year_fraction: float
    discount_factor_to_payment: float
    payoff_undiscounted: float
    pv: float
    curve_source: str
    assumptions: List[str]
    warnings: List[str]


# ---------------------------------------------------------------------------
# FX forward pricing schemas
# ---------------------------------------------------------------------------


class FXForwardPriceRequest(BaseModel):
    """Request body for ``POST /price/fx-forward``."""

    request_id: Optional[str] = None
    instrument_type: str = "fx_forward"
    valuation_date: str
    maturity_date: str
    notional_foreign: float
    spot_rate: float
    contract_forward_rate: float
    domestic_rate: float
    foreign_rate: float
    domestic_currency: str
    foreign_currency: str
    day_count: InstrumentDayCount
    position: str

    @field_validator("instrument_type", mode="before")
    @classmethod
    def validate_instrument_type(cls, v: str) -> str:
        if str(v).lower() != "fx_forward":
            raise ValueError(f"instrument_type must be 'fx_forward'; got '{v}'.")
        return "fx_forward"

    @field_validator("valuation_date", "maturity_date")
    @classmethod
    def validate_iso_date(cls, v: str) -> str:
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError(
                f"'{v}' is not a valid ISO-8601 date (expected YYYY-MM-DD)."
            )
        return v

    @field_validator("notional_foreign")
    @classmethod
    def validate_notional_foreign(cls, v: float) -> float:
        if v <= 0.0:
            raise ValueError(f"notional_foreign must be > 0; got {v}")
        return v

    @field_validator("spot_rate", "contract_forward_rate")
    @classmethod
    def validate_positive_quote(cls, v: float, info) -> float:
        if v <= 0.0:
            raise ValueError(f"{info.field_name} must be > 0; got {v}")
        return v

    @field_validator("domestic_rate", "foreign_rate")
    @classmethod
    def validate_rate_input(cls, v: float, info) -> float:
        if v <= -1.0:
            raise ValueError(
                f"{info.field_name} must be > -1.0 under simple compounding; got {v}"
            )
        return v

    @field_validator("domestic_currency", "foreign_currency", mode="before")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        normalised = str(v).upper()
        if not _re.fullmatch(r"[A-Z]{3}", normalised):
            raise ValueError(
                f"currency '{v}' is not supported. Expected a 3-letter ISO code."
            )
        return normalised

    @field_validator("day_count")
    @classmethod
    def validate_day_count(cls, v: str) -> str:
        if v not in _SUPPORTED_INSTRUMENT_DAY_COUNTS:
            raise ValueError(
                f"day_count '{v}' is not supported. "
                f"Supported values: {sorted(_SUPPORTED_INSTRUMENT_DAY_COUNTS)}."
            )
        return v

    @field_validator("position", mode="before")
    @classmethod
    def validate_position(cls, v: str) -> str:
        normalised = str(v).lower()
        if normalised not in _SUPPORTED_FX_FORWARD_POSITIONS:
            raise ValueError(
                "position '"
                f"{v}' is not supported. Expected 'long_foreign' or 'short_foreign'."
            )
        return normalised

    @model_validator(mode="after")
    def validate_economics(self) -> "FXForwardPriceRequest":
        valuation_date = date.fromisoformat(self.valuation_date)
        maturity_date = date.fromisoformat(self.maturity_date)

        if maturity_date <= valuation_date:
            raise ValueError(
                f"maturity_date {self.maturity_date} must be > valuation_date {self.valuation_date}"
            )
        if self.domestic_currency == self.foreign_currency:
            raise ValueError(
                "domestic_currency and foreign_currency must differ; "
                f"got {self.domestic_currency}/{self.foreign_currency}."
            )
        return self


class FXForwardPriceResponse(BaseModel):
    """Response body from ``POST /price/fx-forward``."""

    request_id: str
    instrument_type: str = "fx_forward"
    status: str
    domestic_currency: str
    foreign_currency: str
    year_fraction: float
    domestic_discount_factor: float
    foreign_discount_factor: float
    implied_forward_rate: float
    forward_points: float
    payoff_undiscounted_domestic: float
    present_value_domestic: float
    pv_currency: str
    rate_source: str
    assumptions: List[str]
    warnings: List[str]


# ---------------------------------------------------------------------------
# FX swap pricing schemas
# ---------------------------------------------------------------------------


class FXSwapPriceRequest(BaseModel):
    """Request body for ``POST /price/fx-swap``."""

    request_id: Optional[str] = None
    instrument_type: str = "fx_swap"
    valuation_date: str
    near_settlement_date: str
    far_settlement_date: str
    spot_rate: float
    near_rate: float
    far_rate: float
    notional_foreign: float
    domestic_currency: str
    foreign_currency: str
    domestic_rate: float
    day_count: InstrumentDayCount
    position: str

    @field_validator("instrument_type", mode="before")
    @classmethod
    def validate_instrument_type(cls, v: str) -> str:
        if str(v).lower() != "fx_swap":
            raise ValueError(f"instrument_type must be 'fx_swap'; got '{v}'.")
        return "fx_swap"

    @field_validator("valuation_date", "near_settlement_date", "far_settlement_date")
    @classmethod
    def validate_iso_date(cls, v: str) -> str:
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError(
                f"'{v}' is not a valid ISO-8601 date (expected YYYY-MM-DD)."
            )
        return v

    @field_validator("spot_rate", "near_rate", "far_rate")
    @classmethod
    def validate_positive_quote(cls, v: float, info) -> float:
        if v <= 0.0:
            raise ValueError(f"{info.field_name} must be > 0; got {v}")
        return v

    @field_validator("notional_foreign")
    @classmethod
    def validate_notional_foreign(cls, v: float) -> float:
        if v <= 0.0:
            raise ValueError(f"notional_foreign must be > 0; got {v}")
        return v

    @field_validator("domestic_rate")
    @classmethod
    def validate_domestic_rate(cls, v: float) -> float:
        if v <= -1.0:
            raise ValueError(
                f"domestic_rate must be > -1.0 under simple compounding; got {v}"
            )
        return v

    @field_validator("domestic_currency", "foreign_currency", mode="before")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        normalised = str(v).upper()
        if not _re.fullmatch(r"[A-Z]{3}", normalised):
            raise ValueError(
                f"currency '{v}' is not supported. Expected a 3-letter ISO code."
            )
        return normalised

    @field_validator("day_count")
    @classmethod
    def validate_day_count(cls, v: str) -> str:
        if v not in _SUPPORTED_INSTRUMENT_DAY_COUNTS:
            raise ValueError(
                f"day_count '{v}' is not supported. "
                f"Supported values: {sorted(_SUPPORTED_INSTRUMENT_DAY_COUNTS)}."
            )
        return v

    @field_validator("position", mode="before")
    @classmethod
    def validate_position(cls, v: str) -> str:
        normalised = str(v).lower()
        if normalised not in _SUPPORTED_FX_SWAP_POSITIONS:
            raise ValueError(
                "position '"
                f"{v}' is not supported. Expected 'long_foreign' or 'short_foreign'."
            )
        return normalised

    @model_validator(mode="after")
    def validate_economics(self) -> "FXSwapPriceRequest":
        valuation_date = date.fromisoformat(self.valuation_date)
        near_settlement_date = date.fromisoformat(self.near_settlement_date)
        far_settlement_date = date.fromisoformat(self.far_settlement_date)

        if near_settlement_date <= valuation_date:
            raise ValueError(
                "near_settlement_date "
                f"{self.near_settlement_date} must be > valuation_date {self.valuation_date}"
            )
        if far_settlement_date <= near_settlement_date:
            raise ValueError(
                "far_settlement_date "
                f"{self.far_settlement_date} must be > near_settlement_date {self.near_settlement_date}"
            )
        if self.domestic_currency == self.foreign_currency:
            raise ValueError(
                "domestic_currency and foreign_currency must differ; "
                f"got {self.domestic_currency}/{self.foreign_currency}."
            )
        return self


class FXSwapPriceResponse(BaseModel):
    """Response body from ``POST /price/fx-swap``."""

    request_id: str
    instrument_type: str = "fx_swap"
    status: str
    domestic_currency: str
    foreign_currency: str
    year_fraction_near: float
    year_fraction_far: float
    domestic_discount_factor_near: float
    domestic_discount_factor_far: float
    near_leg_value_domestic: float
    far_leg_value_domestic: float
    swap_points: float
    present_value_domestic: float
    pv_currency: str
    rate_source: str
    assumptions: List[str]
    warnings: List[str]


# ---------------------------------------------------------------------------
# FX option pricing schemas
# ---------------------------------------------------------------------------


class FXOptionPriceRequest(BaseModel):
    """Request body for ``POST /price/fx-option``."""

    request_id: Optional[str] = None
    instrument_type: str = "fx_option"
    valuation_date: str
    expiry_date: str
    settlement_date: Optional[str] = None
    spot_rate: float
    strike_rate: float
    domestic_rate: float
    foreign_rate: float
    volatility: float
    notional_foreign: float
    option_type: str
    position: str
    domestic_currency: str
    foreign_currency: str
    day_count: InstrumentDayCount

    @field_validator("instrument_type", mode="before")
    @classmethod
    def validate_instrument_type(cls, v: str) -> str:
        if str(v).lower() != "fx_option":
            raise ValueError(f"instrument_type must be 'fx_option'; got '{v}'.")
        return "fx_option"

    @field_validator("valuation_date", "expiry_date", "settlement_date")
    @classmethod
    def validate_iso_date(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError(
                f"'{v}' is not a valid ISO-8601 date (expected YYYY-MM-DD)."
            )
        return v

    @field_validator("spot_rate", "strike_rate")
    @classmethod
    def validate_positive_quote(cls, v: float, info) -> float:
        if v <= 0.0:
            raise ValueError(f"{info.field_name} must be > 0; got {v}")
        return v

    @field_validator("volatility")
    @classmethod
    def validate_volatility(cls, v: float) -> float:
        if v <= 0.0:
            raise ValueError(f"volatility must be > 0; got {v}")
        return v

    @field_validator("notional_foreign")
    @classmethod
    def validate_notional_foreign(cls, v: float) -> float:
        if v <= 0.0:
            raise ValueError(f"notional_foreign must be > 0; got {v}")
        return v

    @field_validator("domestic_currency", "foreign_currency", mode="before")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        normalised = str(v).upper()
        if not _re.fullmatch(r"[A-Z]{3}", normalised):
            raise ValueError(
                f"currency '{v}' is not supported. Expected a 3-letter ISO code."
            )
        return normalised

    @field_validator("day_count")
    @classmethod
    def validate_day_count(cls, v: str) -> str:
        if v not in _SUPPORTED_INSTRUMENT_DAY_COUNTS:
            raise ValueError(
                f"day_count '{v}' is not supported. "
                f"Supported values: {sorted(_SUPPORTED_INSTRUMENT_DAY_COUNTS)}."
            )
        return v

    @field_validator("option_type", mode="before")
    @classmethod
    def validate_option_type(cls, v: str) -> str:
        normalised = str(v).lower()
        if normalised not in _SUPPORTED_FX_OPTION_TYPES:
            raise ValueError(
                f"option_type '{v}' is not supported. Expected 'call' or 'put'."
            )
        return normalised

    @field_validator("position", mode="before")
    @classmethod
    def validate_position(cls, v: str) -> str:
        normalised = str(v).lower()
        if normalised not in _SUPPORTED_FX_OPTION_POSITIONS:
            raise ValueError(
                f"position '{v}' is not supported. Expected 'long' or 'short'."
            )
        return normalised

    @model_validator(mode="after")
    def validate_economics(self) -> "FXOptionPriceRequest":
        valuation_date = date.fromisoformat(self.valuation_date)
        expiry_date = date.fromisoformat(self.expiry_date)
        settlement_date = date.fromisoformat(self.settlement_date) if self.settlement_date else expiry_date

        if expiry_date <= valuation_date:
            raise ValueError(
                f"expiry_date {self.expiry_date} must be > valuation_date {self.valuation_date}"
            )
        if settlement_date < expiry_date:
            raise ValueError(
                f"settlement_date {settlement_date.isoformat()} must be >= expiry_date {self.expiry_date}"
            )
        if self.domestic_currency == self.foreign_currency:
            raise ValueError(
                "domestic_currency and foreign_currency must differ; "
                f"got {self.domestic_currency}/{self.foreign_currency}."
            )
        return self


class FXOptionPriceResponse(BaseModel):
    """Response body from ``POST /price/fx-option``."""

    request_id: str
    instrument_type: str = "fx_option"
    status: str
    domestic_currency: str
    foreign_currency: str
    year_fraction: float
    settlement_year_fraction: float
    domestic_discount_factor: float
    foreign_discount_factor: float
    forward_rate: float
    premium_domestic: float
    premium_foreign: float
    delta: float
    gamma: float
    vega: float
    pv_currency: str
    model_source: str
    assumptions: List[str]
    warnings: List[str]


# ---------------------------------------------------------------------------
# Equity option pricing schemas
# ---------------------------------------------------------------------------


class EquityOptionPriceRequest(BaseModel):
    """Request body for ``POST /price/equity-option``."""

    request_id: Optional[str] = None
    instrument_type: str = "equity_option"
    valuation_date: str
    expiry_date: str
    spot_price: float
    strike_price: float
    risk_free_rate: float
    dividend_yield: float
    volatility: float
    quantity_shares: float
    option_type: str
    position: str
    currency: str
    day_count: InstrumentDayCount
    underlying_name: Optional[str] = None

    @field_validator("instrument_type", mode="before")
    @classmethod
    def validate_instrument_type(cls, v: str) -> str:
        if str(v).lower() != "equity_option":
            raise ValueError(f"instrument_type must be 'equity_option'; got '{v}'.")
        return "equity_option"

    @field_validator("valuation_date", "expiry_date")
    @classmethod
    def validate_iso_date(cls, v: str) -> str:
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError(
                f"'{v}' is not a valid ISO-8601 date (expected YYYY-MM-DD)."
            )
        return v

    @field_validator("spot_price", "strike_price")
    @classmethod
    def validate_positive_quote(cls, v: float, info) -> float:
        if v <= 0.0:
            raise ValueError(f"{info.field_name} must be > 0; got {v}")
        return v

    @field_validator("volatility")
    @classmethod
    def validate_volatility(cls, v: float) -> float:
        if v <= 0.0:
            raise ValueError(f"volatility must be > 0; got {v}")
        return v

    @field_validator("quantity_shares")
    @classmethod
    def validate_quantity_shares(cls, v: float) -> float:
        if v <= 0.0:
            raise ValueError(f"quantity_shares must be > 0; got {v}")
        return v

    @field_validator("currency", mode="before")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        normalised = str(v).upper()
        if not _re.fullmatch(r"[A-Z]{3}", normalised):
            raise ValueError(
                f"currency '{v}' is not supported. Expected a 3-letter ISO code."
            )
        return normalised

    @field_validator("day_count")
    @classmethod
    def validate_day_count(cls, v: str) -> str:
        if v not in _SUPPORTED_INSTRUMENT_DAY_COUNTS:
            raise ValueError(
                f"day_count '{v}' is not supported. "
                f"Supported values: {sorted(_SUPPORTED_INSTRUMENT_DAY_COUNTS)}."
            )
        return v

    @field_validator("option_type", mode="before")
    @classmethod
    def validate_option_type(cls, v: str) -> str:
        normalised = str(v).lower()
        if normalised not in _SUPPORTED_EQUITY_OPTION_TYPES:
            raise ValueError(
                f"option_type '{v}' is not supported. Expected 'call' or 'put'."
            )
        return normalised

    @field_validator("position", mode="before")
    @classmethod
    def validate_position(cls, v: str) -> str:
        normalised = str(v).lower()
        if normalised not in _SUPPORTED_EQUITY_OPTION_POSITIONS:
            raise ValueError(
                f"position '{v}' is not supported. Expected 'long' or 'short'."
            )
        return normalised

    @field_validator("underlying_name", mode="before")
    @classmethod
    def validate_underlying_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        stripped = str(v).strip()
        return stripped or None

    @model_validator(mode="after")
    def validate_economics(self) -> "EquityOptionPriceRequest":
        valuation_date = date.fromisoformat(self.valuation_date)
        expiry_date = date.fromisoformat(self.expiry_date)
        if expiry_date <= valuation_date:
            raise ValueError(
                f"expiry_date {self.expiry_date} must be > valuation_date {self.valuation_date}"
            )
        return self


class EquityOptionPriceResponse(BaseModel):
    """Response body from ``POST /price/equity-option``."""

    request_id: str
    instrument_type: str = "equity_option"
    status: str
    underlying_name: Optional[str] = None
    currency: str
    year_fraction: float
    discount_factor: float
    dividend_discount_factor: float
    forward_price: float
    premium: float
    delta: float
    gamma: float
    vega: float
    pv_currency: str
    model_source: str
    assumptions: List[str]
    warnings: List[str]


# ---------------------------------------------------------------------------
# Bond YTM schemas
# ---------------------------------------------------------------------------


class BondYTMRequest(BaseModel):
    """
    Request body for ``POST /price/bond/ytm``.

    Solve for the flat annual yield that reproduces *market_dirty_price*
    under the simple-rate flat-curve convention::

        df(t) = 1 / (1 + y × τ)

    All date fields must be ISO-8601 strings (``YYYY-MM-DD``).
    """

    request_id: Optional[str] = None
    instrument_type: str = "bond"
    valuation_date: str
    issue_date: str
    maturity_date: str
    face_value: float
    coupon_rate: float
    coupon_frequency: str
    day_count: BondDayCount
    market_dirty_price: float

    @field_validator("valuation_date", "issue_date", "maturity_date")
    @classmethod
    def validate_iso_date(cls, v: str) -> str:
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError(
                f"'{v}' is not a valid ISO-8601 date (expected YYYY-MM-DD)."
            )
        return v

    @field_validator("face_value")
    @classmethod
    def validate_face_value(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"face_value must be > 0; got {v}")
        return v

    @field_validator("coupon_rate")
    @classmethod
    def validate_coupon_rate(cls, v: float) -> float:
        if not (0.0 <= v < 1.0):
            raise ValueError(
                f"coupon_rate must be >= 0 and < 1; got {v}"
            )
        return v

    @field_validator("coupon_frequency", mode="before")
    @classmethod
    def validate_coupon_frequency(cls, v: str) -> str:
        normalised = str(v).lower()
        if normalised not in _SUPPORTED_BOND_FREQUENCIES:
            raise ValueError(
                f"coupon_frequency '{v}' is not supported. "
                f"Supported values: {sorted(_SUPPORTED_BOND_FREQUENCIES)}."
            )
        return normalised

    @field_validator("day_count")
    @classmethod
    def validate_day_count(cls, v: str) -> str:
        if v not in _SUPPORTED_INSTRUMENT_DAY_COUNTS:
            raise ValueError(
                f"day_count '{v}' is not supported. "
                f"Supported values: {sorted(_SUPPORTED_INSTRUMENT_DAY_COUNTS)}."
            )
        return v

    @field_validator("market_dirty_price")
    @classmethod
    def validate_market_dirty_price(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"market_dirty_price must be > 0; got {v}")
        return v


class BondYTMResponse(BaseModel):
    """Response body from ``POST /price/bond/ytm``."""

    request_id: str
    instrument_type: str = "bond"
    status: str
    market_dirty_price: float
    ytm: float
    assumptions: List[str]
    warnings: List[str]


# ---------------------------------------------------------------------------
# Bond cashflow schedule schemas
# ---------------------------------------------------------------------------


class BondCashflowRow(BaseModel):
    """One cashflow row returned by ``POST /price/bond/cashflows``."""

    payment_date: str
    accrual_start: str
    accrual_end: str
    year_fraction: float
    coupon_cashflow: float
    principal_cashflow: float
    total_cashflow: float
    discount_factor: float
    pv_cashflow: float
    time_to_payment_years: float


class BondCashflowRequest(BaseModel):
    """
    Request body for ``POST /price/bond/cashflows``.

    Identical bond description fields as :class:`BondPricingRequest`; reuses
    the same validators.  ``curve_inputs`` is optional.
    """

    request_id: Optional[str] = None
    instrument_type: str = "bond"
    valuation_date: str
    issue_date: str
    maturity_date: str
    face_value: float
    coupon_rate: float
    coupon_frequency: str
    day_count: BondDayCount
    curve_inputs: Optional[CurveInputs] = None

    @field_validator("valuation_date", "issue_date", "maturity_date")
    @classmethod
    def validate_iso_date(cls, v: str) -> str:
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError(
                f"'{v}' is not a valid ISO-8601 date (expected YYYY-MM-DD)."
            )
        return v

    @field_validator("face_value")
    @classmethod
    def validate_face_value(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"face_value must be > 0; got {v}")
        return v

    @field_validator("coupon_rate")
    @classmethod
    def validate_coupon_rate(cls, v: float) -> float:
        if not (0.0 <= v < 1.0):
            raise ValueError(f"coupon_rate must be >= 0 and < 1; got {v}")
        return v

    @field_validator("coupon_frequency", mode="before")
    @classmethod
    def validate_coupon_frequency(cls, v: str) -> str:
        normalised = str(v).lower()
        if normalised not in _SUPPORTED_BOND_FREQUENCIES:
            raise ValueError(
                f"coupon_frequency '{v}' is not supported. "
                f"Supported values: {sorted(_SUPPORTED_BOND_FREQUENCIES)}."
            )
        return normalised

    @field_validator("day_count")
    @classmethod
    def validate_day_count(cls, v: str) -> str:
        if v not in _SUPPORTED_INSTRUMENT_DAY_COUNTS:
            raise ValueError(
                f"day_count '{v}' is not supported. "
                f"Supported values: {sorted(_SUPPORTED_INSTRUMENT_DAY_COUNTS)}."
            )
        return v


class BondCashflowResponse(BaseModel):
    """Response body from ``POST /price/bond/cashflows``."""

    request_id: str
    instrument_type: str = "bond"
    status: str
    dirty_price: float
    n_remaining_coupons: int
    cashflows: List[BondCashflowRow]
    assumptions: List[str]
    warnings: List[str]


# ---------------------------------------------------------------------------
# IRS cashflow schedule schemas
# ---------------------------------------------------------------------------


class IRSCashflowRow(BaseModel):
    """One fixed-leg payment row returned by ``POST /price/irs/cashflows``."""

    payment_date: str
    accrual_start: str
    accrual_end: str
    year_fraction: float
    fixed_rate: float
    notional: float
    fixed_cashflow: float
    discount_factor: float
    pv_cashflow: float
    time_to_payment_years: float


class IRSCashflowRequest(BaseModel):
    """
    Request body for ``POST /price/irs/cashflows``.

    Accepts the same ``extracted_fields`` dict as :class:`PricingRequest`
    (i.e. the output of the NLP extraction step in ``POST /quote``) plus
    an optional ``curve_inputs`` block.
    """

    request_id: Optional[str] = None
    extracted_fields: Dict[str, Any]
    curve_inputs: Optional[CurveInputs] = None


class IRSCashflowResponse(BaseModel):
    """Response body from ``POST /price/irs/cashflows``."""

    request_id: str
    instrument_type: Optional[str] = "irs"
    currency: Optional[str] = None
    status: str
    fixed_leg_pv: float
    n_payments: int
    cashflows: List[IRSCashflowRow]
    assumptions: List[str]
    warnings: List[str]


# ---------------------------------------------------------------------------
# IRS valuation breakdown schemas
# ---------------------------------------------------------------------------


class IRSBreakdownRequest(BaseModel):
    """
    Request body for ``POST /price/irs/breakdown``.

    Accepts the same ``extracted_fields`` dict as :class:`PricingRequest`
    plus an optional ``curve_inputs`` block.  The trade must be a supported
    ZAR IRS JIBAR instrument.
    """

    request_id: Optional[str] = None
    extracted_fields: Dict[str, Any]
    curve_inputs: Optional[CurveInputs] = None


class IRSBreakdownResponse(BaseModel):
    """Response body from ``POST /price/irs/breakdown``."""

    request_id: str
    instrument_type: Optional[str] = "irs"
    currency: Optional[str] = None
    status: str
    fixed_leg_pv: float
    floating_leg_pv: float
    npv: float
    n_payments: int
    curve_source: str
    floating_leg_method: str
    assumptions: List[str]
    warnings: List[str]


# ---------------------------------------------------------------------------
# IRS fair-rate solver schemas
# ---------------------------------------------------------------------------


class IRSFairRateRequest(BaseModel):
    """
    Request body for ``POST /price/irs/fair-rate``.

    Accepts the same ``extracted_fields`` dict as :class:`PricingRequest`
    (instrument_type, currency, direction, floating_index, payment_frequency,
    tenor, notional) plus an optional ``curve_inputs`` block.

    ``fixed_rate`` in ``extracted_fields``, if present, is ignored during
    solving.  The endpoint returns the fair rate, not an NPV.
    """

    request_id: Optional[str] = None
    extracted_fields: Dict[str, Any]
    curve_inputs: Optional[CurveInputs] = None


class IRSFairRateResponse(BaseModel):
    """Response body from ``POST /price/irs/fair-rate``."""

    request_id: str
    instrument_type: Optional[str] = "irs"
    currency: Optional[str] = None
    status: str
    fair_rate: float
    fixed_leg_annuity: float
    curve_source: str
    assumptions: List[str]
    warnings: List[str]


# ---------------------------------------------------------------------------
# IRS direct pricing schemas (structured, no NLP extraction)
# ---------------------------------------------------------------------------

_SUPPORTED_IRS_DIRECTIONS: frozenset[str] = frozenset({"payer", "receiver"})
_SUPPORTED_IRS_FREQUENCIES: frozenset[str] = frozenset({"quarterly", "semiannual", "annual"})


class IRSDirectPriceRequest(BaseModel):
    """
    Request body for ``POST /price/irs``.

    A fully-typed structured IRS pricing request — no NLP extraction
    required.  All fields are explicit and validated at the schema level.
    ``curve_inputs`` is optional; when omitted the flat 8% ZAR JIBAR
    proxy curve is used.
    """

    request_id: Optional[str] = None
    instrument_type: str = "irs"
    currency: str
    direction: str
    floating_index: str
    payment_frequency: str
    tenor: str
    notional: float
    fixed_rate: Optional[float] = None
    curve_inputs: Optional[CurveInputs] = None

    @field_validator("instrument_type", mode="before")
    @classmethod
    def validate_instrument_type(cls, v: str) -> str:
        if str(v).lower() != "irs":
            raise ValueError(f"instrument_type must be 'irs'; got '{v}'.")
        return "irs"

    @field_validator("currency", mode="before")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        if str(v).upper() != "ZAR":
            raise ValueError(
                f"currency '{v}' is not supported. Only 'ZAR' is currently supported."
            )
        return str(v).upper()

    @field_validator("direction", mode="before")
    @classmethod
    def validate_direction(cls, v: str) -> str:
        normalised = str(v).lower()
        if normalised not in _SUPPORTED_IRS_DIRECTIONS:
            raise ValueError(
                f"direction '{v}' is not supported. "
                "Expected 'payer' or 'receiver'."
            )
        return normalised

    @field_validator("floating_index", mode="before")
    @classmethod
    def validate_floating_index(cls, v: str) -> str:
        if str(v).upper() != "JIBAR":
            raise ValueError(
                f"floating_index '{v}' is not supported. "
                "Only 'JIBAR' is currently supported."
            )
        return str(v).upper()

    @field_validator("payment_frequency", mode="before")
    @classmethod
    def validate_payment_frequency(cls, v: str) -> str:
        normalised = str(v).lower()
        if normalised not in _SUPPORTED_IRS_FREQUENCIES:
            raise ValueError(
                f"payment_frequency '{v}' is not supported. "
                f"Supported values: {sorted(_SUPPORTED_IRS_FREQUENCIES)}."
            )
        return normalised

    @field_validator("tenor")
    @classmethod
    def validate_tenor(cls, v: str) -> str:
        m = _re.match(r"^(\d+)[Yy]$", str(v).strip())
        if not m:
            raise ValueError(
                f"tenor '{v}' is not valid. Expected format: '5Y', '10Y', etc."
            )
        years = int(m.group(1))
        if years < 1 or years > 50:
            raise ValueError(
                f"tenor '{v}' ({years}Y) is out of the supported range [1Y, 50Y]."
            )
        return v.upper()

    @field_validator("notional")
    @classmethod
    def validate_notional(cls, v: float) -> float:
        if v < 1_000:
            raise ValueError(
                f"notional {v:,.0f} is implausibly small. "
                "Expected at least 1,000 in the trade currency."
            )
        if v > 100_000_000_000:
            raise ValueError(
                f"notional {v:,.0f} exceeds the maximum supported value "
                "of 100,000,000,000 (100 billion)."
            )
        return v

    @field_validator("fixed_rate")
    @classmethod
    def validate_fixed_rate(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0.0 < v < 1.0):
            raise ValueError(
                f"fixed_rate {v:.6g} is out of range. "
                "Expected a decimal between 0 (exclusive) and 1 (exclusive), "
                "e.g. 0.085 for 8.5%."
            )
        return v


class IRSDirectPriceResponse(BaseModel):
    """Response body from ``POST /price/irs``."""

    request_id: str
    instrument_type: str = "irs"
    currency: Optional[str] = None
    status: str
    price: float
    pv01: float
    curve_source: str
    assumptions: List[str]
    warnings: List[str]


# ---------------------------------------------------------------------------
# IRS direct cashflow schemas (structured, no NLP extraction)
# ---------------------------------------------------------------------------


class IRSDirectCashflowRequest(IRSDirectPriceRequest):
    """
    Request body for ``POST /price/irs/cashflows/direct``.

    Inherits all typed fields and validators from
    :class:`IRSDirectPriceRequest` — instrument_type, currency,
    direction, floating_index, payment_frequency, tenor, notional,
    fixed_rate (optional), and curve_inputs (optional) — so the
    structured cashflow endpoint accepts exactly the same payload as
    the structured pricing endpoint.
    """


class IRSDirectCashflowResponse(BaseModel):
    """Response body from ``POST /price/irs/cashflows/direct``."""

    request_id: str
    instrument_type: str = "irs"
    currency: Optional[str] = None
    status: str
    fixed_leg_pv: float
    n_payments: int
    cashflows: List[IRSCashflowRow]
    curve_source: str
    assumptions: List[str]
    warnings: List[str]


# ---------------------------------------------------------------------------
# IRS direct breakdown schemas (structured, no NLP extraction)
# ---------------------------------------------------------------------------


class IRSDirectBreakdownRequest(IRSDirectPriceRequest):
    """
    Request body for ``POST /price/irs/breakdown/direct``.

    Inherits all typed fields and validators from
    :class:`IRSDirectPriceRequest` — instrument_type, currency,
    direction, floating_index, payment_frequency, tenor, notional,
    fixed_rate (optional), and curve_inputs (optional) — so the
    structured breakdown endpoint accepts exactly the same payload as
    the structured pricing and structured cashflow endpoints.
    """


class IRSDirectBreakdownResponse(BaseModel):
    """Response body from ``POST /price/irs/breakdown/direct``."""

    request_id: str
    instrument_type: str = "irs"
    currency: Optional[str] = None
    status: str
    fixed_leg_pv: float
    floating_leg_pv: float
    npv: float
    n_payments: int
    curve_source: str
    floating_leg_method: str
    assumptions: List[str]
    warnings: List[str]


# ---------------------------------------------------------------------------
# IRS direct fair-rate schemas (structured, no NLP extraction)
# ---------------------------------------------------------------------------


class IRSDirectFairRateRequest(IRSDirectPriceRequest):
    """
    Request body for ``POST /price/irs/fair-rate/direct``.

    Inherits all typed fields and validators from
    :class:`IRSDirectPriceRequest` — instrument_type, currency,
    direction, floating_index, payment_frequency, tenor, notional,
    fixed_rate (optional), and curve_inputs (optional) — so the
    structured fair-rate endpoint accepts exactly the same payload as
    the structured pricing, cashflow, and breakdown endpoints.

    ``fixed_rate``, if present, is accepted but **ignored** during
    solving.  The endpoint always solves for the fair fixed rate
    algebraically via ``solve_irs_fair_rate``.  A ``warnings`` entry is
    included in the response when ``fixed_rate`` was supplied so callers
    can confirm it was not used.
    """


class IRSDirectFairRateResponse(BaseModel):
    """Response body from ``POST /price/irs/fair-rate/direct``."""

    request_id: str
    instrument_type: str = "irs"
    currency: Optional[str] = None
    status: str
    fair_rate: float
    fixed_leg_annuity: float
    curve_source: str
    assumptions: List[str]
    warnings: List[str]
