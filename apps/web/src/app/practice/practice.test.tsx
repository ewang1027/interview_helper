import { screen, waitFor } from "@testing-library/react";
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
    primary_concept_id: null,
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
            suggested_concept_id: "hash-map-counting",
            why: "LeetCode tags this 'hash-table'",
            topic_tags: ["array", "hash-table"],
          },
          {
            id: "p2",
            slug: "coin-change",
            title: "Coin Change",
            difficulty: "Medium",
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
