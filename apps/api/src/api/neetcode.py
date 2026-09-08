"""NeetCode links, which name LeetCode problems under slugs of NeetCode's own.

The NeetCode 150 is a curated *ordering* of problems that already exist on LeetCode, so
nothing here fetches anything: a NeetCode link is resolved to the LeetCode problem it
names, and `api.leetcode` reads the metadata from there exactly as it does for a link
pasted from LeetCode itself. What this module adds is the mapping, and the fact that the
problem was worked through NeetCode — which is the part worth recording, because "I am
working the NeetCode 150" is a different thing to remember than "I did a LeetCode problem".

**Why the mapping needs to exist at all.** NeetCode renames 74 of the problems it lists —
`contains-duplicate` is `duplicate-integer` there, `two-sum` is `two-integer-sum`,
`valid-anagram` is `is-anagram` — so a pasted NeetCode link cannot be turned into a
LeetCode slug by string surgery. neetcode.io publishes no API either; the table lives in
its JavaScript bundle. So the mapping is extracted once and checked in
(`scripts/build_neetcode_catalogue.py` rebuilds it), which makes it reviewable, fast and
testable offline, at the price of going stale — a problem NeetCode adds after the last
extraction is skipped by name, with the LeetCode link named as the way around it.

**Titles and slugs only.** The catalogue holds each problem's two slugs, its title,
NeetCode's own pattern group and which of its lists the problem is on. No statement, no
solution, no video — the same line docs/PRACTICE_LOG.md draws for `api.leetcode`, and for
the same reason: this project stores pointers and metadata, never someone else's problem
text.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

CATALOGUE_PATH = Path(__file__).resolve().parent / "data" / "neetcode.json"

PROBLEM_URL = "https://neetcode.io/problems/{slug}/"

# Same shape and the same reason as `api.leetcode.SLUG`: this is user input, and a pattern
# is cheaper than re-reasoning about where it travels every time a call site changes.
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

URL = re.compile(r"neetcode\.io/problems/([^/?#]+)")


@dataclass(frozen=True)
class NeetCodeProblem:
    """One row of the bundled catalogue: a NeetCode problem and the LeetCode one it is."""

    neetcode_slug: str
    leetcode_slug: str
    title: str
    pattern: str
    lists: tuple[str, ...]
    """Which of NeetCode's own lists this is on — `blind75`, `neetcode150`, `neetcode250`."""

    @property
    def url(self) -> str:
        return PROBLEM_URL.format(slug=self.neetcode_slug)

    @property
    def renamed(self) -> bool:
        return self.neetcode_slug != self.leetcode_slug


def _load() -> dict[str, Any]:
    with CATALOGUE_PATH.open(encoding="utf-8") as fh:
        payload: dict[str, Any] = json.load(fh)
    return payload


@lru_cache
def catalogue() -> dict[str, NeetCodeProblem]:
    """The bundled table, keyed by NeetCode slug. A build-time artifact, like the corpus."""
    return {
        row["neetcode_slug"]: NeetCodeProblem(
            neetcode_slug=row["neetcode_slug"],
            leetcode_slug=row["leetcode_slug"],
            title=row["title"],
            pattern=row["pattern"],
            lists=tuple(row["lists"]),
        )
        for row in _load()["problems"]
    }


@lru_cache
def extracted_at() -> str:
    """The date the catalogue was pulled from neetcode.io, for anything reporting staleness."""
    return str(_load()["extracted_at"])


@lru_cache
def leetcode_slugs() -> frozenset[str]:
    return frozenset(row.leetcode_slug for row in catalogue().values())


def slug_from(text: str) -> str | None:
    """The NeetCode slug in whatever was pasted, or `None` if this is not NeetCode's.

    A **neetcode.io link** is NeetCode's by construction, and is returned whether or not
    the catalogue knows it — an unknown slug is a stale catalogue, and the caller should
    say so rather than report the link as unreadable.

    A **bare word** is NeetCode's only when the catalogue lists it *and* no LeetCode
    problem in that same catalogue uses it. `duplicate-integer` is a name only NeetCode
    uses, so it resolves here; `two-sum` is LeetCode's own slug for a problem NeetCode
    calls `two-integer-sum`, so it does not, and falls through to `api.leetcode` where it
    belongs. The two readings name the same problem in every overlapping case, so the rule
    decides which *site* the solve is recorded against, never which problem.
    """
    candidate = text.strip().rstrip("/")
    if not candidate:
        return None

    match = URL.search(candidate)
    if match:
        return _clean(match.group(1))
    if "/" in candidate or "." in candidate:
        # URL-shaped, and not a neetcode.io problem link.
        return None

    slug = _clean(candidate)
    if slug is None or slug not in catalogue() or slug in leetcode_slugs():
        return None
    return slug


def _clean(candidate: str) -> str | None:
    cleaned = candidate.split("?")[0].strip().lower()
    return cleaned if SLUG.match(cleaned) else None


def lookup(slug: str) -> NeetCodeProblem | None:
    """The catalogue row for a NeetCode slug, or `None` if this build has never seen it."""
    return catalogue().get(slug)
