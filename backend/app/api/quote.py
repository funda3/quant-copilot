from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.schemas.quote import QuoteRequest, QuoteResponse
from app.services.extractor import extract_fields
from app.services.pricer import compute_price

router = APIRouter(tags=["quote"])


@router.post("/quote", response_model=QuoteResponse)
def quote(request: QuoteRequest) -> QuoteResponse:
    """
    Accept a natural-language trading prompt and return either:
    - a needs-clarification response (no pricing attempted), or
    - an indicative or unsupported pricing result.

    A single request_id is generated here and flows through extraction
    and pricing so all service calls share the same correlation ID.
    """
    request_id = str(uuid.uuid4())

    extracted_fields, missing_fields, extraction_status = extract_fields(request.prompt)

    if extraction_status == "needs_clarification":
        return QuoteResponse(
            request_id=request_id,
            raw_prompt=request.prompt,
            extracted_fields=extracted_fields,
            missing_fields=missing_fields,
            extraction_status=extraction_status,
            pricing_attempted=False,
            price_status=None,
            price=0.0,
            pv01=0.0,
            assumptions=[],
            warnings=[
                f"Cannot price yet. Missing fields: {', '.join(missing_fields)}. "
                "Please provide the missing information."
            ],
        )

    # Extraction is ready — attempt pricing.
    # Non-blocking fields (e.g. effective_date) are intentionally excluded from
    # the ready-path response; they would be misleading alongside a priced result.
    pricing_result = compute_price(extracted_fields, request_id=request_id, curve_inputs=request.curve_inputs)

    return QuoteResponse(
        request_id=request_id,
        raw_prompt=request.prompt,
        extracted_fields=extracted_fields,
        missing_fields=[],
        extraction_status=extraction_status,
        pricing_attempted=True,
        price_status=pricing_result["status"],
        price=pricing_result["price"],
        pv01=pricing_result["pv01"],
        assumptions=pricing_result["assumptions"],
        warnings=pricing_result["warnings"],
    )
