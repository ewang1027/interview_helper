"""Every model call in this project goes through here.

Three things happen around one `messages.create`, and none of them are optional:

1. **The budget is checked first** (docs/COST.md's hard limits). Over the session or the
   day ceiling, the call is *refused* — not downgraded to a cheaper model, not truncated.
   A session that stops and says why is recoverable; one that quietly degrades produces
   bad evidence, and bad evidence corrupts mastery permanently.
2. **The call is made** with the model, effort and cache shape the job asks for.
3. **The ledger row is written**, in its own transaction, before the caller sees anything.
   Money was spent; whether the caller's work then succeeds is a separate question, and a
   rollback that erases the record of spend is how a bill becomes unexplainable.

The cache shape is the part that is easy to get wrong and expensive to leave wrong. Render
order is `tools` → `system` → `messages`, and a prefix match means one changed byte
anywhere before the breakpoint re-bills the whole prefix. So the frozen system prompt goes
in a block carrying `cache_control`, and everything volatile goes in `messages`, after it.
**Automatic (top-level) `cache_control` is not available on Bedrock**, which is the default
provider here, so the breakpoint is placed by hand.

What is not here: streaming (the SSE stream is a later slice), tool loops (the interviewer
owns that), and retries beyond the SDK's own — it already retries 429s and 5xx twice.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import anthropic
from sqlmodel import Session, col, func, select

from api.db import get_engine
from api.errors import budget_exceeded, provider_rate_limited, unavailable
from api.model_router import Job, ModelRouter
from api.models import LlmCall
from api.pricing import cost_of
from api.settings import Settings, get_settings

logger = logging.getLogger(__name__)

# Non-streaming, so this stays under the SDK's HTTP timeout. An interviewer turn that needs
# more than this is a design problem, not a limit problem.
DEFAULT_MAX_TOKENS = 4096


class MessagesClient(Protocol):
    """What this module needs from an Anthropic client — small enough that a test can
    implement it without a network, and typed so that a fake cannot drift from the real
    call signature unnoticed."""

    @property
    def messages(self) -> Any: ...


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int

    @property
    def total(self) -> int:
        """What a budget counts. Cache reads are cheap, not free, and they are still
        context the model processed."""
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
        )


@dataclass(frozen=True)
class Completion:
    """One call's result, plus what it cost."""

    text: str
    stop_reason: str | None
    content: list[Any]
    model: str
    usage: Usage
    cost_usd: float
    latency_ms: int
    call_id: str


def usage_of(response: Any) -> Usage:
    """Pull the four token counts off a response, defaulting anything absent to zero.

    Defensive because these fields differ by provider and SDK version, and a ledger that
    raises on a missing counter records nothing at all — the worst outcome available."""
    raw = getattr(response, "usage", None)
    return Usage(
        input_tokens=int(getattr(raw, "input_tokens", 0) or 0),
        output_tokens=int(getattr(raw, "output_tokens", 0) or 0),
        cache_read_tokens=int(getattr(raw, "cache_read_input_tokens", 0) or 0),
        cache_write_tokens=int(getattr(raw, "cache_creation_input_tokens", 0) or 0),
    )


def text_of(response: Any) -> str:
    """The text blocks, joined. Thinking and tool_use blocks are not text and are skipped;
    a caller that needs them reads `Completion.content`."""
    return "".join(
        block.text
        for block in getattr(response, "content", [])
        if getattr(block, "type", None) == "text"
    )


