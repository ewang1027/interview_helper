"""Every schema this repo sends under constrained decoding, checked against what the API accepts.

**The bug this exists to prevent has now happened three times in one repo.**

Structured outputs (`output_config.format.schema`) and `strict: true` tools accept only a
subset of JSON Schema. `type`, `enum`, `required` and `additionalProperties` survive; the
range and length keywords — `minimum`, `maximum`, `minItems`, `maxItems`, `minLength`,
`maxLength` — are rejected with a 400 naming the offending property:

    output_config.format.schema: For 'number' type, properties maximum, minimum are not supported
    tools.1.custom: For 'array' type, property 'maxItems' is not supported

Three schemas here carried those keywords, and **none of the existing tests could catch
it**, because a scripted client answers whatever it was handed and never validates the
request. Each one was found only when a real call was finally made:

- `api.jobs.parse_response_schema` / `row_schema` / `record_tool` — found 2026-08-26 by
  the job tracker's first live import, three 400s in a row.
- `api.practice.response_schema` — same defect, present since Phase 9. Every real
  classification would have failed.
- `api.grading.rubric.response_schema` — same defect, present since Phase 3. **Every real
  design or behavioral grading would have failed**, which is the expensive one: the
  buildlog said all four modes grade, and two of them could not have.

So this is a static check rather than a live one. It costs nothing, runs in the default
suite, and it fails the moment somebody adds a bound to a schema that cannot carry one.
What it cannot check is whether the *constraint* survived the removal — that belongs with
each schema, and each of the three now enforces its bound in code with a test saying so.
"""

from __future__ import annotations

from typing import Any

import pytest

from api import jobs, practice
from api.grading import rubric
from corpus.loader import load_items

# Rejected under constrained decoding. `format`, `default` and `description` are not on the
# list because nothing here sends them; add them if that stops being true and a call 400s.
UNSUPPORTED = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minItems",
        "maxItems",
        "minLength",
        "maxLength",
        "multipleOf",
        "pattern",
    }
)


def offenders(node: Any, path: str = "$") -> list[str]:
    """Every unsupported keyword in a schema, with the path that reaches it."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            # Only a *schema* position counts. A property literally named "pattern" is a
            # field the model fills in, not a constraint on one, and `properties` is where
            # that distinction lives.
            if key in UNSUPPORTED:
                found.append(f"{path}.{key}")
            elif key == "properties" and isinstance(value, dict):
                for name, child in value.items():
                    found += offenders(child, f"{path}.properties.{name}")
            else:
                found += offenders(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            found += offenders(item, f"{path}[{index}]")
    return found


def _design_criteria() -> list[dict[str, Any]]:
    items = {item.id: item for item in load_items()}
    return items["i.design.0001"].grading["criteria"]


def schemas() -> list[tuple[str, dict[str, Any]]]:
    """Every schema sent as `output_schema=` or on a `strict` tool.

    Listed by hand rather than discovered, because the thing that matters is that a *new*
    one gets added here — and a test that finds its own subjects would silently pass over
    the schema nobody remembered to register.
    """
    return [
        ("jobs.row_schema", jobs.row_schema()),
        ("jobs.parse_response_schema", jobs.parse_response_schema()),
        ("jobs.record_tool", jobs.record_tool()["input_schema"]),
        ("practice.response_schema", practice.response_schema()),
        ("rubric.response_schema", rubric.response_schema(_design_criteria())),
    ]


@pytest.mark.parametrize(
    "name,schema", schemas(), ids=lambda value: value if isinstance(value, str) else ""
)
def test_no_schema_carries_a_keyword_constrained_decoding_rejects(name: str, schema: Any) -> None:
    found = offenders(schema)
    assert not found, (
        f"{name} carries {found}, which the API rejects with a 400 under constrained "
        "decoding. Enforce the bound in code instead, and say so where it moved to."
    )


def test_the_detector_finds_a_keyword_when_there_is_one() -> None:
    """A guard that cannot fail is a guard that passes vacuously.

    Checked in both directions, the same way this repo checks every other gate: the
    detector is shown a schema shaped exactly like the ones it inspects, and has to find
    the bound buried in it.
    """
    planted = {
        "type": "object",
        "properties": {
            "rows": {
                "type": "array",
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "properties": {"score": {"type": "number", "minimum": 0}},
                },
            }
        },
    }
    found = offenders(planted)
    assert "$.properties.rows.maxItems" in found
    assert "$.properties.rows.items.properties.score.minimum" in found


def test_a_property_named_like_a_keyword_is_not_an_offender() -> None:
    """`pattern` as a *field the model fills in* is fine; `pattern` as a constraint is not.
    Without this the guard would refuse a perfectly legal schema and get switched off."""
    legal = {
        "type": "object",
        "properties": {"pattern": {"type": "string"}, "maximum": {"type": "string"}},
    }
    assert offenders(legal) == []


def test_enum_survives_because_it_is_the_one_that_matters() -> None:
    """The removals cost nothing important, and this says why in an assertion.

    Every bound that was dropped was a *range*, and each is enforced in code. `enum` is the
    constraint doing real work — it makes a tag outside the vocabulary unrepresentable
    rather than something to filter afterwards — and it is fully supported.
    """
    assert jobs.row_schema()["properties"]["subcategory"]["enum"] == list(jobs.SUBCATEGORIES)
    assert jobs.row_schema()["properties"]["stage"]["enum"] == list(jobs.STAGES)
    assert set(practice.response_schema()["properties"]["primary_concept_id"]["enum"]) == (
        practice.concept_ids()
    )
