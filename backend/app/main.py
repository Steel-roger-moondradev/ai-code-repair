"""FastAPI application entry point."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.github import router as github_router
from app.api.workflows import router as workflows_router
from app.config import get_settings


app = FastAPI(title="PatchPilot", version="0.1.0")

origins = [
    origin.strip()
    for origin in get_settings().cors_allowed_origins.split(",")
    if origin.strip()
]
if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Request-ID"],
    )


@app.middleware("http")
async def enforce_request_limits(request: Request, call_next):
    """Reject oversized requests before workflow execution or persistence."""

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            size = int(content_length)
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "invalid content length"})
        from app.config import get_settings

        if size > get_settings().max_request_body_bytes:
            return JSONResponse(status_code=413, content={"detail": "request body too large"})
    return await call_next(request)
app.include_router(health_router)
app.include_router(github_router)
app.include_router(workflows_router)
