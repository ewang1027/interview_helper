"""The LeetCode topic-tag mapping, and what it refuses to guess.

No network: every case is a canned tag set, because a test that reaches leetcode.com is a
test that fails when someone else deploys. The tag sets are real — copied from live
responses while building the table — and the three marked below are the ones that were
wrong first time and are the reason the rules they exercise exist.
"""

from __future__ import annotations

import httpx
import pytest

from api import leetcode
from api.leetcode import LeetCodeProblem, slug_from


def problem(slug: str, *tags: str) -> LeetCodeProblem:
    return LeetCodeProblem(slug=slug, title=slug, difficulty="Medium", topic_tags=tags)


@pytest.mark.parametrize(
    ("slug", "tags", "expected"),
    [
        ("two-sum", ("array", "hash-table"), "hash-map-counting"),
        (
            "longest-substring-without-repeating-characters",
            ("hash-table", "string", "sliding-window"),
            "sliding-window",
        ),
        (
            "merge-k-sorted-lists",
            ("linked-list", "divide-and-conquer", "heap-priority-queue", "merge-sort"),
            "heap-top-k",
        ),
        ("valid-parentheses", ("string", "stack"), "stack-simulation"),
        (
            "course-schedule",
            ("depth-first-search", "breadth-first-search", "graph", "topological-sort"),
            "topological-sort",
        ),
        ("daily-temperatures", ("array", "stack", "monotonic-stack"), "monotonic-stack"),
        ("single-number", ("array", "bit-manipulation"), "bit-tricks"),
        (
            "network-delay-time",
            (
                "depth-first-search",
                "breadth-first-search",
                "graph",
                "heap-priority-queue",
                "shortest-path",
            ),
            "shortest-path-weighted",
        ),
        (
            "sliding-window-maximum",
            ("array", "queue", "sliding-window", "heap-priority-queue", "monotonic-queue"),
            "deque-window",
        ),
        ("redundant-connection", ("depth-first-search", "union-find", "graph"), "union-find"),
    ],
)
def test_an_unambiguous_tag_names_the_concept(slug, tags, expected):
    assert problem(slug, *tags).concept()[0] == expected


def test_structure_outranks_traversal():
    """`validate-binary-search-tree` came out as a graph problem, because the traversal tag
    was ranked above the structure tag. It is a BST problem that happens to use DFS."""
    tags = ("tree", "depth-first-search", "binary-search-tree", "binary-tree")
    assert problem("validate-binary-search-tree", *tags).concept()[0] == "bst-invariants"


def test_a_dp_problem_co_tagged_with_its_alternative_solution_suggests_nothing():
    """`coin-change` imported as `graph-bfs`. LeetCode co-tags DP problems with the other
    solutions people post, and this taxonomy splits dynamic programming five ways — so the
    honest answer is that the metadata does not say which."""
    tags = ("array", "dynamic-programming", "breadth-first-search")
    concept, why = problem("coin-change", *tags).concept()
    assert concept is None
    assert "dynamic-programming" in why


def test_a_design_problem_is_not_its_data_structure():
    """`lru-cache` imported as `linked-list-manipulation`. `design` covers three concepts
    here, so a structure tag underneath it is not enough to choose."""
    tags = ("hash-table", "linked-list", "design", "doubly-linked-list")
    concept, why = problem("lru-cache", *tags).concept()
    assert concept is None
    assert "design" in why


def test_a_trie_is_still_a_trie_despite_being_tagged_design():
    """The blocker must not swallow a tag that is unambiguous on its own."""
    tags = ("hash-table", "string", "design", "trie")
    assert problem("implement-trie-prefix-tree", *tags).concept()[0] == "trie"


def test_memoization_survives_the_dp_blocker():
    tags = ("math", "dynamic-programming", "memoization")
    assert problem("climbing-stairs", *tags).concept()[0] == "memoization"


@pytest.mark.parametrize(
    "tags",
    [
        ("array", "string", "math"),
        ("array", "sorting", "quicksort"),
        ("string", "dynamic-programming", "longest-common-subsequence"),
        (),
    ],
)
def test_nothing_specific_suggests_nothing(tags):
    concept, why = problem("whatever", *tags).concept()
    assert concept is None
    assert why


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://leetcode.com/problems/two-sum/", "two-sum"),
        ("https://leetcode.com/problems/two-sum", "two-sum"),
        ("https://leetcode.com/problems/two-sum/description/", "two-sum"),
        ("http://leetcode.com/problems/two-sum/?envId=x", "two-sum"),
        ("leetcode.com/problems/word-ladder/", "word-ladder"),
        ("two-sum", "two-sum"),
        ("  Two-Sum  ", "two-sum"),
        # Not LeetCode problems, and not slugs.
        ("https://example.com/problems/two-sum/", None),
        ("https://neetcode.io/problems/two-sum", None),
        ("", None),
        ("not a slug!", None),
        ("../../etc/passwd", None),
    ],
)
def test_a_slug_is_read_out_of_whatever_was_pasted(text, expected):
    assert slug_from(text) == expected


