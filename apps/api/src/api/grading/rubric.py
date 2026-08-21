"""Rubric grading: a model's judgement, held to the same standard as a test result.

docs/GRADING.md asks for two things on every criterion, and both are enforced here rather
than hoped for:

- **Score anchors.** Each criterion carries `levels` describing what each score looks like.
  Without them a grader scores on vibe and drifts between runs, so the anchors are sent as
  part of the request rather than summarised into it.
- **Citation.** Every judgement must quote the span it is based on — and the quote is
  *checked against the artifact*. A citation that does not appear in what the candidate
  actually wrote is a fabrication, and the criterion is demoted to not-demonstrated. This
  is the one control that separates "the model read the answer" from "the model wrote a
  plausible review of an answer".

**Not-demonstrated is not failure, and the two are treated differently on purpose.** A
criterion nobody addressed scores zero — you cannot be credited for what you did not do —
but writes **no evidence**, because silence says nothing about ability. Scoring it as
failure would tell the adaptive engine you are weak at something it never observed.

The grader is pure: it takes an item, an artifact and a model client, and returns rows.
Writing them is the session layer's job, which is what lets a grade be re-run over a stored
artifact without duplicating history.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from api import llm
from api.grading.coding import Evidence, hint_retention
from api.settings import Settings
from corpus.models import Item

logger = logging.getLogger(__name__)

GRADER_VERSION = "rubric.llm@1"

# The corpus does not fix one anchor scale, and assuming it does costs a quarter of a
# score in silence. `system_design` and `behavioral` anchor criteria on 0/2/4; every quant
# reasoning rubric on disk anchors on 0/1/2/3. What "full marks" means is therefore the
# criterion's own top anchor, read from it — a hardcoded 4 caps a perfect three-point
# derivation at 0.75 and writes evidence of a weakness that is an artefact of the grader.
# Only used where a criterion carries no anchors at all.
DEFAULT_LEVEL_MAX = 4.0

# A rubric judgement is a model's read of prose, not a hidden test passing. docs/ADAPTIVE.md
# weights evidence by how much it should be trusted, and this is the number that says a
# rubric should move an estimate about half as far as a deterministic result.
RUBRIC_CONFIDENCE = 0.5

# Enough for a judgement per criterion with a citation and a sentence of reasoning.
MAX_TOKENS = 4096

SYSTEM_PROMPT = """You are grading one answer from a technical interview against a rubric
that was written before the answer existed. You are not the interviewer and you are not
helping the candidate; you are producing evidence that will be recorded.

For each criterion, in the order given:

1. Decide whether the answer **demonstrates** it at all. If the candidate never addressed
   it, say so — `demonstrated: false` — and do not invent a charitable reading.
2. If it is demonstrated, choose the level whose anchor text matches what the answer
   actually does. Use the anchors; do not interpolate a feeling about the answer.
3. Quote the span you based that on, **verbatim from the answer**, in `citation`. Copy it
   exactly — it is checked against the answer, and a quote that is not there costs the
   candidate the criterion. If you cannot quote it, it is not demonstrated.
4. Give one sentence of reasoning naming what is present or missing.

