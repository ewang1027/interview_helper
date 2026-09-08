"""Rebuild `apps/api/src/api/data/neetcode.json` from neetcode.io's own problem table.

**Why a bundled file rather than a call at import time.** A NeetCode problem *is* a
LeetCode problem, so importing one only needs the mapping between the two slugs — and
neetcode.io publishes no API, so the mapping has to come out of the site's JavaScript
bundle. Doing that per import would be slow, fragile and rude; doing it once and checking
the result in makes the mapping reviewable, offline-testable and stable. The cost is that
it goes stale, which is what this script exists to fix.

**What it takes, and what it deliberately does not.** A title, the two slugs, NeetCode's
own pattern group and which of its lists a problem is on. No problem statement, no
solution, no video — the same line `api.leetcode` draws, for the same reason
(docs/PRACTICE_LOG.md): this project stores pointers and metadata, never someone else's
problem text.

The bundle's filename carries a content hash that changes on every deploy, so the hash is
read from the page rather than pinned here.

    uv run python scripts/build_neetcode_catalogue.py
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

SITE = "https://neetcode.io/"
OUT = Path(__file__).resolve().parents[1] / "apps/api/src/api/data/neetcode.json"

# The array literal starts at `O=[{problem:"..."`, and the identifier `O` is a minifier
# artifact that will not survive a rebuild — so it is matched on the *shape* of the first
# entry instead: an object whose first key is `problem` and which carries a `pattern`.
ARRAY_START = re.compile(r"\[\{problem:\"[^\"]+\",pattern:")

# `key:` -> `"key":`, which is all that separates this literal from JSON once `!0`/`!1`
# are spelled out. Anchored on `{` or `,` so a colon inside a title — "Pow(x, n)" is the
# only string in the table with punctuation at all — cannot be mistaken for a key.
KEY = re.compile(r"([{,])([A-Za-z_][A-Za-z0-9_]*):")

LISTS = ("blind75", "neetcode150", "neetcode250")

# What each list should contain, as NeetCode itself publishes them. A mapping that silently
# loses half the NeetCode 150 is worse than no mapping, and the failure this guards against
# is not a network error — it is a bundle whose shape changed just enough to still parse.
EXPECTED = {"blind75": 75, "neetcode150": 150, "neetcode250": 250}


def bundle_url(client: httpx.Client) -> str:
    page = client.get(SITE).text
    match = re.search(r'src="(main\.[0-9a-f]+\.js)"', page)
    if match is None:
        raise SystemExit("no main.<hash>.js on the page — the site's build changed")
    return SITE + match.group(1)


def array_literal(source: str) -> str:
    """The problem table's array literal, sliced at its matching bracket."""
    match = ARRAY_START.search(source)
    if match is None:
        raise SystemExit("no problem table in the bundle — its shape changed")
    start = match.start()
    depth, quote, i = 0, None, start
    while i < len(source):
        char = source[i]
        if quote:
            if char == "\\":
                i += 2
                continue
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
        i += 1
    raise SystemExit("the problem table's array literal is unterminated")


def as_json(literal: str) -> list[dict[str, Any]]:
    rows = json.loads(KEY.sub(r'\1"\2":', literal).replace("!0", "true").replace("!1", "false"))
    if not isinstance(rows, list):  # pragma: no cover - the literal is an array or nothing
        raise SystemExit("the problem table did not parse as a list")
    return rows


def catalogue(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The rows that exist as neetcode.io pages, which are the only ones anyone can paste."""
    out = []
    for row in rows:
        if not row.get("ncLink") or not row.get("link"):
            continue
        out.append(
            {
                "neetcode_slug": row["ncLink"].strip("/"),
                "leetcode_slug": row["link"].strip("/"),
                "title": row["problem"],
                "pattern": row["pattern"],
                "lists": [name for name in LISTS if row.get(name)],
            }
        )
    return sorted(out, key=lambda row: row["neetcode_slug"])


def check(problems: list[dict[str, Any]]) -> None:
    for field in ("neetcode_slug", "leetcode_slug"):
        seen = [row[field] for row in problems]
        duplicated = sorted({slug for slug in seen if seen.count(slug) > 1})
        if duplicated:
            raise SystemExit(f"duplicate {field}: {duplicated}")
    for name, expected in EXPECTED.items():
        found = sum(1 for row in problems if name in row["lists"])
        if found != expected:
            raise SystemExit(f"{name}: found {found} problems, expected {expected}")


def render(header: dict[str, str], problems: list[dict[str, Any]]) -> str:
    """One problem per line. `json.dump` at any indent makes a 600-entry table unreadable
    and every regeneration a diff nobody checks; a line per row is greppable and reviewable."""
    lines = [json.dumps(row, ensure_ascii=False) for row in problems]
    head = ",\n".join(f"  {json.dumps(k)}: {json.dumps(v)}" for k, v in header.items())
    body = ",\n".join(f"  {line}" for line in lines)
    return "{\n" + head + ',\n  "problems": [\n' + body + "\n  ]\n}\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        url = bundle_url(client)
        problems = catalogue(as_json(array_literal(client.get(url).text)))
    check(problems)

    payload = {
        "source": SITE,
        "bundle": url.rsplit("/", 1)[-1],
        "extracted_at": datetime.now().astimezone().date().isoformat(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(payload, problems), encoding="utf-8")
    renamed = sum(1 for row in problems if row["neetcode_slug"] != row["leetcode_slug"])
    print(f"{len(problems)} problems ({renamed} renamed by NeetCode) -> {args.out}")


if __name__ == "__main__":
    main()