def cached_system(prompt: str) -> list[dict[str, Any]]:
    """A system prompt as one cacheable block.

    The breakpoint goes here and nowhere else: everything above it must be byte-identical
    across calls for the cache to hit, and a system prompt built from the mode and the item
    is the largest thing in this system that qualifies."""
    return [{"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}]


# --- Budgets -----------------------------------------------------------------------------


def tokens_spent(
    db: Session, *, session_id: str | None = None, since: datetime | None = None
) -> int:
    """Total tokens on the ledger, optionally for one session or since a moment."""
    query = select(
        func.coalesce(
            func.sum(
                LlmCall.input_tokens
                + LlmCall.output_tokens
                + LlmCall.cache_read_tokens
                + LlmCall.cache_write_tokens
            ),
            0,
        )
    )
    if session_id is not None:
        query = query.where(LlmCall.session_id == session_id)
    if since is not None:
        query = query.where(col(LlmCall.created_at) >= since)
    return int(db.exec(query).one())


def start_of_day(now: datetime | None = None) -> datetime:
    """The daily budget resets at UTC midnight. A rolling 24-hour window would be kinder to
    a late-night session and impossible to reason about from a bill."""
    moment = now or datetime.now(UTC)
    return moment.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def budget_status(db: Session, *, session_id: str | None, settings: Settings) -> dict[str, Any]:
    """What `GET /costs/budget` reports, and what the check below refuses on."""
    day_spent = tokens_spent(db, since=start_of_day())
    session_spent = tokens_spent(db, session_id=session_id) if session_id else 0
    return {
        "session": {
            "id": session_id,
            "spent": session_spent,
            "limit": settings.max_tokens_per_session,
            "remaining": max(0, settings.max_tokens_per_session - session_spent),
        },
        "day": {
            "start": start_of_day().isoformat(),
            "spent": day_spent,
            "limit": settings.max_tokens_per_day,
            "remaining": max(0, settings.max_tokens_per_day - day_spent),
        },
    }


def enforce_budget(db: Session, *, session_id: str | None, settings: Settings) -> None:
    """Refuse the call if a ceiling is already reached.

    The check is "already spent", not "would this call fit": the input size is not known
    before the call and asking the provider would itself be a call. The consequence is
    honest and bounded — the last call before a refusal can overshoot the ceiling by at
    most its own `max_tokens`, and the next one is refused.
    """
    status = budget_status(db, session_id=session_id, settings=settings)
    if status["day"]["remaining"] <= 0:
        raise budget_exceeded(
            f"The daily budget of {settings.max_tokens_per_day} tokens is spent "
            f"({status['day']['spent']} used since {status['day']['start']}).",
            scope="day",
            **{"consumed": status["day"]["spent"], "limit": settings.max_tokens_per_day},
        )
    if session_id and status["session"]["remaining"] <= 0:
        raise budget_exceeded(
            f"This session has spent its budget of {settings.max_tokens_per_session} tokens "
            f"({status['session']['spent']} used).",
            scope="session",
            **{"consumed": status["session"]["spent"], "limit": settings.max_tokens_per_session},
        )


# --- The call ------------------------------------------------------------------------------


def complete(
    *,
    job: Job,
    messages: list[dict[str, Any]],
    system: str | list[dict[str, Any]] | None = None,
    tools: list[dict[str, Any]] | None = None,
    session_id: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    client: MessagesClient | None = None,
    settings: Settings | None = None,
    router: ModelRouter | None = None,
) -> Completion:
    """One model call: budget-checked, made, and recorded."""
    config = settings or get_settings()
    routing = router or ModelRouter(config)
    model = routing.model_for(job)

    with Session(get_engine()) as db:
        enforce_budget(db, session_id=session_id, settings=config)

    request: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system is not None:
        request["system"] = cached_system(system) if isinstance(system, str) else system
    if tools:
        request["tools"] = tools
    effort = routing.effort_for(job)
    if effort is not None:
        request["output_config"] = {"effort": effort}

    started = time.monotonic()
    try:
        response = (client or routing.client()).messages.create(**request)
    except anthropic.RateLimitError as exc:
        raise provider_rate_limited(
            f"{config.model_provider} rate limited the request: {exc}"
        ) from exc
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
        # No ledger row: a call that never produced usage never cost anything, and inventing
        # a zero-token row would make the ledger's call count wrong.
        raise unavailable(f"The model provider did not answer: {exc}") from exc
    latency_ms = int((time.monotonic() - started) * 1000)

    usage = usage_of(response)
    cost = cost_of(
        model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
    )
    call_id = record_call(
        job=job,
        model=model,
        provider=config.model_provider,
        usage=usage,
        cost_usd=cost,
        latency_ms=latency_ms,
        session_id=session_id,
    )
    return Completion(
        text=text_of(response),
        stop_reason=getattr(response, "stop_reason", None),
        content=list(getattr(response, "content", [])),
        model=model,
        usage=usage,
        cost_usd=cost,
        latency_ms=latency_ms,
        call_id=call_id,
    )


def record_call(
    *,
    job: str,
    model: str,
    provider: str,
    usage: Usage,
    cost_usd: float,
    latency_ms: int,
    session_id: str | None,
) -> str:
    """Append to the ledger, in its own transaction.

    Its own, deliberately: the spend happened whatever the caller does next, and a caller
    that raises after the call would otherwise roll back the only record of it."""
    row = LlmCall(
        session_id=session_id,
        job=job,
        model=model,
        provider=provider,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
    )
    with Session(get_engine()) as db:
        db.add(row)
        db.commit()
        db.refresh(row)
    return row.id


def rollup(db: Session, *, days: int = 7) -> dict[str, Any]:
    """What `GET /costs` reports: totals, and the same numbers split the two ways that
    change a decision — by job (what is expensive) and by model (what it is routed to)."""
    since = start_of_day() - timedelta(days=days - 1)
    # Two queries rather than one: `select()`'s typed overloads stop at four columns, and
    # a `# type: ignore` on an aggregate is how a wrong column goes unnoticed later.
    calls, cost = db.exec(
        select(func.count(), func.coalesce(func.sum(LlmCall.cost_usd), 0.0)).where(
            col(LlmCall.created_at) >= since
        )
    ).one()
    tokens_in, tokens_out, cache_read = db.exec(
        select(
            func.coalesce(func.sum(LlmCall.input_tokens), 0),
            func.coalesce(func.sum(LlmCall.output_tokens), 0),
            func.coalesce(func.sum(LlmCall.cache_read_tokens), 0),
        ).where(col(LlmCall.created_at) >= since)
    ).one()
    by_job = db.exec(
        select(LlmCall.job, func.count(), func.coalesce(func.sum(LlmCall.cost_usd), 0.0))
        .where(col(LlmCall.created_at) >= since)
        .group_by(col(LlmCall.job))
        .order_by(col(LlmCall.job))
    ).all()
    by_model = db.exec(
        select(LlmCall.model, func.count(), func.coalesce(func.sum(LlmCall.cost_usd), 0.0))
        .where(col(LlmCall.created_at) >= since)
        .group_by(col(LlmCall.model))
        .order_by(col(LlmCall.model))
    ).all()
    return {
        "since": since.isoformat(),
        "calls": int(calls),
        "cost_usd": round(float(cost), 6),
        "input_tokens": int(tokens_in),
        "output_tokens": int(tokens_out),
        "cache_read_tokens": int(cache_read),
        "by_job": [
            {"job": j, "calls": int(c), "cost_usd": round(float(s), 6)} for j, c, s in by_job
        ],
        "by_model": [
            {"model": m, "calls": int(c), "cost_usd": round(float(s), 6)} for m, c, s in by_model
        ],
    }
