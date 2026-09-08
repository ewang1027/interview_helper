"""The NeetCode catalogue, and which slug belongs to which site.

No network anywhere: the mapping is a file this repo ships, and that is the point of it —
`scripts/build_neetcode_catalogue.py` is the only thing that ever talks to neetcode.io.

What these guard is the one way this feature can be quietly wrong. A mapping that resolves
the wrong problem logs a solve you did not do, against a concept you did not exercise, and
`concept_evidence` is immutable — so the mappings asserted below are named ones, checked by
hand against both sites, rather than a count that would pass on a shuffled table.
"""

from __future__ import annotations

import pytest

from api import leetcode, neetcode
from api.neetcode import SLUG, catalogue, lookup, slug_from

# The three renames that broke a naive "neetcode.io/problems/<leetcode slug>" assumption
# first, and the shape of the other 71: NeetCode retitles a problem and its slug follows.
RENAMED = [
    ("duplicate-integer", "contains-duplicate"),
    ("two-integer-sum", "two-sum"),
    ("is-anagram", "valid-anagram"),
    ("top-k-elements-in-list", "top-k-frequent-elements"),
    ("find-duplicate-integer", "find-the-duplicate-number"),
]


@pytest.mark.parametrize(("neetcode_slug", "leetcode_slug"), RENAMED)
def test_a_renamed_problem_resolves_to_the_leetcode_one(neetcode_slug, leetcode_slug):
    entry = lookup(neetcode_slug)
    assert entry is not None
    assert entry.leetcode_slug == leetcode_slug
    assert entry.renamed


def test_the_lists_are_the_sizes_they_are_named_after():
    """A bundle whose shape changed just enough to still parse is the failure this catches,
    and it is the same check the build script runs before writing the file."""
    rows = catalogue().values()
    for name, expected in (("blind75", 75), ("neetcode150", 150), ("neetcode250", 250)):
        assert sum(1 for row in rows if name in row.lists) == expected, name


def test_every_row_is_a_pair_of_real_slugs():
    for row in catalogue().values():
        assert SLUG.match(row.neetcode_slug), row.neetcode_slug
        assert SLUG.match(row.leetcode_slug), row.leetcode_slug
        assert row.title and row.pattern


def test_no_two_rows_claim_the_same_problem():
    slugs = [row.leetcode_slug for row in catalogue().values()]
    assert len(set(slugs)) == len(slugs)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://neetcode.io/problems/duplicate-integer", "duplicate-integer"),
        ("https://neetcode.io/problems/duplicate-integer/", "duplicate-integer"),
        ("neetcode.io/problems/is-anagram", "is-anagram"),
        ("https://neetcode.io/problems/is-anagram?list=neetcode150", "is-anagram"),
        # What the site's address bar actually holds while you are solving one: a tab
        # segment after the slug and the list you came from in the query.
        (
            "https://neetcode.io/problems/reverse-a-linked-list/question?list=neetcode150",
            "reverse-a-linked-list",
        ),
        ("https://neetcode.io/problems/is-anagram/solution", "is-anagram"),
        ("  https://neetcode.io/problems/Two-Integer-Sum  ", "two-integer-sum"),
        # A name only NeetCode uses, typed on its own.
        ("duplicate-integer", "duplicate-integer"),
        # LeetCode's own slug for a problem NeetCode calls `two-integer-sum` — LeetCode's
        # to import, and `api.leetcode` is where it goes.
        ("two-sum", None),
        ("https://leetcode.com/problems/two-sum/", None),
        ("", None),
        ("not a slug!", None),
        ("../../etc/passwd", None),
    ],
)
def test_a_neetcode_slug_is_read_out_of_whatever_was_pasted(text, expected):
    assert slug_from(text) == expected


def test_a_link_neetcode_added_after_the_catalogue_is_still_read_as_neetcodes():
    """Separating "not NeetCode's" from "NeetCode's, and this build has not heard of it"
    is what lets the import say *paste the LeetCode link* instead of "unreadable"."""
    slug = slug_from("https://neetcode.io/problems/some-problem-added-last-week")
    assert slug == "some-problem-added-last-week"
    assert lookup(slug) is None


def test_a_bare_slug_shared_with_leetcode_stays_leetcodes():
    """514 of the 588 slugs are the same on both sites. Typed bare, they read as LeetCode's
    — the same problem either way, so the rule decides which site is recorded, not what."""
    shared = next(row for row in catalogue().values() if not row.renamed)
    assert slug_from(shared.neetcode_slug) is None
    assert leetcode.slug_from(shared.neetcode_slug) == shared.leetcode_slug


def test_the_url_points_back_at_neetcode():
    entry = lookup("duplicate-integer")
    assert entry is not None
    assert entry.url == "https://neetcode.io/problems/duplicate-integer/"


def test_the_catalogue_records_when_it_was_taken():
    assert neetcode.extracted_at()
