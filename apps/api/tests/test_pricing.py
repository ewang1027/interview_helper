"""The rate table, and the id decoration it has to see through.

`llm_calls.cost_usd` is computed once and stored, so an error here is not a display bug —
it is a wrong number in a ledger that is supposed to be reconcilable against a bill.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from api.pricing import RATES, cost_of, is_priced, normalise, rate_for

BEFORE_INTRO_ENDS = datetime(2026, 8, 20, tzinfo=UTC)
AFTER_INTRO_ENDS = datetime(2026, 9, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    ("model", "family"),
    [
        ("claude-opus-5", "claude-opus-5"),
        ("anthropic.claude-opus-5", "claude-opus-5"),
        ("us.anthropic.claude-sonnet-4-6", "claude-sonnet-4-6"),
        ("us.anthropic.claude-haiku-4-5-20251001-v1:0", "claude-haiku-4-5"),
        ("anthropic.claude-sonnet-4-5-20250929-v1:0", "claude-sonnet-4-5"),
        ("eu.anthropic.claude-opus-4-8", "claude-opus-4-8"),
    ],
)
def test_provider_decoration_does_not_change_the_price(model, family):
    """A Bedrock inference-profile id carries a region prefix, a provider prefix, a date and
    a version. None of them are a different model."""
    assert normalise(model) == family
    assert is_priced(model)


def test_every_family_in_the_table_normalises_to_itself():
    """Guards the table against an entry a lookup could never reach."""
    assert all(normalise(family) == family for family in RATES)


def test_a_million_in_and_out_is_the_listed_rate():
    assert cost_of("claude-opus-5", input_tokens=1_000_000, output_tokens=1_000_000) == 30.0
    assert cost_of("claude-haiku-4-5", input_tokens=1_000_000, output_tokens=0) == 1.0


def test_cache_reads_are_a_tenth_and_writes_a_quarter_more():
    """The read discount is the entire reason docs/COST.md tracks cache columns."""
    read = cost_of("claude-opus-5", input_tokens=0, output_tokens=0, cache_read_tokens=1_000_000)
    write = cost_of("claude-opus-5", input_tokens=0, output_tokens=0, cache_write_tokens=1_000_000)
    assert read == pytest.approx(0.5)
    assert write == pytest.approx(6.25)


def test_sonnet_5_intro_pricing_expires():
    """Encoded rather than ignored: the window is open as this lands, and list price would
    be 50% out on every Sonnet call until it closes."""
    assert rate_for("claude-sonnet-5", when=BEFORE_INTRO_ENDS) == pytest.approx(
        rate_for("claude-sonnet-5", when=BEFORE_INTRO_ENDS)
    )
    intro = rate_for("claude-sonnet-5", when=BEFORE_INTRO_ENDS)
    listed = rate_for("claude-sonnet-5", when=AFTER_INTRO_ENDS)
    assert intro is not None and listed is not None
    assert (intro.input_usd, intro.output_usd) == (2.0, 10.0)
    assert (listed.input_usd, listed.output_usd) == (3.0, 15.0)


def test_an_unknown_model_is_recorded_at_zero_rather_than_guessed(caplog):
    """Zero and a warning, not an exception: the call already happened and the money is
    already spent, so refusing to price it would lose the token counts too."""
    assert not is_priced("anthropic.claude-imaginary-9")
    with caplog.at_level("WARNING"):
        assert cost_of("anthropic.claude-imaginary-9", input_tokens=1000, output_tokens=1000) == 0.0
    assert "no rate" in caplog.text
