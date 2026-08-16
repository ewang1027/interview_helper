import pytest

from api.model_router import ModelRouter
from api.settings import Settings


def _settings(**overrides):
    base = {
        "model_planner": "planner-model",
        "model_interviewer": "interviewer-model",
        "model_grader": "grader-model",
        "model_utility": "utility-model",
    }
    return Settings(**{**base, **overrides})


def test_each_job_resolves_to_its_configured_model():
    router = ModelRouter(_settings())
    assert router.model_for("session_planning") == "planner-model"
    assert router.model_for("interviewing") == "interviewer-model"
    assert router.model_for("grading") == "grader-model"
    # docs/ARCHITECTURE.md routes classification/extraction to the utility model —
    # this is the row docs/PRACTICE_LOG.md's problem classification rides on.
    assert router.model_for("classification") == "utility-model"


def test_anthropic_provider_without_a_key_refuses_rather_than_falling_back():
    """docs/COST.md: the system refuses work rather than silently degrading."""
    router = ModelRouter(_settings(model_provider="anthropic", anthropic_api_key=None))
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        router.client()
