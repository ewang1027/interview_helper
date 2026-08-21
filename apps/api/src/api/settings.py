"""Runtime configuration, read once from the environment.

Mirrors `.env.example` exactly — every var there has a field here. Nothing in the
app should call `os.environ` directly; import `get_settings()` instead so tests can
override via `Settings(...)` construction.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ModelProvider = Literal["bedrock", "anthropic"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://interview:interview@localhost:5432/interview_helper"

    model_provider: ModelProvider = "bedrock"
    aws_region: str = "us-east-2"

    # Measured 2026-08-20, not assumed. Bedrock ids for current models are cross-region
    # inference profiles (`us.` prefixed); the undecorated ids shipped here since Phase 3
    # never worked. These four default to the one model this account can reach today —
    # docs/ARCHITECTURE.md's routing table (Opus 5 planning and grading, Sonnet 5
    # interviewing, Haiku 4.5 utility) is the target, and docs/COST.md says what to enable
    # in the Bedrock console to restore it.
    model_planner: str = "us.anthropic.claude-sonnet-4-6"
    model_interviewer: str = "us.anthropic.claude-sonnet-4-6"
    model_grader: str = "us.anthropic.claude-sonnet-4-6"
    model_utility: str = "us.anthropic.claude-sonnet-4-6"
    anthropic_api_key: str | None = None

    max_tokens_per_session: int = Field(default=400_000, gt=0)
    max_tokens_per_day: int = Field(default=3_000_000, gt=0)

    # Auth (docs/API.md). No usable defaults on purpose: a session secret with a
    # fallback value is a session secret every clone of this repo already knows, and an
    # allowed account with a default is a deployment anyone can log in to.
    session_secret: str | None = None
    github_client_id: str | None = None
    github_client_secret: str | None = None
    github_allowed_id: int | None = None
    github_redirect_uri: str = "http://localhost:8000/auth/callback"
    cookie_secure: bool = True

    executor_url: str = "http://localhost:8081"
    executor_wall_ms: int = Field(default=5_000, gt=0)
    executor_memory_mb: int = Field(default=256, gt=0)

    vapi_api_key: str | None = None
    vapi_webhook_secret: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
