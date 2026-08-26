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
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import anthropic
from sqlalchemy import case
from sqlmodel import Session, col, func, select

from api import events as event_bus
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
    # Server-side web searches, which are billed per search rather than per token. Not in
    # `total` below for exactly that reason: `total` is what the *token* ceilings count,
    # and folding a search into it would mean one number standing for two different units.
    # The dollar ceilings see it, because `api.pricing.cost_of` prices it.
    web_search_requests: int = 0

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
        # `usage.server_tool_use.web_search_requests`, absent on every response that
        # declared no server tool — which is why it is read as defensively as the rest.
        web_search_requests=int(
            getattr(getattr(raw, "server_tool_use", None), "web_search_requests", 0) or 0
        ),
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


# A reservation older than this is treated as abandoned — the process holding it died
# between writing the row and settling it. Generous, because releasing a live reservation
# re-opens the race it exists to close, and the cost of holding a dead one is that the
# ceiling is briefly stricter than it needs to be. That is the right direction to fail.
RESERVATION_TTL = timedelta(minutes=15)

# What a call that never reached the provider consumed.
_NO_USAGE = Usage(input_tokens=0, output_tokens=0, cache_read_tokens=0, cache_write_tokens=0)


def _spend_expression() -> Any:
    """What a row contributes to spend.

    An in-flight row contributes its *reservation*: that is the whole point of writing it
    before the call. A settled or failed row contributes what the provider actually
    reported, which for a failed row may be partial and may be zero."""
    actual = (
        LlmCall.input_tokens
        + LlmCall.output_tokens
        + LlmCall.cache_read_tokens
        + LlmCall.cache_write_tokens
    )
    return func.sum(
        case(
            (
                (col(LlmCall.status) == "reserved")
                & (col(LlmCall.created_at) >= datetime.now(UTC) - RESERVATION_TTL),
                LlmCall.reserved_tokens,
            ),
            else_=actual,
        )
    )


def _money(amount: float) -> str:
    """Dollars, with enough precision to still be a number.

    `:.2f` reads "$0.00" for a ceiling of $0.001, which is what a refusal looked like the
    first time one was triggered against a deliberately tiny limit — a message saying a
    budget of nothing was spent, about a limit somebody had just set on purpose.
    """
    return f"${amount:.2f}" if amount >= 0.01 else f"${amount:.4f}"


def _usd_expression() -> Any:
    """What a row contributes to *spend in dollars*.

    The same shape as `_spend_expression` and for the same reason: an in-flight row
    contributes its reservation, a settled or failed row contributes what it really cost.
    Separate from the token version rather than derived from it, because tokens cannot be
    converted to dollars after the fact — output costs five times input and the row keeps
    only their sum.
    """
    return func.sum(
        case(
            (
                (col(LlmCall.status) == "reserved")
                & (col(LlmCall.created_at) >= datetime.now(UTC) - RESERVATION_TTL),
                LlmCall.reserved_usd,
            ),
            else_=LlmCall.cost_usd,
        )
    )


def usd_spent(
    db: Session, *, session_id: str | None = None, since: datetime | None = None
) -> float:
    """Dollars on the ledger, optionally for one session or since a moment.

    Counts calls in flight at their reservation, exactly as `tokens_spent` does — without
    that, concurrent calls each read the other's spend as zero, which is the finding that
    made the token ceiling not a ceiling.
    """
    query = select(func.coalesce(_usd_expression(), 0.0))
    if session_id is not None:
        query = query.where(LlmCall.session_id == session_id)
    if since is not None:
        query = query.where(col(LlmCall.created_at) >= since)
    return float(db.exec(query).one())


