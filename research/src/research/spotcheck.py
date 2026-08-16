"""Deterministic sampling for the human spot-check gate.

The Phase 1 gate ends with a human reading ten random instances and confirming they
read like real interview questions rather than textbook exercises. Sampling is seeded
so a spot-check is reproducible: "the 10 I read" is a seed you can write in the
buildlog, not a claim nobody can re-derive.

Run with `make spot-check` (or `uv run python -m research.spotcheck --n 10 --seed 1`).
"""

from __future__ import annotations

import argparse
import random
import sys
from typing import Any

from corpus.loader import CorpusPaths, load_raw_items


def sample(
    items: list[dict[str, Any]], n: int, seed: int, domain: str | None = None
) -> list[dict[str, Any]]:
    pool = [i for i in items if i.get("kind") == "instance"]
    if domain:
        pool = [i for i in pool if i.get("domain") == domain]
    pool.sort(key=lambda i: str(i.get("id")))
    if n >= len(pool):
        return pool
    rng = random.Random(seed)  # noqa: S311 — reproducible sampling, not cryptography
    return rng.sample(pool, n)


def _grading_summary(item: dict[str, Any]) -> str:
    grading = item.get("grading") or {}
    kind = grading.get("type")
    if kind == "tests":
        tests = grading.get("tests", [])
        langs = ",".join(grading.get("languages", []))
        kinds = sorted({str(t.get("kind", "edge")) for t in tests})
        target = grading.get("complexity_target")
        return f"tests: {len(tests)} ({', '.join(kinds)}) · {langs} · target {target}"
    if kind == "answer":
        answer = grading.get("answer", {})
        rubric = grading.get("reasoning_rubric", [])
        return (
            f"answer: exact={answer.get('exact')} numeric={answer.get('numeric')} "
            f"· {len(rubric)} reasoning criteria"
        )
    if kind == "rubric":
        criteria = grading.get("criteria", [])
        return f"rubric: {len(criteria)} criteria, weights {[c.get('weight') for c in criteria]}"
    return "no grading contract"


def render(item: dict[str, Any]) -> str:
    lines = [
        "─" * 78,
        f"{item.get('id')}  [{item.get('domain')} · {item.get('difficulty', {}).get('band')} · "
        f"elo {item.get('difficulty', {}).get('elo')} · {item.get('expected_minutes')} min]",
        f"{item.get('title')}",
        f"archetype: {item.get('archetype_id')}   primary: {item.get('primary_concept')}",
        "",
        str(item.get("statement_md", "")).strip(),
        "",
        _grading_summary(item),
        f"hints: {len(item.get('hints', []))} · follow-ups: {len(item.get('follow_ups', []))}",
        f"sources: {', '.join(s.get('url', '') for s in item.get('sources', []))}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sample corpus instances for a human read.")
    parser.add_argument("--n", type=int, default=10)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument(
        "--domain", choices=["coding", "quant", "system_design", "behavioral"], default=None
    )
    args = parser.parse_args(argv)

    picked = sample(load_raw_items(CorpusPaths.default()), args.n, args.seed, args.domain)
    if not picked:
        print("no instances to sample yet")
        return 0
    for item in picked:
        print(render(item))
    print("─" * 78)
    print(f"{len(picked)} instance(s) · seed {args.seed} — reproducible with the same seed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
