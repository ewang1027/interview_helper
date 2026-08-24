"""Importing problems you solved on LeetCode, from metadata alone.

**This does not fetch problem statements, and that is the whole design constraint.**
docs/PRACTICE_LOG.md is manual-entry-only because docs/CORPUS.md mechanically rejects
proprietary statement text, and "fetching a LeetCode page to classify it would mean
holding that text somewhere, even briefly". That rule is about *content*. A title, a slug,
a difficulty label and a topic tag are the same four fields the practice log already
stores, typed by hand, for every entry — so this reads those and nothing else. The
GraphQL projections below name their fields explicitly; there is no query here that could
return a statement even by accident.

Two ways in, neither needing a credential:

- `recent_solves(username)` — accepted submissions from a public profile.
- `problem(slug)` — one problem's title, difficulty and topic tags.

**The tags are the point.** LeetCode labels its own problems `sliding-window`,
`union-find`, `monotonic-stack` — editorial metadata that maps almost one-to-one onto this
project's coding taxonomy. That turns an import into something already classified, which
matters because the model classifier cannot run here and every logged problem otherwise
lands `pending_classification` for a human to tag by hand.

**An ambiguous tag proposes nothing.** `concept_evidence` is immutable, so a wrong tag is a
permanent wrong fact about someone's mastery — and `dynamic-programming` covers five
concepts in this taxonomy. Broad tags are deliberately absent from the table below, and a
problem carrying only those lands `pending_classification` exactly as it does today. The
gate this feature must not weaken is the one that says a guess does not count.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

ENDPOINT = "https://leetcode.com/graphql"
PROBLEM_URL = "https://leetcode.com/problems/{slug}/"

# LeetCode answers 403 to a bare client.
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; interview_helper/0.1; personal practice log)",
    "Referer": "https://leetcode.com",
}

TIMEOUT = httpx.Timeout(15.0)

# A slug is the tail of a problem URL. Validated rather than trusted: it is user input,
# and while it travels as a GraphQL *variable* rather than in a URL path — so there is no
# request this could redirect — a pattern is cheaper than reasoning about that every time
# the call site changes.
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# How many problems one import may fetch. Each slug is one request to leetcode.com, and an
# unbounded list is both a slow HTTP handler and an impolite thing to point at somebody
# else's service.
MAX_SLUGS = 100

GRADER = "leetcode-topic-tags@1"

# Confidence for an unambiguous tag match. Above `AUTO_ACCEPT_CONFIDENCE` (0.75) because
# this is a lookup against LeetCode's own editorial labels rather than a model's guess —
# but not 1.0, because a problem tagged `sliding-window` can still principally exercise
# something else, and the number should not claim otherwise.
TAG_CONFIDENCE = 0.9

# LeetCode topic tag -> this project's concept, most specific first. First match wins, so
# ordering is load-bearing: `longest-substring-without-repeating-characters` carries
# `hash-table`, `string` and `sliding-window`, and only the last of those names what the
# problem is actually about.
#
# Tags absent on purpose, because each covers more than one concept here and guessing
# writes immutable evidence against the wrong one:
#   dynamic-programming  -> dp-1d / dp-2d-grid / dp-knapsack / dp-subsequences / dp-intervals
#   graph                -> graph-bfs / graph-dfs / topological-sort / union-find
#   array, string, math, simulation, sorting, counting, database, geometry, number-theory
TAG_TO_CONCEPT: tuple[tuple[str, str], ...] = (
    # Unmistakable: the tag names one technique and this taxonomy has exactly one for it.
    ("union-find", "union-find"),
    ("topological-sort", "topological-sort"),
    ("trie", "trie"),
    ("monotonic-stack", "monotonic-stack"),
    ("monotonic-queue", "deque-window"),
    ("shortest-path", "shortest-path-weighted"),
    ("bitmask", "bitmask-enumeration"),
    ("memoization", "memoization"),
    ("sliding-window", "sliding-window"),
    ("two-pointers", "two-pointers"),
    ("prefix-sum", "prefix-sums"),
    ("backtracking", "recursion-backtracking"),
    # Structure before traversal. `validate-binary-search-tree` carries
    # `binary-search-tree` *and* `depth-first-search`, and ranking the traversal first
    # called it a graph problem — measured, and the reason this line sits here.
    ("binary-search-tree", "bst-invariants"),
    ("binary-search", "binary-search-index"),
    ("heap-priority-queue", "heap-top-k"),
    ("linked-list", "linked-list-manipulation"),
    ("breadth-first-search", "graph-bfs"),
    ("depth-first-search", "graph-dfs"),
    ("bit-manipulation", "bit-tricks"),
    ("greedy", "greedy-exchange"),
    ("stack", "stack-simulation"),
    # Weaker, and last for that reason: these fire only when nothing above matched.
    ("binary-tree", "tree-traversal"),
    ("tree", "tree-traversal"),
    ("hash-table", "hash-map-counting"),
)

# A tag that names a *family* this taxonomy splits several ways. When one is present, only
# the tags listed beside it may still win; anything else means the specific concept cannot
# be told from the metadata, and the problem waits for a human.
#
# Both were found by running the table over real problems rather than by inspection:
# `coin-change` is tagged `dynamic-programming` *and* `breadth-first-search`, and came out
# as a graph problem; `lru-cache` is tagged `design` and `linked-list`, and came out as
# linked-list manipulation. DP problems are routinely co-tagged with the alternative
# solutions people post, which is exactly the signal that must not be trusted.
FAMILY_TAGS: dict[str, frozenset[str]] = {
    # dp-1d · dp-2d-grid · dp-knapsack · dp-subsequences · dp-intervals
    "dynamic-programming": frozenset({"memoization"}),
    # oop-class-design · lru-cache-design · iterator-design
    "design": frozenset({"trie", "monotonic-queue"}),
}


@dataclass(frozen=True)
class LeetCodeProblem:
    """One problem's metadata. Deliberately no field that could hold a statement."""

    slug: str
    title: str
    difficulty: str | None
    topic_tags: tuple[str, ...]

    @property
    def url(self) -> str:
        return PROBLEM_URL.format(slug=self.slug)

    def concept(self) -> tuple[str | None, str]:
        """The concept this problem's tags name, and why — or `None` and the reason not."""
        if not self.topic_tags:
            return None, "LeetCode lists no topic tags for this problem"

        tags = set(self.topic_tags)
        for tag, concept_id in TAG_TO_CONCEPT:
            if tag not in tags:
                continue
            blocked = [
                family
                for family, allowed in FAMILY_TAGS.items()
                if family in tags and tag not in allowed
            ]
            if blocked:
                return None, (
                    f"tagged {blocked[0]!r}, which this taxonomy splits several ways — "
                    f"{tag!r} is not specific enough to choose between them"
                )
            return concept_id, f"LeetCode tags this {tag!r}"

        return None, ("no concept is named unambiguously by " + ", ".join(sorted(self.topic_tags)))


