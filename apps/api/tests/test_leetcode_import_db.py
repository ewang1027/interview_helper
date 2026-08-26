"""The LeetCode import against a live Postgres, with a scripted LeetCode.

Never touches the network: the HTTP client is injected, exactly as the executor and model
clients are. A test that reaches leetcode.com is a test that fails when somebody else
deploys, and the thing worth testing here is not their API — it is that an import lands in
the state this project's own rules require.
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import sign_in, use_settings
from fastapi.testclient import TestClient
from sqlmodel import Session, col, delete, select

from api.db import get_engine
from api.main import app
from api.mastery import recompute
from api.models import ConceptEvidence, PracticeProblem, PracticeSolve
from api.routes.practice import get_leetcode_client
from api.users import single_user

pytestmark = pytest.mark.db


class ScriptedLeetCode:
    """Answers `question(titleSlug)` from a table of slug -> tags."""

    def __init__(self, catalogue: dict[str, tuple[str, ...]], recent: list[str] | None = None):
        self.catalogue = catalogue
        self.recent = recent or []
        self.asked: list[str] = []

    def post(self, url: str, json: dict, headers: dict | None = None):
        variables = json.get("variables", {})
        if "username" in variables:
            return _Response(
                {
                    "data": {
                        "recentAcSubmissionList": [
                            {"title": slug, "titleSlug": slug, "timestamp": "1700000000"}
                            for slug in self.recent
                        ]
                    }
                }
            )
        slug = variables["slug"]
        self.asked.append(slug)
        tags = self.catalogue.get(slug)
        if tags is None:
            return _Response({"data": {"question": None}})
        return _Response(
            {
                "data": {
                    "question": {
                        "title": slug.replace("-", " ").title(),
                        "difficulty": "Medium",
                        "topicTags": [{"slug": t} for t in tags],
                    }
                }
            }
        )


class _Response:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        return self._payload


CATALOGUE = {
    "two-sum": ("array", "hash-table"),
    "coin-change": ("array", "dynamic-programming", "breadth-first-search"),
    "daily-temperatures": ("array", "stack", "monotonic-stack"),
}


@pytest.fixture
def imported() -> Any:
    """Remove exactly the practice rows a test created, then rebuild the projection.

    It used to *clear the practice tables* — `select(PracticeProblem)` with no filter, and
    `delete(Mastery)` with no `where` at all, which is the whole adaptive projection. Both
    are the same mistake the job tests made and conftest's rule forbids: a teardown scoped
    to a table rather than to the rows its test wrote. Caught by the canary in `conftest`
    on the first run after it was added, which is what that canary is for.

    `mastery` is rebuilt rather than deleted. It is a projection over `concept_evidence`,
    so once this test's evidence is gone the correct state is whatever the *remaining*
    evidence implies — and `recompute` is what says so. Emptying the table instead left the
    database in the one state the whole design calls impossible: a projection that does not
    match the rows it derives from.
    """
    with Session(get_engine()) as db:
        before = set(db.exec(select(PracticeProblem.id)).all())
    yield
    with Session(get_engine()) as db:
        ids = list(set(db.exec(select(PracticeProblem.id)).all()) - before)
        if ids:
            db.exec(delete(PracticeSolve).where(col(PracticeSolve.problem_id).in_(ids)))
            db.exec(
                delete(ConceptEvidence).where(col(ConceptEvidence.practice_problem_id).in_(ids))
            )
            db.exec(delete(PracticeProblem).where(col(PracticeProblem.id).in_(ids)))
        db.commit()
        recompute(db, single_user(db).id)


def client_with(script: ScriptedLeetCode) -> TestClient:
    app.dependency_overrides[get_leetcode_client] = lambda: script
    return sign_in(TestClient(app))


def do_import(client: TestClient, **body: Any) -> Any:
    return client.post("/api/v1/practice/import/leetcode", json=body)


def test_an_import_suggests_a_concept_but_never_accepts_it(imported):
    """The decision this whole feature turns on.

    `PATCH .../classification` refuses anything already resolved, because the evidence is
    written and evidence is immutable — so a wrong auto-accept could never be corrected.
    An import therefore lands `pending_classification` *with the concept selected*, and
    writes no evidence until a human confirms.
    """
    client = client_with(ScriptedLeetCode(CATALOGUE))
    response = do_import(client, slugs=["two-sum"])
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["with_a_suggestion"] == 1
    assert body["awaiting_confirmation"] == 1
    assert body["imported"][0]["suggested_concept_id"] == "hash-map-counting"

    with Session(get_engine()) as db:
        problem = db.get(PracticeProblem, body["imported"][0]["id"])
        assert problem.status == "pending_classification"
        assert problem.primary_concept_id == "hash-map-counting"
        # Held, so nothing is claimed about mastery yet.
        assert problem.due_at is None
        assert db.exec(select(ConceptEvidence)).all() == []


def test_confirming_an_import_is_what_writes_the_evidence(imported):
    client = client_with(ScriptedLeetCode(CATALOGUE))
    problem_id = do_import(client, slugs=["daily-temperatures"]).json()["imported"][0]["id"]

    resolved = client.patch(
        f"/api/v1/practice/problems/{problem_id}/classification",
        json={"primary_concept_id": "monotonic-stack", "secondary_concept_ids": []},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "active"
    assert resolved.json()["due_at"] is not None

    with Session(get_engine()) as db:
        evidence = db.exec(select(ConceptEvidence)).all()
        assert [row.concept_id for row in evidence] == ["monotonic-stack"]


def test_a_family_tag_imports_with_no_suggestion(imported):
    """`coin-change` is tagged `dynamic-programming` and `breadth-first-search`, and this
    taxonomy splits DP five ways. It arrives unsuggested rather than as a graph problem."""
    client = client_with(ScriptedLeetCode(CATALOGUE))
    body = do_import(client, slugs=["coin-change"]).json()

    row = body["imported"][0]
    assert row["suggested_concept_id"] is None
    assert "dynamic-programming" in row["why"]
    assert body["with_a_suggestion"] == 0


def test_one_bad_slug_does_not_lose_the_rest(imported):
    client = client_with(ScriptedLeetCode(CATALOGUE))
    body = do_import(
        client,
        slugs=[
            "two-sum",
            "no-such-problem",
            "https://example.com/problems/x",
            "daily-temperatures",
        ],
    ).json()

    assert sorted(row["slug"] for row in body["imported"]) == ["daily-temperatures", "two-sum"]
    assert len(body["skipped"]) == 2
    assert {row["reason"] for row in body["skipped"]} == {
        "LeetCode has no such problem",
        "not a LeetCode problem slug or URL",
    }


def test_importing_the_same_problem_twice_does_not_duplicate_it(imported):
    client = client_with(ScriptedLeetCode(CATALOGUE))
    do_import(client, slugs=["two-sum"])
    again = do_import(client, slugs=["two-sum"]).json()

    assert again["imported"] == []
    assert again["skipped"][0]["reason"] == "already logged"
    with Session(get_engine()) as db:
        # Counted by slug, not by counting the table. `select(PracticeProblem)` with no
        # filter asserts that this test is the only thing in the database, which was true
        # only because the teardown emptied the table first — the very over-deletion that
        # teardown no longer does.
        rows = db.exec(
            select(PracticeProblem).where(col(PracticeProblem.url).contains("two-sum"))
        ).all()
    assert len(rows) == 1


def test_a_url_and_its_bare_slug_are_the_same_problem(imported):
    client = client_with(ScriptedLeetCode(CATALOGUE))
    body = do_import(
        client, slugs=["https://leetcode.com/problems/two-sum/description/", "two-sum"]
    ).json()

    assert len(body["imported"]) == 1
    assert body["skipped"][0]["reason"] == "already logged"


def test_a_username_pulls_recent_solves(imported):
    script = ScriptedLeetCode(CATALOGUE, recent=["two-sum", "daily-temperatures"])
    body = do_import(client_with(script), username="someone").json()

    assert sorted(row["slug"] for row in body["imported"]) == ["daily-temperatures", "two-sum"]


def test_an_unreachable_leetcode_is_a_503_not_a_500(imported):
    class Broken(ScriptedLeetCode):
        def post(self, url, json, headers=None):
            return _Response({}, status_code=503)

    response = do_import(client_with(Broken({})), username="someone")
    assert response.status_code == 503
    assert response.json()["type"].endswith("/dependency-unavailable")


def test_an_import_with_neither_slugs_nor_a_username_is_refused(imported):
    # 400, not 422: FastAPI cannot tell a malformed body from a well-formed invalid one,
    # and this API resolves that ambiguity toward 400 for every schema failure.
    assert do_import(client_with(ScriptedLeetCode({}))).status_code == 400


def test_the_import_needs_a_session_cookie(imported):
    """A configured server with no cookie answers 401 — see the note in
    `test_corpus_routes_db.py`; without `use_settings()` this asserts 503 in CI."""
    use_settings()
    app.dependency_overrides[get_leetcode_client] = lambda: ScriptedLeetCode({})
    assert (
        TestClient(app)
        .post("/api/v1/practice/import/leetcode", json={"slugs": ["two-sum"]})
        .status_code
        == 401
    )
