"""The LeetCode topic-tag mapping, and what it refuses to guess.

No network: every case is a canned tag set, because a test that reaches leetcode.com is a
test that fails when someone else deploys. The tag sets are real — copied from live
responses while building the table — and the three marked below are the ones that were
wrong first time and are the reason the rules they exercise exist.
"""

from __future__ import annotations

import pytest

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
