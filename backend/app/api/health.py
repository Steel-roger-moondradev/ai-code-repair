"""Health and service metadata endpoints."""

from fastapi import APIRouter


router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Report whether the API process is available."""

    return {"status": "ok"}


@router.get("/")
def service_metadata() -> dict[str, str]:
    """Return non-sensitive service metadata."""

    return {"service": "PatchPilot", "version": "0.1.0"}
