"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.github import router as github_router
from app.api.workflows import router as workflows_router


app = FastAPI(title="PatchPilot", version="0.1.0")
app.include_router(health_router)
app.include_router(github_router)
app.include_router(workflows_router)
