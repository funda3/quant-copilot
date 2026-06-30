from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.schemas.extract import ExtractRequest, ExtractResponse, ExtractStatus
from app.services.extractor import extract_fields

router = APIRouter(tags=["extract"])


@router.post("/extract", response_model=ExtractResponse)
def extract(request: ExtractRequest) -> ExtractResponse:
    """
    Accept a free-text pricing prompt and return prompt-driven extracted fields.

    Field extraction is rule-based. An LLM-based parser will replace this
    in a later sprint.
    """
    extracted, missing, status = extract_fields(request.prompt)
    return ExtractResponse(
        request_id=str(uuid.uuid4()),
        raw_prompt=request.prompt,
        extracted_fields=extracted,
        missing_fields=missing,
        status=ExtractStatus(status),
    )
