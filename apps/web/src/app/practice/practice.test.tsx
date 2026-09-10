import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import Practice from "./page";
import { fixtures, renderPage, stubFetch } from "@/test/harness";

vi.mock("next/navigation", () => ({ usePathname: () => "/practice", useRouter: () => ({ push: vi.fn() }) }));

/**
 * The practice log page.
 *
 * The state it is designed around is `pending_classification`: with no model provider
 * reachable, every logged or imported problem lands there, and nothing counts until a
 * human confirms. These assert the page says so rather than looking finished.
 */

function problem(over: Record<string, unknown> = {}) {
  return {
    id: "p1",
    title: "Two Sum",
    url: "https://leetcode.com/problems/two-sum/",
    source_site: "leetcode",
    notes: null,
    difficulty_label: "Easy",
    labels: [],
    primary_concept_id: null,
    primary_concept_name: null,
    topic: null,
    lists: [],
    secondary_concept_ids: [],
    classification: { confidence: 0, model: null, auto_accepted: false },
    status: "pending_classification",
    solve_count: 1,
    stability_days: null,
    due_at: null,
    graduated_at: null,
    created_at: "2026-08-25T00:00:00Z",
    ...over,
  };
}

const BASE = {
  "/api/v1/practice/review-queue": fixtures.emptyQueue,
  "/api/v1/practice/problems": { problems: [], next_cursor: null },
  "/api/v1/concepts": fixtures.concepts,
};

afterEach(() => vi.unstubAllGlobals());

