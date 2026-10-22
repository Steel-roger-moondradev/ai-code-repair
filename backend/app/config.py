"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated settings for the PatchPilot backend."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    github_token: str | None = None
    groq_api_key: str | None = None
    groq_model: str | None = None
    repository_root: str = "data/repositories"
    workspace_root: str = "data/workspaces"
    database_url: str = "sqlite:///./data/patchpilot.db"
    request_timeout_seconds: int = Field(default=20, gt=0)
    llm_timeout_seconds: int = Field(default=45, gt=0)
    max_repair_attempts: int = Field(default=2, gt=0)
    max_repository_files: int = Field(default=5000, gt=0)
    max_file_bytes: int = Field(default=200000, gt=0)
    max_context_chars: int = Field(default=30000, gt=0)
    max_patch_files: int = Field(default=10, gt=0)
    max_patch_bytes: int = Field(default=200000, gt=0)
    sandbox_timeout_seconds: int = Field(default=120, gt=0)
    max_request_body_bytes: int = Field(default=65536, gt=0)

    @field_validator("app_env", "repository_root", "workspace_root", "database_url")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        """Reject blank values for settings that identify runtime resources."""

        if not value.strip():
            raise ValueError("setting must not be empty")
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide validated settings instance."""

    return Settings()
