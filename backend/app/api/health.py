from fastapi import APIRouter, Request

from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthResponse)
def health_check(request: Request) -> HealthResponse:
    return HealthResponse(status="ok", version=request.app.version)