Grade what is there, not what a good answer would contain. Fluency is not correctness: a
confident paragraph that never produces the number the criterion asks for scores where the
anchors say it scores."""


@dataclass(frozen=True)
class Judgement:
    """One criterion, judged."""

    id: str
    weight: float
    concept: str | None
    level: float
    level_max: float
    score: float
    demonstrated: bool
    citation: str | None
    reasoning: str
    citation_verified: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "weight": self.weight,
            "concept": self.concept,
            "level": self.level,
            "level_max": self.level_max,
            "score": round(self.score, 4),
            "demonstrated": self.demonstrated,
            "citation": self.citation,
            "citation_verified": self.citation_verified,
            "reasoning": self.reasoning,
        }


@dataclass(frozen=True)
class RubricGrade:
    status: str
    item_id: str
    score: float | None
    hints_revealed: int
    judgements: tuple[Judgement, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    summary: str = ""
    detail: str = ""
    grader_version: str = GRADER_VERSION
    components: dict[str, float] = field(default_factory=dict)

    def as_detail(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "score": self.score,
            "hints_revealed": self.hints_revealed,
            "criteria": [j.as_dict() for j in self.judgements],
            "not_demonstrated": [j.id for j in self.judgements if not j.demonstrated],
            "components": self.components,
            "summary": self.summary,
            "detail": self.detail,
        }


def level_max(criterion: dict[str, Any]) -> float:
    """The top anchor on this criterion — what a full-marks judgement is scored against.

    A criterion with no anchors falls back to the widest scale, which is the same case
    `build_prompt` tells the grader to judge conservatively on: there is no scale to read,
    so a conservative judgement should land low on a wide one rather than high on a narrow
    one it invented.
    """
    tops = [float(key) for key in (criterion.get("levels") or {})]
    top = max(tops, default=0.0)
    return top if top > 0 else DEFAULT_LEVEL_MAX


def response_schema(criteria: list[dict[str, Any]]) -> dict[str, Any]:
    """The shape the model must answer in.

    `id` is an enum of this item's criteria, so a judgement of something that is not on the
    rubric cannot be expressed rather than having to be filtered out afterwards. `maximum`
    is the item's own top anchor: telling a model it may answer 4 on a rubric anchored to 3
    invites a level no anchor describes, which is the ungrounded judgement the anchors exist
    to prevent. Each criterion is still clamped to *its* scale when judged, since one
    `maximum` cannot describe an item that mixes them.
    """
    criterion_ids = [c["id"] for c in criteria]
    top = max((level_max(c) for c in criteria), default=DEFAULT_LEVEL_MAX)
    return {
        "type": "object",
        "properties": {
            "criteria": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "enum": criterion_ids},
                        "demonstrated": {"type": "boolean"},
                        "level": {"type": "number", "minimum": 0, "maximum": top},
                        "citation": {"type": "string"},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["id", "demonstrated", "level", "citation", "reasoning"],
                    "additionalProperties": False,
                },
            },
            "summary": {"type": "string"},
        },
        "required": ["criteria", "summary"],
        "additionalProperties": False,
    }


def _normalise(text: str) -> str:
    """Whitespace-flattened and lowercased, for comparing a quote to its source.

    A model that reflows a quotation across line breaks has still quoted it; one that
    invents a sentence has not. This tells those apart without being brittle about
    formatting."""
    return re.sub(r"\s+", " ", text).strip().lower()


def cites_the_answer(citation: str, answer: str) -> bool:
    """Whether the quote actually appears in what the candidate wrote.

    Short quotes are rejected outright: a citation of "the" is a substring of everything
    and evidence of nothing."""
    quoted = _normalise(citation)
    return len(quoted) >= 12 and quoted in _normalise(answer)


def build_prompt(item: Item, answer: str, criteria: list[dict[str, Any]]) -> str:
    """The request. `criteria` is passed rather than read off the item: quant's derivation
    is judged against `reasoning_rubric`, which is the same shape in a different place."""
    lines = [
        f"# Problem\n\n{item.statement_md}",
        "\n# Rubric\n",
    ]
    for criterion in criteria:
        lines.append(f"## {criterion['id']} (weight {criterion['weight']})")
        lines.append(criterion["description"])
        levels = criterion.get("levels") or {}
        if levels:
            for level in sorted(levels, key=float):
                lines.append(f"- level {level}: {levels[level]}")
        else:
            # docs/GRADING.md: the validator warns rather than errors on a missing
            # `levels`, so the grader has to cope. Say what is missing instead of pretending
            # the anchors were there — an unanchored criterion is where drift starts.
            lines.append("- (no anchors on this criterion; judge conservatively)")
        lines.append("")
    lines.append("# The candidate's answer\n")
    lines.append(answer)
    return "\n".join(lines)


def judge_criteria(
    item: Item,
    answer: str,
    criteria: list[dict[str, Any]],
    *,
    session_id: str | None = None,
    client: Any = None,
    settings: Settings | None = None,
) -> tuple[tuple[Judgement, ...], str]:
    """One model call, judging an artifact against a list of criteria. Returns the
    judgements and the grader's summary.

    Separate from `grade_rubric` because two graders need it and neither owns it: a quant
    derivation is judged against `reasoning_rubric` by exactly this code, and a second copy
    of it would be a second place for the citation check to drift.
    """
    if not criteria:
        raise ValueError(f"{item.id} has a rubric with no criteria")
    if not answer.strip():
        raise ValueError("an empty answer cannot be graded")

    completion = llm.complete(
        job="grading",
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_prompt(item, answer, criteria)}],
        max_tokens=MAX_TOKENS,
        output_schema=response_schema(criteria),
        session_id=session_id,
        client=client,
        settings=settings,
    )
    verdicts = _parse(completion.text)
    judgements = tuple(
        _judge(criterion, verdicts.get(criterion["id"]), answer) for criterion in criteria
    )
    return judgements, verdicts.get("__summary__", {}).get("text", "")


def weighted_score(judgements: tuple[Judgement, ...]) -> float:
    """The judgements as one number in [0, 1], each criterion carrying its own weight."""
    weight = sum(j.weight for j in judgements) or 1.0
    return sum(j.score * j.weight for j in judgements) / weight


def evidence_from(
    judgements: tuple[Judgement, ...], *, grader_version: str = GRADER_VERSION
) -> tuple[Evidence, ...]:
    """The `concept_evidence` rows a set of judgements implies.

    Demonstrated only: silence is not evidence of weakness, and telling the adaptive engine
    otherwise would drill a concept the candidate was never asked about.
    """
    return tuple(
        Evidence(
            concept_id=judgement.concept,
            score=judgement.score,
            confidence=RUBRIC_CONFIDENCE,
            grader_version=grader_version,
        )
        for judgement in judgements
        if judgement.demonstrated and judgement.concept
    )


def criteria_detail(judgements: tuple[Judgement, ...]) -> str:
    """How many criteria were demonstrated, and which were not."""
    missing = [j.id for j in judgements if not j.demonstrated]
    detail = f"{len(judgements) - len(missing)}/{len(judgements)} criteria demonstrated"
    if missing:
        detail += f"; not demonstrated: {', '.join(missing)}"
    return detail


def grade_rubric(
    item: Item,
    answer: str,
    *,
    hints_revealed: int = 0,
    session_id: str | None = None,
    client: Any = None,
    settings: Settings | None = None,
) -> RubricGrade:
    """Judge one artifact against its item's rubric."""
    grading = item.grading or {}
    if grading.get("type") != "rubric":
        raise ValueError(f"{item.id} is not graded by rubric (type={grading.get('type')!r})")
    criteria = grading.get("criteria") or []

    judgements, summary = judge_criteria(
        item, answer, criteria, session_id=session_id, client=client, settings=settings
    )

    raw = weighted_score(judgements)
    retention = hint_retention(hints_revealed)
    score = raw * retention
    evidence = evidence_from(judgements)
    detail = criteria_detail(judgements)
    if hints_revealed:
        detail += f"; {hints_revealed} hint(s) taken, keeping {retention:.0%}"

    return RubricGrade(
        status="graded",
        item_id=item.id,
        score=round(score, 4),
        hints_revealed=hints_revealed,
        judgements=judgements,
        evidence=evidence,
        summary=summary,
        detail=detail,
        components={"rubric": round(raw, 4), "hint_retention": round(retention, 4)},
    )


