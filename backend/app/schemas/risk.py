"""
Schemas for POST /risk/ladder — bucketed PV01 ladder for vanilla IRS.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, field_validator

# Re-use price schemas for curve inputs and direct structured IRS validation.
from app.schemas.price import (  # noqa: F401 (re-export for callers)
    CurveInputs,
    IRSDirectPriceRequest,
)


class LadderRequest(BaseModel):
    """
    Request body for ``POST /risk/ladder``.

    Mirrors the shape of :class:`~app.schemas.price.PricingRequest` with an
    additional optional *bucket_years* field.
    """

    request_id: Optional[str] = None
    extracted_fields: Dict[str, Any]
    curve_inputs: Optional[CurveInputs] = None
    bucket_years: Optional[List[int]] = None

    @field_validator("bucket_years")
    @classmethod
    def validate_bucket_years(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        if v is not None:
            for b in v:
                if not isinstance(b, int) or b <= 0:
                    raise ValueError(
                        f"bucket_years must contain positive integers; got {b!r}"
                    )
        return v


class LadderResponse(BaseModel):
    """
    Response body from ``POST /risk/ladder``.

    Attributes
    ----------
    request_id : str
        Echo of the caller-supplied request_id or a generated UUID.
    instrument_type : str | None
        Instrument type from extracted_fields (e.g. ``"irs"``).
    currency : str | None
        Currency from extracted_fields (e.g. ``"ZAR"``).
    bucket_pv01 : dict[str, float]
        Signed key-rate PV01 per tenor bucket (e.g. ``{"1Y": 12.34, ...}``).
        Positive for a payer IRS (benefits from rate rises); negative for a
        receiver.  Buckets beyond the curve domain have value 0.0.
        Empty dict when status is ``"unsupported"``.
    total_abs_pv01 : float
        Sum of absolute bucket PV01 values.  Equals zero when status is
        ``"unsupported"``.  Always non-negative.
    status : str
        ``"indicative"`` for a successfully priced trade; ``"unsupported"``
        when the trade cannot be priced (see *warnings*).
    assumptions : list[str]
        Descriptions of pricing assumptions applied.
    warnings : list[str]
        Reasons why pricing could not be completed (non-empty when
        status is ``"unsupported"``).
    """

    request_id: str
    instrument_type: Optional[str] = None
    currency: Optional[str] = None
    bucket_pv01: Dict[str, float]
    total_abs_pv01: float
    status: str
    assumptions: List[str]
    warnings: List[str]


class IRSDirectLadderRequest(IRSDirectPriceRequest):
    """
    Request body for ``POST /risk/ladder/direct``.

    Inherits all typed fields and validators from
    :class:`app.schemas.price.IRSDirectPriceRequest` and adds an optional
    ``bucket_years`` list for key-rate PV01 bucketing.
    """

    bucket_years: Optional[List[int]] = None

    @field_validator("bucket_years")
    @classmethod
    def validate_bucket_years(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        if v is not None:
            for bucket in v:
                if not isinstance(bucket, int) or bucket <= 0:
                    raise ValueError(
                        f"bucket_years must contain positive integers; got {bucket!r}"
                    )
        return v


class IRSDirectLadderResponse(BaseModel):
    """Response body from ``POST /risk/ladder/direct``."""

    request_id: str
    instrument_type: str = "irs"
    currency: Optional[str] = None
    bucket_pv01: Dict[str, float]
    total_abs_pv01: float
    curve_source: str
    status: str
    assumptions: List[str]
    warnings: List[str]


class IRSDirectScenarioRequest(IRSDirectPriceRequest):
    """
    Request body for ``POST /risk/scenario/direct``.

    Inherits all typed fields and validators from
    :class:`app.schemas.price.IRSDirectPriceRequest` and adds an optional
    ``shift_bps`` list for parallel curve-shift scenario analysis.
    """

    shift_bps: Optional[List[int]] = None

    @field_validator("shift_bps")
    @classmethod
    def validate_shift_bps(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        if v is not None:
            for shift in v:
                if not isinstance(shift, int):
                    raise ValueError(
                        f"shift_bps must contain integers; got {shift!r}"
                    )
        return v


class IRSDirectScenarioResponse(BaseModel):
    """Response body from ``POST /risk/scenario/direct``."""

    request_id: str
    instrument_type: str = "irs"
    currency: Optional[str] = None
    status: str
    scenario_npv: Dict[str, float]
    base_npv: float
    curve_source: str
    assumptions: List[str]
    warnings: List[str]


class ScenarioRequest(BaseModel):
    """
    Request body for ``POST /risk/scenario``.

    Mirrors the shape of :class:`LadderRequest` with ``shift_bps`` in place
    of ``bucket_years``.  Negative, zero, and positive shifts are all valid.
    """

    request_id: Optional[str] = None
    extracted_fields: Dict[str, Any]
    curve_inputs: Optional[CurveInputs] = None
    shift_bps: Optional[List[int]] = None


class ScenarioResponse(BaseModel):
    """
    Response body from ``POST /risk/scenario``.

    Attributes
    ----------
    request_id : str
        Echo of the caller-supplied request_id or a generated UUID.
    instrument_type : str | None
        Instrument type from extracted_fields (e.g. ``"irs"``).
    currency : str | None
        Currency from extracted_fields (e.g. ``"ZAR"``).
    status : str
        ``"indicative"`` for a successfully priced trade; ``"unsupported"``
        when the trade cannot be priced (see *warnings*).
    scenario_npv : dict[str, float]
        NPV of *swap* under each requested parallel curve shift.
        Keys are ``"{shift_bps}bp"`` (e.g. ``"-200bp"``, ``"0bp"``,
        ``"200bp"``).  Empty dict when status is ``"unsupported"``.
    base_npv : float
        NPV of *swap* on the unshifted curve (shift = 0 bp).  Equals zero
        when status is ``"unsupported"``.
    assumptions : list[str]
        Descriptions of pricing assumptions applied.
    warnings : list[str]
        Reasons why pricing could not be completed (non-empty when
        status is ``"unsupported"``).
    """

    request_id: str
    instrument_type: Optional[str] = None
    currency: Optional[str] = None
    status: str
    scenario_npv: Dict[str, float]
    base_npv: float
    assumptions: List[str]
    warnings: List[str]


# ---------------------------------------------------------------------------
# Bond risk schemas
# ---------------------------------------------------------------------------

from datetime import date as _date  # noqa: E402 (local import to avoid circular)

from app.schemas.price import (  # noqa: E402 (already imported above for CurveInputs)
    BondDayCount,
    _SUPPORTED_BOND_FREQUENCIES,
    _SUPPORTED_INSTRUMENT_DAY_COUNTS,
)
from pydantic import field_validator  # noqa: F811 (already imported)


class BondRiskRequest(BaseModel):
    """
    Request body for ``POST /risk/bond``.

    Identical field set to :class:`~app.schemas.price.BondPricingRequest`;
    the endpoint computes DV01 and modified duration rather than just the
    price.
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
            _date.fromisoformat(v)
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


class BondRiskResponse(BaseModel):
    """Response body from ``POST /risk/bond``."""

    request_id: str
    instrument_type: str = "bond"
    status: str
    dirty_price: float
    dv01: float
    modified_duration: float
    macaulay_duration: float
    convexity: float
    assumptions: List[str]
    warnings: List[str]