@dataclass(frozen=True)
class Solve:
    slug: str
    title: str
    solved_at: int
    """Unix seconds, as LeetCode reports it."""


class LeetCodeError(RuntimeError):
    """The import could not be completed. Never raised for one bad slug — see `problems`."""


def slug_from(text: str) -> str | None:
    """Read a slug out of a URL or accept one written directly.

    Takes what somebody actually pastes: a full URL, one with a `/description/` tail or a
    query string, or the bare slug.
    """
    candidate = text.strip().rstrip("/")
    if not candidate:
        return None
    match = re.search(r"leetcode\.com/problems/([^/?#]+)", candidate)
    if match:
        candidate = match.group(1)
    elif "/" in candidate or "." in candidate:
        # Something URL-shaped that is not a LeetCode problem link.
        return None
    candidate = candidate.split("?")[0].strip().lower()
    return candidate if SLUG.match(candidate) else None


@contextmanager
def session(client: Any = None) -> Iterator[Any]:
    """One connection for a whole import, or whatever a caller injects.

    An import fetches one problem per slug, and a fresh `httpx.Client` per request would
    open a fresh TCP connection per request against somebody else's service. The injected
    form is what lets a test drive the whole path with a stub and no network — the same
    dependency shape the executor and model clients use.
    """
    if client is not None:
        yield client
        return
    with httpx.Client(timeout=TIMEOUT, headers=HEADERS) as owned:
        yield owned


def _post(payload: dict[str, Any], *, client: httpx.Client | None = None) -> dict[str, Any]:
    owned = client is None
    http = client or httpx.Client(timeout=TIMEOUT, headers=HEADERS)
    try:
        response = http.post(ENDPOINT, json=payload, headers=HEADERS)
    except httpx.HTTPError as exc:
        raise LeetCodeError(f"could not reach leetcode.com: {exc}") from exc
    finally:
        if owned:
            http.close()

    if response.status_code != 200:
        raise LeetCodeError(f"leetcode.com answered {response.status_code}")
    body: dict[str, Any] = response.json()
    if body.get("errors"):
        raise LeetCodeError(str(body["errors"])[:200])
    return body.get("data") or {}


_PROBLEM_QUERY = """
query($slug: String!) {
  question(titleSlug: $slug) {
    title
    difficulty
    topicTags { slug }
  }
}
"""

_RECENT_QUERY = """
query($username: String!, $limit: Int!) {
  recentAcSubmissionList(username: $username, limit: $limit) {
    title
    titleSlug
    timestamp
  }
}
"""


def problem(slug: str, *, client: httpx.Client | None = None) -> LeetCodeProblem | None:
    """One problem's metadata, or `None` if LeetCode does not know the slug."""
    if not SLUG.match(slug):
        return None
    data = _post({"query": _PROBLEM_QUERY, "variables": {"slug": slug}}, client=client)
    question = data.get("question")
    if not question:
        return None
    return LeetCodeProblem(
        slug=slug,
        title=question.get("title") or slug,
        difficulty=question.get("difficulty"),
        topic_tags=tuple(tag["slug"] for tag in question.get("topicTags") or []),
    )


def recent_solves(
    username: str, *, limit: int = 20, client: httpx.Client | None = None
) -> list[Solve]:
    """Accepted submissions from a public profile, newest first.

    LeetCode caps what it returns here regardless of `limit`, and it is the *recent* list
    rather than the full history — a complete one needs a session cookie, which this
    deliberately does not take. Pasting slugs is the path for a back catalogue.
    """
    data = _post(
        {"query": _RECENT_QUERY, "variables": {"username": username, "limit": limit}},
        client=client,
    )
    rows = data.get("recentAcSubmissionList")
    if rows is None:
        raise LeetCodeError(f"no public profile for {username!r}")
    return [
        Solve(
            slug=row["titleSlug"],
            title=row["title"],
            solved_at=int(row["timestamp"]),
        )
        for row in rows
    ]
