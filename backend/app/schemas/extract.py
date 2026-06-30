from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List

from pydantic import BaseModel


class ExtractStatus(str, Enum):
    needs_clarification = "needs_clarification"
    ready = "ready"


class ExtractRequest(BaseModel):
    prompt: str


class ExtractResponse(BaseModel):
    request_id: str
    raw_prompt: str
    extracted_fields: Dict[str, Any]
    missing_fields: List[str]
    status: ExtractStatus