# --- The network layer, with no network -------------------------------------------------


class FakeResponse:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> object:
        return self._payload


class FakeClient:
    """Records what was asked and answers from a script. Never opens a socket."""

    def __init__(self, *answers: object, error: Exception | None = None) -> None:
        self._answers = list(answers)
        self._error = error
        self.calls: list[dict] = []

    def post(self, url: str, json: dict, headers: dict | None = None):
        self.calls.append(json)
        if self._error is not None:
            raise self._error
        return self._answers.pop(0) if self._answers else FakeResponse({"data": {}})


def question_payload(*tags: str, title: str = "A Problem", difficulty: str = "Medium"):
    return FakeResponse(
        {
            "data": {
                "question": {
                    "title": title,
                    "difficulty": difficulty,
                    "topicTags": [{"slug": tag} for tag in tags],
                }
            }
        }
    )


def test_a_problem_is_read_out_of_the_response():
    client = FakeClient(question_payload("sliding-window", title="Longest Substring"))
    found = leetcode.problem("longest-substring", client=client)

    assert found is not None
    assert found.title == "Longest Substring"
    assert found.difficulty == "Medium"
    assert found.concept()[0] == "sliding-window"
    assert found.url == "https://leetcode.com/problems/longest-substring/"


def test_the_query_asks_for_metadata_and_nothing_else():
    """The rule this feature lives under is that no problem *statement* is fetched, and
    the projection is what enforces it. A field added here that could carry one would
    move this feature from inside docs/PRACTICE_LOG.md's rule to an exception to it."""
    client = FakeClient(question_payload("array"))
    leetcode.problem("two-sum", client=client)

    sent = client.calls[0]["query"]
    assert "topicTags" in sent and "difficulty" in sent and "title" in sent
    for forbidden in ("content", "questionBody", "hints", "solution", "exampleTestcases"):
        assert forbidden not in sent, f"the projection asks for {forbidden!r}"


def test_an_unknown_slug_is_none_rather_than_an_error():
    """One bad slug in a pasted list must not fail the batch."""
    assert (
        leetcode.problem("nope", client=FakeClient(FakeResponse({"data": {"question": None}})))
        is None
    )


def test_a_slug_that_is_not_a_slug_never_reaches_the_network():
    client = FakeClient()
    assert leetcode.problem("../../etc/passwd", client=client) is None
    assert client.calls == []


def test_a_non_200_is_an_error_naming_the_status():
    client = FakeClient(FakeResponse({}, status_code=403))
    with pytest.raises(leetcode.LeetCodeError, match="403"):
        leetcode.problem("two-sum", client=client)


def test_graphql_errors_surface_rather_than_being_read_as_no_data():
    client = FakeClient(FakeResponse({"errors": [{"message": "rate limited"}]}))
    with pytest.raises(leetcode.LeetCodeError, match="rate limited"):
        leetcode.problem("two-sum", client=client)


def test_a_transport_failure_says_it_could_not_reach_leetcode():
    client = FakeClient(error=httpx.ConnectError("no route to host"))
    with pytest.raises(leetcode.LeetCodeError, match="could not reach"):
        leetcode.problem("two-sum", client=client)


def test_recent_solves_are_read_newest_first():
    client = FakeClient(
        FakeResponse(
            {
                "data": {
                    "recentAcSubmissionList": [
                        {"title": "Two Sum", "titleSlug": "two-sum", "timestamp": "1700000000"},
                        {
                            "title": "Word Ladder",
                            "titleSlug": "word-ladder",
                            "timestamp": "1699000000",
                        },
                    ]
                }
            }
        )
    )
    solves = leetcode.recent_solves("someone", client=client)

    assert [s.slug for s in solves] == ["two-sum", "word-ladder"]
    assert solves[0].solved_at == 1_700_000_000


def test_a_profile_that_does_not_exist_is_an_error_not_an_empty_list():
    """LeetCode answers `null` for an unknown user and `[]` for one who has solved
    nothing. Reporting the first as "no recent solves" would tell somebody their username
    worked when it did not."""
    client = FakeClient(FakeResponse({"data": {"recentAcSubmissionList": None}}))
    with pytest.raises(leetcode.LeetCodeError, match="no public profile"):
        leetcode.recent_solves("ghost", client=client)

    empty = FakeClient(FakeResponse({"data": {"recentAcSubmissionList": []}}))
    assert leetcode.recent_solves("newcomer", client=empty) == []


def test_the_session_helper_yields_an_injected_client_unchanged():
    client = FakeClient()
    with leetcode.session(client) as yielded:
        assert yielded is client
