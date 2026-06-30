from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.schemas.price import CurveInputs


class QuoteRequest(BaseModel):
    prompt: str
    curve_inputs: Optional[CurveInputs] = None


class QuoteResponse(BaseModel):
    request_id: str
    raw_prompt: str
    extracted_fields: Dict[str, Any]
    missing_fields: List[str]
    extraction_status: str          # "ready" | "needs_clarification"
    pricing_attempted: bool
    price_status: Optional[str]     # "indicative" | "unsupported" | null
    price: float
    pv01: float
    assumptions: List[str]
    warnings: List[str]
