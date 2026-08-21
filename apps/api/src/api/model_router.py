"""Resolves job -> model, effort and provider client from config.

Call sites never name a model and never branch on `MODEL_PROVIDER`. See
docs/ARCHITECTURE.md's model routing table and docs/COST.md.

**Bedrock, measured 2026-08-20** rather than assumed, because the first real call in this
project's history is what found it:

- The newer `AnthropicBedrockMantle` client is what the Anthropic SDK recommends for new
  code, and it answered `404 the model does not exist` for every id this account can
  reach. The working path is the classic `AnthropicBedrock` (InvokeModel) client.
- Bedrock ids for current models are **cross-region inference profiles** — `us.` prefixed,
  dated, versioned (`us.anthropic.claude-sonnet-4-6`). The undecorated ids this repo
  shipped in `.env.example` since Phase 3 (`anthropic.claude-opus-5`) fail two different
  ways: `404 does not exist`, or `on-demand throughput isn't supported, retry with an
  inference profile`.

Both are configuration, not code, so the resolver did not change — but the defaults did,
and the note stays because the next person to see a 404 here will otherwise re-derive it.
"""

from __future__ import annotations

from typing import Literal

from anthropic import Anthropic, AnthropicBedrock

from api.pricing import normalise
from api.settings import Settings, get_settings

Job = Literal["session_planning", "interviewing", "grading", "classification"]

# docs/COST.md: effort is tuned per job — "grading high, utility classification low".
# Interviewing sits between: it is the hot loop, and its output is dialogue rather than a
# judgement that compounds into mastery.
EFFORT_FOR_JOB: dict[Job, str] = {
    "session_planning": "high",
    "interviewing": "medium",
    "grading": "high",
    "classification": "low",
}

# `output_config.effort` is rejected by models older than the 4.6 family. Model ids are
# configuration, so this is a guard rather than a constant — keyed on the family
# `api.pricing.normalise` produces, so an inference-profile id matches too.
EFFORT_CAPABLE_FAMILIES = frozenset(
    {
        "claude-fable-5",
        "claude-opus-5",
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-sonnet-5",
        "claude-sonnet-4-6",
    }
)


class ModelRouter:
    """Job in, model out. Constructed per call site; holds no connection of its own."""

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

    def effort_for(self, job: Job) -> str | None:
        """The effort for a job, or None when the configured model would reject it.

        Silently dropping an unsupported parameter is usually the wrong instinct — here it
        is the right one, because the alternative is a 400 that makes an older model
        unusable for a reason unrelated to what the caller asked for."""
        if normalise(self.model_for(job)) not in EFFORT_CAPABLE_FAMILIES:
            return None
        return EFFORT_FOR_JOB[job]

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
