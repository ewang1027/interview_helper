"""What a model call cost, in dollars, at the moment it was made.

`llm_calls.cost_usd` is computed here and stored, never recomputed on read: rates change,
and a ledger that silently re-prices last month's calls is a ledger you cannot reconcile
against a bill.

**These are Anthropic first-party list rates**, and Bedrock is partner-operated and priced
separately (https://aws.amazon.com/bedrock/pricing/). That used to make the number here an
estimate. Checked 2026-08-20 against Bedrock's own rate card for the model this project
runs — `aws bedrock list-foundation-model-agreement-offers --model-id
anthropic.claude-sonnet-4-6` — the two agree exactly:

    input $3.00/M · output $15.00/M · cache read $0.30/M · cache write $3.75/M (5m)

which also confirms the two multipliers below: a read is a tenth of input and a 5-minute
write is a quarter more. The one-hour write is 2x input, not 1.25x — this module always
requests the 5-minute default, and that is the reason it should keep doing so silently
rather than growing a TTL parameter nobody sets.

Still an estimate for any model whose Bedrock card has not been read, and the bill is
authoritative either way. It is worth computing regardless: the shape of the spend — which
job, which model, how much of it was cache — is what docs/COST.md's "measure before
optimizing" needs, and that shape is the same whoever bills it.

Rates last checked 2026-08-20 against the model table in the `claude-api` skill.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime

logger = logging.getLogger(__name__)

# Cache multipliers on the input rate, confirmed against Bedrock's published rate card
# rather than rounded from documentation: a 5-minute write is 1.25x, a read 0.1x. The read
# discount is the entire reason docs/COST.md cares whether caching is working.
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.1

# Server-side web search, billed per search at $10 per 1,000 — flat, not per model, and
# *on top of* the tokens the results consume. This is the only line here that is not a
# token rate, and it exists because docs/JOBS.md's research pass is the first call in this
# project to declare a server-side tool. Left out, a thirty-search research call would
# report roughly a third of what it cost against a $1 session ceiling.
WEB_SEARCH_USD = 0.01


@dataclass(frozen=True)
class Rate:
    """Dollars per million tokens."""

    input_usd: float
    output_usd: float


# Keyed by *family*, after `normalise` strips the region, provider and version decoration a
# Bedrock id carries. Anything not listed here is priced at zero and reported as unpriced
# rather than guessed at — see `cost_of`.
RATES: dict[str, Rate] = {
    "claude-fable-5": Rate(10.0, 50.0),
    "claude-opus-5": Rate(5.0, 25.0),
    "claude-opus-4-8": Rate(5.0, 25.0),
    "claude-opus-4-7": Rate(5.0, 25.0),
    "claude-opus-4-6": Rate(5.0, 25.0),
    "claude-sonnet-5": Rate(3.0, 15.0),
    "claude-sonnet-4-6": Rate(3.0, 15.0),
    "claude-sonnet-4-5": Rate(3.0, 15.0),
    "claude-haiku-4-5": Rate(1.0, 5.0),
}

# Sonnet 5 launched with introductory pricing. Encoded rather than ignored because the
# window is open as this lands: a ledger that reports list price today would be 50% out on
# every Sonnet call, which is precisely the error a cost ledger exists to prevent.
INTRO_RATES: dict[str, tuple[Rate, date]] = {
    "claude-sonnet-5": (Rate(2.0, 10.0), date(2026, 8, 31)),
}

# `us.anthropic.claude-haiku-4-5-20251001-v1:0` -> `claude-haiku-4-5`. Bedrock ids carry a
# cross-region inference-profile prefix, a provider prefix, and often a dated version; none
# of them change the price.
_GEO_PREFIX = re.compile(r"^(us|eu|apac|global)\.")
_PROVIDER_PREFIX = re.compile(r"^anthropic\.")
_VERSION_SUFFIX = re.compile(r"(-v\d+(:\d+)?)+$")
_DATE_SUFFIX = re.compile(r"-\d{8}$")


def normalise(model: str) -> str:
    """The rate-table key for a model id from any provider."""
    name = _GEO_PREFIX.sub("", model.strip())
    name = _PROVIDER_PREFIX.sub("", name)
    name = _VERSION_SUFFIX.sub("", name)
    return _DATE_SUFFIX.sub("", name)


def rate_for(model: str, *, when: datetime | None = None) -> Rate | None:
    """The rate in force for a model at a moment, or None if it is not in the table."""
    family = normalise(model)
    intro = INTRO_RATES.get(family)
    if intro is not None:
        rate, until = intro
        moment = when or datetime.now(UTC)
        if moment.date() <= until:
            return rate
    return RATES.get(family)


def cost_of(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    web_search_requests: int = 0,
    when: datetime | None = None,
) -> float:
    """Dollars for one call. Zero for a model with no rate, and a warning saying so.

    Zero rather than a raised exception on purpose: the call has already been made and the
    money already spent, so refusing to write the ledger row would lose the token counts
    too. `make cost-report` counts unpriced calls separately, so a zero here shows up as a
    missing rate rather than as free work.

    Web searches are added even when the model is unpriced: that charge is flat and known
    whatever the model was, and dropping it would be a second error on top of the missing
    rate rather than a conservative one.
    """
    searches = web_search_requests * WEB_SEARCH_USD
    rate = rate_for(model, when=when)
    if rate is None:
        logger.warning(
            "no rate for model %r (%r); recording the call at $%.4f (web search only)",
            model,
            normalise(model),
            searches,
        )
        return searches
    per_token_in = rate.input_usd / 1_000_000
    return (
        input_tokens * per_token_in
        + output_tokens * rate.output_usd / 1_000_000
        + cache_read_tokens * per_token_in * CACHE_READ_MULTIPLIER
        + cache_write_tokens * per_token_in * CACHE_WRITE_MULTIPLIER
        + searches
    )


def is_priced(model: str) -> bool:
    return rate_for(model) is not None
