"""Resolves job -> model/provider from config. Call sites never name a model.

See docs/ARCHITECTURE.md's Model routing table and docs/COST.md. The provider
client itself (Bedrock vs Anthropic direct) is also resolved here so a call site
never branches on `MODEL_PROVIDER` either.
"""

from __future__ import annotations

from typing import Literal

from anthropic import Anthropic, AnthropicBedrock

from api.settings import Settings, get_settings

Job = Literal["session_planning", "interviewing", "grading", "classification"]


class ModelRouter:
    """Not yet wired to any call site — Phase 3 infra lands the resolver and the
    client factory; the interviewer/grader/planner call sites land with sessions
    (docs/API.md), which are a later slice of Phase 3."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def model_for(self, job: Job) -> str:
        s = self._settings
        return {
            "session_planning": s.model_planner,
            "interviewing": s.model_interviewer,
            "grading": s.model_grader,
            "classification": s.model_utility,
        }[job]

    def client(self) -> Anthropic | AnthropicBedrock:
        """One client per provider config, not per call site. Bedrock is the
        credit-funded default; Anthropic direct is the escape hatch and requires
        `ANTHROPIC_API_KEY` (docs/COST.md's "where the money goes")."""
        s = self._settings
        if s.model_provider == "bedrock":
            return AnthropicBedrock(aws_region=s.aws_region)
        if not s.anthropic_api_key:
            raise RuntimeError("MODEL_PROVIDER=anthropic requires ANTHROPIC_API_KEY to be set")
        return Anthropic(api_key=s.anthropic_api_key)