def start_of_month(now: datetime | None = None) -> datetime:
    """The monthly budget resets at UTC midnight on the first.

    A calendar month rather than a rolling thirty days, for the reason the day uses UTC
    midnight: a rolling window is kinder and impossible to reconcile against a bill.
    """
    moment = now or datetime.now(UTC)
    return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def tokens_spent(
    db: Session, *, session_id: str | None = None, since: datetime | None = None
) -> int:
    """Total tokens on the ledger, optionally for one session or since a moment.

    Counts calls **in flight** at their reservation. Without that, two calls overlapping
    in time both read the other's spend as zero, which is how a 1000-token daily ceiling
    was measured absorbing 8,000,000 tokens."""
    query = select(func.coalesce(_spend_expression(), 0))
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
    usd_day = usd_spent(db, since=start_of_day())
    usd_month = usd_spent(db, since=start_of_month())
    usd_session = usd_spent(db, session_id=session_id) if session_id else 0.0
    return {
        "session": {
            "id": session_id,
            "spent": session_spent,
            "limit": settings.max_tokens_per_session,
            "remaining": max(0, settings.max_tokens_per_session - session_spent),
            "spent_usd": round(usd_session, 6),
            "limit_usd": settings.max_usd_per_session,
            "remaining_usd": round(max(0.0, settings.max_usd_per_session - usd_session), 6),
        },
        "day": {
            "start": start_of_day().isoformat(),
            "spent": day_spent,
            "limit": settings.max_tokens_per_day,
            "remaining": max(0, settings.max_tokens_per_day - day_spent),
            "spent_usd": round(usd_day, 6),
            "limit_usd": settings.max_usd_per_day,
            "remaining_usd": round(max(0.0, settings.max_usd_per_day - usd_day), 6),
        },
        "month": {
            "start": start_of_month().isoformat(),
            "spent_usd": round(usd_month, 6),
            "limit_usd": settings.max_usd_per_month,
            "remaining_usd": round(max(0.0, settings.max_usd_per_month - usd_month), 6),
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

    # Dollars first. They are the ceiling that means something once the routing table
    # holds more than one model — 3,000,000 tokens is about $15 of Haiku input or $75 of
    # Opus 5 output, and which one depends on a line of `.env`. Checked before the token
    # limits so the refusal names the thing the operator actually set.
    for scope, human in (("month", "monthly"), ("day", "daily"), ("session", "session")):
        leg = status[scope]
        if scope == "session" and not session_id:
            continue
        if leg["remaining_usd"] <= 0:
            raise budget_exceeded(
                f"The {human} budget of {_money(leg['limit_usd'])} is spent "
                f"({_money(leg['spent_usd'])} used).",
                scope=scope,
                unit="usd",
                **{"consumed": leg["spent_usd"], "limit": leg["limit_usd"]},
            )

    if status["day"]["remaining"] <= 0:
        raise budget_exceeded(
            f"The daily budget of {settings.max_tokens_per_day} tokens is spent "
            f"({status['day']['spent']} used since {status['day']['start']}).",
            scope="day",
            unit="tokens",
            **{"consumed": status["day"]["spent"], "limit": settings.max_tokens_per_day},
        )
    if session_id and status["session"]["remaining"] <= 0:
        raise budget_exceeded(
            f"This session has spent its budget of {settings.max_tokens_per_session} tokens "
            f"({status['session']['spent']} used).",
            scope="session",
            unit="tokens",
            **{"consumed": status["session"]["spent"], "limit": settings.max_tokens_per_session},
        )


# The lock key. Any constant works — this serialises *all* reserve-and-check pairs, which
# is coarse and correct. The critical section holds no network call, only two aggregates
# and one insert, so contention is microseconds even though every model call passes here.
_BUDGET_LOCK_KEY = 0x1CE_B00C


def reserve(
    *,
    job: str,
    model: str,
    provider: str,
    session_id: str | None,
    max_tokens: int,
    estimated_input_tokens: int,
    settings: Settings,
) -> str:
    """Check the ceilings and claim room for this call, atomically.

    The check and the claim have to be one indivisible step. Splitting them is what made
    the ceiling not a ceiling: `enforce_budget` read the ledger in a transaction that
    closed before the provider was called, so every call overlapping in time read the same
    pre-spend total and every one of them proceeded. Measured at eight concurrent calls
    against a 1000-token daily limit: all eight allowed, 8,000,000 tokens spent.

    `pg_advisory_xact_lock` rather than `SELECT ... FOR UPDATE`: there is no single row
    that represents "today's spend" to lock, and the lock releases with the transaction
    whatever happens to the caller. It is held across two aggregates and one insert, never
    across the provider call — holding a database lock over a network round-trip is how a
    connection pool dies.
    """
    with Session(get_engine()) as db:
        db.exec(select(func.pg_advisory_xact_lock(_BUDGET_LOCK_KEY)))
        enforce_budget(db, session_id=session_id, settings=settings)
        row = LlmCall(
            session_id=session_id,
            job=job,
            model=model,
            provider=provider,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=0,
            status="reserved",
            # What this call may cost if it runs to its limit. The input side is an
            # estimate — the true count is only known once the provider answers — so this
            # is a bound with a soft edge, not an exact figure. It is the difference
            # between an overshoot of one call and an overshoot of every concurrent call.
            reserved_tokens=max_tokens + estimated_input_tokens,
            # The same reservation in dollars, priced at this call's own model and at its
            # worst case: every one of `max_tokens` billed at the output rate. A call
            # cannot cost more than this, which is what makes it safe to hold against a
            # ceiling before the provider has answered.
            reserved_usd=cost_of(
                model,
                input_tokens=estimated_input_tokens,
                output_tokens=max_tokens,
            ),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id


def estimate_input_tokens(
    messages: list[dict[str, Any]], system: str | list[dict[str, Any]] | None
) -> int:
    """A cheap upper-ish estimate of the prompt, for the reservation only.

    Four characters per token is the usual rule of thumb and is wrong in both directions;
    it does not need to be right, it needs to stop a reservation from being zero."""
    text = str(messages) + str(system or "")
    return len(text) // 4


def settle(call_id: str, *, usage: Usage, cost_usd: float, latency_ms: int, failed: bool) -> None:
    """Turn a reservation into a record of what actually happened.

    `failed=True` still records usage, because a call can fail *after* the provider has
    generated output — a stream that drops mid-flight has already handed the caller billed
    tokens. That case previously wrote no row at all, so the spend was invisible to both
    the ledger and the budget."""
    with Session(get_engine()) as db:
        row = db.get(LlmCall, call_id)
        if row is None:  # pragma: no cover - the reservation is written before the call
            return
        row.status = "failed" if failed else "settled"
        row.reserved_tokens = 0
        row.input_tokens = usage.input_tokens
        row.output_tokens = usage.output_tokens
        row.cache_read_tokens = usage.cache_read_tokens
        row.cache_write_tokens = usage.cache_write_tokens
        row.web_search_requests = usage.web_search_requests
        # The reservation is over; `cost_usd` below is what it really cost.
        row.reserved_usd = 0.0
        row.cost_usd = cost_usd
        row.latency_ms = latency_ms
        row.settled_at = datetime.now(UTC)
        db.add(row)
        db.commit()


# --- The call ------------------------------------------------------------------------------


def _request(
    *,
    model: str,
    max_tokens: int,
    messages: list[dict[str, Any]],
    system: str | list[dict[str, Any]] | None,
    tools: list[dict[str, Any]] | None,
    effort: str | None,
    output_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The request body, built the same way for a streamed and an unstreamed call.

    One builder because the cache prefix is `tools` then `system`: two builders is two
    chances for those to be assembled differently and for a switch between call styles to
    read as a cache miss on the bill."""
    request: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "messages": messages}
    if system is not None:
        request["system"] = cached_system(system) if isinstance(system, str) else system
    if tools:
        request["tools"] = tools
    output_config: dict[str, Any] = {}
    if effort is not None:
        output_config["effort"] = effort
    if output_schema is not None:
        # A validated object instead of prose to be parsed (docs/GRADING.md). The first text
        # block of the response is then guaranteed to be JSON matching the schema, which is
        # the difference between a grader and a regex over an essay.
        output_config["format"] = {"type": "json_schema", "schema": output_schema}
    if output_config:
        request["output_config"] = output_config
    return request


def complete(
    *,
    job: Job,
    messages: list[dict[str, Any]],
    system: str | list[dict[str, Any]] | None = None,
    tools: list[dict[str, Any]] | None = None,
    session_id: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    output_schema: dict[str, Any] | None = None,
    client: MessagesClient | None = None,
    settings: Settings | None = None,
    router: ModelRouter | None = None,
) -> Completion:
    """One model call: budget-checked, made, and recorded."""
    config = settings or get_settings()
    routing = router or ModelRouter(config)
    model = routing.model_for(job)

    call_id = reserve(
        job=job,
        model=model,
        provider=config.model_provider,
        session_id=session_id,
        max_tokens=max_tokens,
        estimated_input_tokens=estimate_input_tokens(messages, system),
        settings=config,
    )

    request = _request(
        model=model,
        max_tokens=max_tokens,
        messages=messages,
        system=system,
        tools=tools,
        effort=routing.effort_for(job),
        output_schema=output_schema,
    )
    started = time.monotonic()
    try:
        response = (client or routing.client()).messages.create(**request)
    except anthropic.RateLimitError as exc:
        settle(call_id, usage=_NO_USAGE, cost_usd=0.0, latency_ms=0, failed=True)
        raise provider_rate_limited(
            f"{config.model_provider} rate limited the request: {exc}"
        ) from exc
    except Exception as exc:
        # `Exception`, not the three `anthropic` classes this used to name. Two of them
        # let real failures through: `APIResponseValidationError` is a sibling of
        # `APIStatusError`, so a fully billed response the SDK could not validate escaped
        # as an unhandled 500, and a `botocore` credential error out of the Bedrock client
        # is not an `anthropic` exception at all — it reached the client as a text/plain
        # 500, outside the problem+json contract every route is supposed to keep.
        settle(call_id, usage=_NO_USAGE, cost_usd=0.0, latency_ms=0, failed=True)
        raise unavailable(f"The model provider did not answer: {exc}") from exc
    latency_ms = int((time.monotonic() - started) * 1000)

    return _record_and_wrap(
        response,
        job=job,
        model=model,
        config=config,
        session_id=session_id,
        latency_ms=latency_ms,
        call_id=call_id,
    )


def _record_and_wrap(
    response: Any,
    *,
    job: Job,
    model: str,
    config: Settings,
    session_id: str | None,
    latency_ms: int,
    call_id: str,
) -> Completion:
    """Everything that happens once the provider has answered, whichever way it was asked.

    Shared by `complete` and `stream` on purpose: the ledger row, its price and the budget
    warning are not features of one call style, and two copies of this is how a streamed
    call quietly stops being counted."""
    usage = usage_of(response)
    cost = cost_of(
        model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        web_search_requests=usage.web_search_requests,
    )
    settle(call_id, usage=usage, cost_usd=cost, latency_ms=latency_ms, failed=False)
    if session_id:
        _warn_if_close_to_a_ceiling(session_id, config)
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


def stream(
    *,
    job: Job,
    messages: list[dict[str, Any]],
    on_delta: Callable[[str], None],
    system: str | list[dict[str, Any]] | None = None,
    tools: list[dict[str, Any]] | None = None,
    session_id: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    client: MessagesClient | None = None,
    settings: Settings | None = None,
    router: ModelRouter | None = None,
) -> Completion:
    """Same call, delivered as it is generated. `on_delta` gets each chunk of text.

    Returns the same `Completion` as `complete`, built from the final message — so a caller
    that ignores `on_delta` behaves identically, and the ledger cannot tell the difference.
    That is deliberate: streaming is a delivery decision, and nothing downstream of a call
    should have to know which way it was made.

    `on_delta` is called from inside the request. It must be cheap and it must not raise —
    publishing to the in-process event bus is both. An exception there is caught and logged
    rather than allowed to abandon a call that is already being paid for.
    """
    config = settings or get_settings()
    routing = router or ModelRouter(config)
    model = routing.model_for(job)

    call_id = reserve(
        job=job,
        model=model,
        provider=config.model_provider,
        session_id=session_id,
        max_tokens=max_tokens,
        estimated_input_tokens=estimate_input_tokens(messages, system),
        settings=config,
    )

    request = _request(
        model=model,
        max_tokens=max_tokens,
        messages=messages,
        system=system,
        tools=tools,
        effort=routing.effort_for(job),
    )
    started = time.monotonic()
    partial: Any = None
    try:
        with (client or routing.client()).messages.stream(**request) as active:
            for chunk in active.text_stream:
                partial = getattr(active, "current_message_snapshot", None)
                try:
                    on_delta(chunk)
                except Exception:  # pragma: no cover - the guard, not a path
                    logger.exception("a delta subscriber raised; the call continues")
            response = active.get_final_message()
    except anthropic.RateLimitError as exc:
        settle(call_id, usage=_NO_USAGE, cost_usd=0.0, latency_ms=0, failed=True)
        raise provider_rate_limited(
            f"{config.model_provider} rate limited the request: {exc}"
        ) from exc
    except Exception as exc:
        # A stream that drops has usually already delivered — and been billed for — output.
        # Settling from the last snapshot records that spend; settling at zero would have
        # been the previous behaviour of writing no row at all, which left the tokens
        # invisible to the ledger and to every subsequent budget check.
        usage = usage_of(partial) if partial is not None else _NO_USAGE
        settle(
            call_id,
            usage=usage,
            cost_usd=cost_of(
                model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=usage.cache_read_tokens,
                cache_write_tokens=usage.cache_write_tokens,
            ),
            latency_ms=int((time.monotonic() - started) * 1000),
            failed=True,
        )
        raise unavailable(f"The model provider did not answer: {exc}") from exc

    return _record_and_wrap(
        response,
        job=job,
        model=model,
        config=config,
        call_id=call_id,
        session_id=session_id,
        latency_ms=int((time.monotonic() - started) * 1000),
    )


# Warn while there is still room to do something about it. A warning at 99% is a
# notification that the next call will fail, which the refusal already says.
WARN_AT_FRACTION_REMAINING = 0.2


def _warn_if_close_to_a_ceiling(session_id: str, settings: Settings) -> None:
    """Publish `budget.warning` when a ceiling is in sight (docs/API.md's event list).

    Never raises: a failure to warn must not turn a completed call into an error the caller
    sees, having already paid for it."""
    try:
        with Session(get_engine()) as db:
            status = budget_status(db, session_id=session_id, settings=settings)
        for scope in ("session", "day"):
            limit = status[scope]["limit"]
            if limit and status[scope]["remaining"] / limit <= WARN_AT_FRACTION_REMAINING:
                event_bus.bus().publish(
                    session_id,
                    "budget.warning",
                    scope=scope,
                    consumed=status[scope]["spent"],
                    limit=limit,
                )
    except Exception:  # pragma: no cover - the guard, not a path
        logger.exception("could not evaluate the budget warning for session %s", session_id)


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
    tokens_in, tokens_out, cache_read, cache_write = db.exec(
        select(
            func.coalesce(func.sum(LlmCall.input_tokens), 0),
            func.coalesce(func.sum(LlmCall.output_tokens), 0),
            func.coalesce(func.sum(LlmCall.cache_read_tokens), 0),
            func.coalesce(func.sum(LlmCall.cache_write_tokens), 0),
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
        # Reported because it is the number that answers "is caching working" — a write
        # costs 1.25x and a read 0.1x, so a system writing more than it reads is paying a
        # premium for nothing. It was summed by enforcement and exposed by no read
        # surface, so a 200,000-token cache-write call showed on `/costs` as a call with
        # zero tokens and a real dollar figure.
        "cache_write_tokens": int(cache_write),
        "by_job": [
            {"job": j, "calls": int(c), "cost_usd": round(float(s), 6)} for j, c, s in by_job
        ],
        "by_model": [
            {"model": m, "calls": int(c), "cost_usd": round(float(s), 6)} for m, c, s in by_model
        ],
    }