describe("practice log", () => {
  it("says an untagged problem counts for nothing yet", async () => {
    stubFetch({
      ...BASE,
      "/api/v1/practice/problems": { problems: [problem()], next_cursor: null },
    });
    renderPage(<Practice />);

    expect(await screen.findByText("needs a tag")).toBeInTheDocument();
    expect(await screen.findByText("these feed nothing until confirmed")).toBeInTheDocument();
  });

  it("distinguishes a suggestion from having no idea", async () => {
    // An import arrives with a concept selected but unconfirmed. That is a different
    // state from a problem nothing could classify, and the row must not claim otherwise.
    stubFetch({
      ...BASE,
      "/api/v1/practice/problems": {
        problems: [problem({ primary_concept_id: "hash-map-counting" })],
        next_cursor: null,
      },
    });
    renderPage(<Practice />);

    expect(await screen.findByText("suggested — confirm it")).toBeInTheDocument();
  });

  it("offers to confirm every suggestion at once, and says what that means", async () => {
    stubFetch({
      ...BASE,
      "/api/v1/practice/problems": {
        problems: [
          problem({ id: "p1", primary_concept_id: "hash-map-counting" }),
          problem({ id: "p2", title: "Coin Change", primary_concept_id: null }),
        ],
        next_cursor: null,
      },
    });
    renderPage(<Practice />);

    // Only the one with a suggestion is offered — never the one nothing named.
    expect(await screen.findByRole("button", { name: /Confirm all 1/ })).toBeInTheDocument();
    expect(
      await screen.findByText(/Confirming writes evidence, and evidence is immutable/),
    ).toBeInTheDocument();
  });

  it("does not offer a bulk confirm when nothing is suggested", async () => {
    stubFetch({
      ...BASE,
      "/api/v1/practice/problems": { problems: [problem()], next_cursor: null },
    });
    renderPage(<Practice />);

    await screen.findByText("needs a tag");
    expect(screen.queryByRole("button", { name: /Confirm all/ })).not.toBeInTheDocument();
  });

  it("confirms each suggestion against the concept the tags named", async () => {
    const patched: string[] = [];
    stubFetch({
      ...BASE,
      "/api/v1/practice/problems/p1/classification": (url: string) => {
        patched.push(url);
        return problem({ status: "active", primary_concept_id: "hash-map-counting" });
      },
      "/api/v1/practice/problems": {
        problems: [problem({ primary_concept_id: "hash-map-counting" })],
        next_cursor: null,
      },
    });
    renderPage(<Practice />);

    await userEvent.click(await screen.findByRole("button", { name: /Confirm all 1/ }));
    await waitFor(() => expect(patched).toHaveLength(1));
  });

  it("will not log a problem without both a title and a URL", async () => {
    stubFetch(BASE);
    renderPage(<Practice />);

    const log = await screen.findByRole("button", { name: "Log it" });
    expect(log).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/^Title/), "Two Sum");
    expect(log).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/^URL/), "https://leetcode.com/problems/two-sum/");
    expect(log).toBeEnabled();
  });

  it("reports what an import suggested and what it skipped", async () => {
    stubFetch({
      ...BASE,
      "/api/v1/practice/import/leetcode": {
        imported: [
          {
            id: "p1",
            slug: "two-sum",
            title: "Two Sum",
            difficulty: "Easy",
            source_site: "leetcode",
            neetcode: null,
            suggested_concept_id: "hash-map-counting",
            why: "LeetCode tags this 'hash-table'",
            topic_tags: ["array", "hash-table"],
          },
          {
            id: "p2",
            slug: "coin-change",
            title: "Coin Change",
            difficulty: "Medium",
            source_site: "leetcode",
            neetcode: null,
            suggested_concept_id: null,
            why: "tagged 'dynamic-programming', which this taxonomy splits several ways",
            topic_tags: ["dynamic-programming"],
          },
        ],
        skipped: [{ input: "nope", slug: "nope", reason: "LeetCode has no such problem" }],
        awaiting_confirmation: 2,
        with_a_suggestion: 1,
      },
    });
    renderPage(<Practice />);

    await userEvent.type(await screen.findByLabelText(/Paste links or slugs/), "two-sum");
    await userEvent.click(screen.getByRole("button", { name: "Import" }));

    // The count of suggestions, and the fact that none of it counts yet.
    expect(await screen.findByText(/with a concept already suggested/)).toBeInTheDocument();
    expect(await screen.findByText(/None counts until confirmed/)).toBeInTheDocument();
    expect(await screen.findByText("hash-map-counting")).toBeInTheDocument();
    expect(await screen.findByText("no suggestion")).toBeInTheDocument();
    expect(await screen.findByText("1 skipped")).toBeInTheDocument();
  });

  it("says which imported problems came from NeetCode, and which list", async () => {
    // A NeetCode link imports the LeetCode problem it names — `duplicate-integer` is
    // `contains-duplicate` — so the row is titled by LeetCode and badged by NeetCode.
    stubFetch({
      ...BASE,
      "/api/v1/practice/import/leetcode": {
        imported: [
          {
            id: "p1",
            slug: "contains-duplicate",
            title: "Contains Duplicate",
            difficulty: "Easy",
            source_site: "neetcode",
            neetcode: {
              slug: "duplicate-integer",
              pattern: "Arrays & Hashing",
              lists: ["blind75", "neetcode150", "neetcode250"],
            },
            suggested_concept_id: "hash-map-counting",
            why: "LeetCode tags this 'hash-table'",
            topic_tags: ["array", "hash-table"],
          },
        ],
        skipped: [],
        awaiting_confirmation: 1,
        with_a_suggestion: 1,
      },
    });
    renderPage(<Practice />);

    await userEvent.type(
      await screen.findByLabelText(/Paste links or slugs/),
      "https://neetcode.io/problems/duplicate-integer",
    );
    await userEvent.click(screen.getByRole("button", { name: "Import" }));

    expect(await screen.findByText("Contains Duplicate")).toBeInTheDocument();
    expect(await screen.findByText("NeetCode 150")).toBeInTheDocument();
  });

  it("cannot import with neither a paste nor a username", async () => {
    stubFetch(BASE);
    renderPage(<Practice />);
    expect(await screen.findByRole("button", { name: "Import" })).toBeDisabled();
  });

  it("shows the API's own refusal rather than a generic failure", async () => {
    stubFetch({
      ...BASE,
      "/api/v1/practice/import/leetcode": {
        __status: 503,
        type: "https://interview-helper.local/errors/dependency-unavailable",
        title: "A service this depends on is unavailable",
        detail: "LeetCode: leetcode.com answered 403",
        status: 503,
      },
    });
    renderPage(<Practice />);

    await userEvent.type(await screen.findByLabelText(/Paste links or slugs/), "two-sum");
    await userEvent.click(screen.getByRole("button", { name: "Import" }));

    expect(await screen.findByText("dependency-unavailable")).toBeInTheDocument();
    expect(await screen.findByText(/leetcode.com answered 403/)).toBeInTheDocument();
  });

  it("files a problem under its topic, and filters and groups by it", async () => {
    stubFetch({
      ...BASE,
      "/api/v1/practice/problems": {
        problems: [
          problem({
            id: "p1",
            title: "Merge Intervals",
            status: "active",
            primary_concept_id: "interval-merge",
            primary_concept_name: "Merging and inserting intervals",
            topic: "Intervals",
            lists: ["blind75", "neetcode150"],
            difficulty_label: "Medium",
          }),
          problem({
            id: "p2",
            title: "Two Sum",
            status: "active",
            primary_concept_id: "hash-map-counting",
            primary_concept_name: "Hash map counting and lookup",
            topic: "Arrays & Hashing",
            difficulty_label: "Easy",
          }),
        ],
        next_cursor: null,
      },
    });
    renderPage(<Practice />);

    // The row shows the concept by name and the list it is on, not a bare id.
    expect(await screen.findByText("· Merging and inserting intervals")).toBeInTheDocument();
    expect(screen.getByText("NeetCode 150")).toBeInTheDocument();

    // Filter options come from the log itself, with counts.
    await userEvent.selectOptions(screen.getByLabelText("Topic"), "Intervals");
    expect(screen.getByText("1 of 2 match")).toBeInTheDocument();
    expect(screen.queryByText("Two Sum")).not.toBeInTheDocument();

    await userEvent.click(screen.getByText("Clear"));
    await userEvent.selectOptions(screen.getByLabelText("Group by"), "topic");
    const section = screen.getByRole("region", { name: "Arrays & Hashing" });
    expect(within(section).getByText("Two Sum")).toBeInTheDocument();
  });

  it("searches across title, concept and label, and says when nothing matches", async () => {
    stubFetch({
      ...BASE,
      "/api/v1/practice/problems": {
        problems: [
          problem({ id: "p1", title: "Merge Intervals", labels: ["Blind 75"] }),
          problem({ id: "p2", title: "Two Sum", primary_concept_name: "Hash map counting and lookup" }),
        ],
        next_cursor: null,
      },
    });
    renderPage(<Practice />);

    const search = await screen.findByLabelText("Search problems");
    await userEvent.type(search, "blind");
    expect(screen.getByText("Merge Intervals")).toBeInTheDocument();
    expect(screen.queryByText("Two Sum")).not.toBeInTheDocument();

    await userEvent.clear(search);
    await userEvent.type(search, "hash map");
    expect(screen.getByText("Two Sum")).toBeInTheDocument();

    await userEvent.clear(search);
    await userEvent.type(search, "nothing like this");
    expect(screen.getByText("Nothing matches")).toBeInTheDocument();
    // The log is not empty — the view of it is — so the search box must stay.
    expect(screen.getByLabelText("Search problems")).toBeInTheDocument();
  });

  it("adds and removes a label on the row, sending the whole list", async () => {
    const sent: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn());
    stubFetch({
      ...BASE,
      "/api/v1/practice/problems": {
        problems: [problem({ id: "p1", labels: ["redo"] })],
        next_cursor: null,
      },
      "/api/v1/practice/problems/p1": problem({ id: "p1", labels: ["redo", "Blind 75"] }),
    });
    const original = globalThis.fetch;
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "PATCH") sent.push(JSON.parse(String(init.body)));
      return original(input, init);
    });
    renderPage(<Practice />);

    await userEvent.click(await screen.findByLabelText("Add a label to Two Sum"));
    await userEvent.type(screen.getByLabelText("New label for Two Sum"), "Blind 75{Enter}");
    await waitFor(() => expect(sent).toEqual([{ labels: ["redo", "Blind 75"] }]));

    // The list is refetched after every edit, and the stub above still answers `["redo"]`
    // for it — so removing that one sends the whole list minus it, which is empty.
    await userEvent.click(screen.getByLabelText("Remove label redo from Two Sum"));
    await waitFor(() => expect(sent[1]).toEqual({ labels: [] }));
  });

  it("loads the whole log across cursor pages, so the counts are the log's", async () => {
    stubFetch({
      ...BASE,
      "/api/v1/practice/problems": (url: string) =>
        url.includes("cursor=")
          ? { problems: [problem({ id: "p2", title: "Second page" })], next_cursor: null }
          : { problems: [problem({ id: "p1", title: "First page" })], next_cursor: "p1" },
    });
    renderPage(<Practice />);

    expect(await screen.findByText("Second page")).toBeInTheDocument();
    expect(screen.getByText("First page")).toBeInTheDocument();
    expect(screen.getByText("2 problems")).toBeInTheDocument();
  });

  it("counts what is due separately from what is logged", async () => {
    stubFetch({
      ...BASE,
      "/api/v1/practice/review-queue": {
        as_of: "2026-08-25T00:00:00Z",
        due: [
          {
            ...problem({ id: "p9", status: "active", primary_concept_id: "trie", solve_count: 3 }),
            due_at: new Date(Date.now() - 3 * 86_400_000).toISOString(),
            days_overdue: 3,
          },
        ],
      },
    });
    renderPage(<Practice />);

    expect(await screen.findByText(/3d overdue/)).toBeInTheDocument();
    expect(await screen.findByText(/solved 3×/)).toBeInTheDocument();
    // "Due now" counts the queue, not the problem list, which is empty here.
    expect(await screen.findByText("Due now")).toBeInTheDocument();
  });
});