def _parse(text: str) -> dict[str, Any]:
    """The model's answer, keyed by criterion id.

    `output_config.format` guarantees valid JSON matching the schema, so a failure here is
    a provider or wiring problem rather than a bad answer — and it is raised, because a
    grader that shrugs and scores zero would write evidence of weakness from its own bug.
    """
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"the grader did not answer with JSON: {text[:200]!r}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("criteria"), list):
        raise ValueError(f"the grader's answer had no criteria: {text[:200]!r}")
    verdicts: dict[str, Any] = {
        entry["id"]: entry
        for entry in payload["criteria"]
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    }
    verdicts["__summary__"] = {"text": str(payload.get("summary", ""))}
    return verdicts


def _judge(criterion: dict[str, Any], verdict: dict[str, Any] | None, answer: str) -> Judgement:
    """One criterion's judgement, after the citation has been checked."""
    weight = float(criterion.get("weight", 0.0))
    concept = criterion.get("concept")
    top = level_max(criterion)
    if verdict is None:
        # The model skipped it. Not demonstrated, which is the same conclusion as "the
        # candidate did not address it" — and the honest one, since nothing says otherwise.
        return Judgement(
            id=criterion["id"],
            weight=weight,
            concept=concept,
            level=0.0,
            level_max=top,
            score=0.0,
            demonstrated=False,
            citation=None,
            reasoning="The grader returned no judgement for this criterion.",
            citation_verified=False,
        )

    citation = str(verdict.get("citation") or "")
    verified = cites_the_answer(citation, answer)
    demonstrated = bool(verdict.get("demonstrated")) and verified
    level = max(0.0, min(top, float(verdict.get("level", 0.0))))
    reasoning = str(verdict.get("reasoning") or "")
    if verdict.get("demonstrated") and not verified:
        reasoning = f"[citation not found in the answer] {reasoning}"
        logger.info("criterion %s cited text that is not in the artifact", criterion["id"])
    return Judgement(
        id=criterion["id"],
        weight=weight,
        concept=concept,
        level=level if demonstrated else 0.0,
        level_max=top,
        score=(level / top) if demonstrated else 0.0,
        demonstrated=demonstrated,
        citation=citation or None,
        reasoning=reasoning,
        citation_verified=verified,
    )
