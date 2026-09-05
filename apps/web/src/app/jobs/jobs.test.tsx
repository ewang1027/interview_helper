import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import Jobs from "./page";
import { renderPage, stubFetch } from "@/test/harness";

vi.mock("next/navigation", () => ({
  usePathname: () => "/jobs",
  useRouter: () => ({ push: vi.fn() }),
}));

/**
 * The applications page.
 *
 * The assertions worth making here are the ones about *what the numbers mean*,
 * because the page is at its most misleading when it looks finished:
 *
 * - the funnel counts where applications **reached**, so a rejection after an
 *   onsite must still show in the onsite rung,
 * - an import that did not research says so, since researched and unresearched
 *   rows are indistinguishable on the board,
 * - and an untagged row is marked rather than quietly counted as `other`.
 */

const CATALOG = {
  categories: {
    swe: ["backend", "frontend"],
    ai: ["ml_engineering"],
    quant: ["quant_trading"],
    other: ["unclassified"],
  },
  ladder: ["applied", "oa", "phone_screen", "round_1", "round_2", "final", "offer"],
  terminal: ["rejected", "withdrawn", "ghosted"],
  stage_labels: {
    applied: "Applied",
    oa: "Online assessment",
    phone_screen: "Phone screen",
    round_1: "First round",
    round_2: "Second round",
    final: "Final / onsite",
    offer: "Offer",
    rejected: "Rejected",
    withdrawn: "Withdrawn",
    ghosted: "Ghosted",
  },
};

function step(stage: string, label: string, reached: number, conversion = 1) {
  return { stage, label, reached, share: reached / 4, conversion };
}

const STATS = {
  total: 4,
  open: 2,
  offers: 0,
  rejected: 1,
  responded: 3,
  response_rate: 0.75,
  needs_review: 1,
  funnel: [
    step("applied", "Applied", 4),
    step("oa", "Online assessment", 3, 0.75),
    step("phone_screen", "Phone screen", 2, 0.667),
    step("round_1", "First round", 2, 1),
    step("round_2", "Second round", 1, 0.5),
    step("final", "Final / onsite", 1, 1),
    step("offer", "Offer", 0, 0),
  ],
  by_category: {
    swe: { total: 3, active: 2, offers: 0, responded: 2, subcategories: { backend: 3 } },
    quant: { total: 1, active: 0, offers: 0, responded: 1, subcategories: { quant_trading: 1 } },
  },
  by_stage: { applied: 1, oa: 1, final: 1, rejected: 1 },
};

function application(over: Record<string, unknown> = {}) {
  return {
    id: "j1",
    company: "Aurora Labs",
    role: "Backend Engineer",
    location: "Boston",
    url: null,
    source: "paste",
    category: "swe",
    subcategory: "backend",
    classification_confidence: 0.9,
    classification_model: "claude-sonnet-5",
    status: "tracked",
    current_stage: "rejected",
    current_stage_label: "Rejected",
    furthest_stage: "final",
    outcome: "rejected",
    notes: null,
    applied_at: "2026-07-04T00:00:00Z",
    updated_at: "2026-08-20T00:00:00Z",
    ...over,
  };
}

const BASE = {
  "/api/v1/jobs/catalog": CATALOG,
  "/api/v1/jobs/stats": STATS,
  "/api/v1/jobs": { applications: [application()], count: 1 },
};

afterEach(() => vi.unstubAllGlobals());

describe("applications", () => {
  it("leads with the response rate and its denominator", async () => {
    // A rate with an invisible denominator reads as more solid than it is —
    // docs/WEB.md's rule about evidence counts, applied to this page.
    stubFetch(BASE);
    renderPage(<Jobs />);

    expect(await screen.findByText("75%")).toBeInTheDocument();
    expect(await screen.findByText("3 of 4")).toBeInTheDocument();
  });

  it("keeps a rejected application in the rungs it reached", async () => {
    // The one number on this page that would be wrong in a way nobody notices.
    // The single application shown is `rejected` and its furthest stage is
    // `final`, so the final rung must not read zero.
    stubFetch(BASE);
    renderPage(<Jobs />);

    // Scoped to the funnel: "Final / onsite" is also an option in every row's
    // stage control, and an unscoped query matches both.
    const funnel = await screen.findByLabelText("Application funnel");
    const onsite = within(funnel).getByText("Final / onsite").closest("li")!;
    expect(onsite).toHaveTextContent("1 / 4");
    expect(onsite).not.toHaveTextContent("0 / 4");
  });

  it("says when an import did not research, and why", async () => {
    // Researched and unresearched rows look identical on the board. Hiding the
    // difference hides the only thing that tells them apart.
    stubFetch({
      ...BASE,
      "/api/v1/jobs/import": {
        created: 2,
        duplicates: 0,
        researched: false,
        research_skipped: "2 rows is at or below the threshold of 10",
        model: "claude-sonnet-5",
        cost_usd: 0.004,
        web_searches: 0,
        applications: [],
      },
    });
    renderPage(<Jobs />);

    await userEvent.type(
      await screen.findByLabelText("Applications to import"),
      "Aurora Labs, backend",
    );
    await userEvent.click(screen.getByRole("button", { name: "Import" }));

    expect(await screen.findByText("2 added")).toBeInTheDocument();
    expect(
      await screen.findByText(/No web research: 2 rows is at or below the threshold of 10/),
    ).toBeInTheDocument();
  });

  it("marks a row whose tag was proposed and nothing was proposed for", async () => {
    stubFetch({
      ...BASE,
      "/api/v1/jobs": {
        applications: [
          application({
            id: "untagged",
            company: "Calder & Finch",
            status: "pending_classification",
            category: null,
            subcategory: null,
            classification_confidence: 0.2,
          }),
        ],
        count: 1,
      },
    });
    renderPage(<Jobs />);

    expect(await screen.findByText("needs a tag")).toBeInTheDocument();
    expect(await screen.findByLabelText("Tag Calder & Finch")).toHaveValue("");
  });

  it("confirms the proposed tag in one click, without changing it first", async () => {
    // The bug this pins: the tag control was a <select> pre-set to the proposed value,
    // so choosing that value fired no `change` event and the proposal could not be
    // accepted at all — you had to pick some *other* tag first. Confirming is the common
    // case, so it is a button, and it sends the proposed sub-category unchanged.
    stubFetch({
      ...BASE,
      "/api/v1/jobs": {
        applications: [
          application({ status: "pending_classification", classification_confidence: 0.45 }),
        ],
        count: 1,
      },
    });
    renderPage(<Jobs />);

    await userEvent.click(await screen.findByRole("button", { name: /Confirm Backend/ }));

    const patch = vi
      .mocked(fetch)
      .mock.calls.find(([, init]) => (init as RequestInit | undefined)?.method === "PATCH");
    expect(patch).toBeDefined();
    expect(String(patch![0])).toContain("/api/v1/jobs/j1/classification");
    expect(JSON.parse(String((patch![1] as RequestInit).body))).toEqual({
      subcategory: "backend",
    });
  });

  it("never leaves the tag select sitting on a real tag", async () => {
    // Structural, not cosmetic: a <select> fires no `change` for the option it already
    // shows, so any tag it displays is an option nobody can pick. Pinned at the
    // placeholder, every choice is a change.
    stubFetch({
      ...BASE,
      "/api/v1/jobs": {
        applications: [application({ status: "pending_classification" })],
        count: 1,
      },
    });
    renderPage(<Jobs />);

    const select = await screen.findByLabelText("Tag Aurora Labs");
    expect(select).toHaveValue("");
    expect(within(select).getByText("Change…")).toBeInTheDocument();
  });

  it("offers every stage from the served catalog, not a hard-coded list", async () => {
    // The enum the model is constrained to and the options a person picks from
    // have to be one list, and the catalog endpoint is what makes them one.
    stubFetch(BASE);
    renderPage(<Jobs />);

    const control = await screen.findByLabelText("Move Aurora Labs to a stage");
    for (const label of ["Online assessment", "Final / onsite", "Ghosted"]) {
      expect(within(control).getByText(label)).toBeInTheDocument();
    }
  });

  it("narrows the board to a search, matching terms in any order", async () => {
    // The reason the search exists: finding one row to move it along, in a list long
    // enough that scrolling for it is the slow part.
    stubFetch({
      ...BASE,
      "/api/v1/jobs": {
        applications: [
          application(),
          application({ id: "j2", company: "Calder & Finch", role: "Quant Trader" }),
          application({ id: "j3", company: "Meridian", role: "Backend Engineer" }),
        ],
        count: 3,
      },
    });
    renderPage(<Jobs />);

    await userEvent.type(await screen.findByLabelText("Search applications"), "backend meridian");

    expect(await screen.findByLabelText("Move Meridian to a stage")).toBeInTheDocument();
    expect(screen.queryByLabelText("Move Calder & Finch to a stage")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Move Aurora Labs to a stage")).not.toBeInTheDocument();
    // The denominator stays visible: "1 shown" and "1 of 3 match" are different claims.
    expect(screen.getByText("1 of 3 match · showing 1")).toBeInTheDocument();
  });

  it("says a search matched nothing, without claiming the board is empty", async () => {
    // "No applications yet" would be false and unrecoverable — the search box has to
    // survive its own empty result or there is no way back to the list.
    stubFetch(BASE);
    renderPage(<Jobs />);

    const search = await screen.findByLabelText("Search applications");
    await userEvent.type(search, "nowhere");

    expect(await screen.findByText(/Nothing matches/)).toBeInTheDocument();
    expect(screen.queryByText("No applications yet")).not.toBeInTheDocument();
    expect(search).toBeInTheDocument();
  });

  it("shows twenty rows, then ten more per click", async () => {
    // A board that silently stops at twenty looks like a complete list of twenty, so
    // the count and the button both name the numbers they are working with.
    const many = Array.from({ length: 35 }, (_, index) =>
      application({ id: `j${index}`, company: `Company ${index}` }),
    );
    stubFetch({ ...BASE, "/api/v1/jobs": { applications: many, count: 35 } });
    renderPage(<Jobs />);

    const rows = () => screen.getAllByLabelText(/^Move Company \d+ to a stage$/);
    await screen.findByText("Showing 20 of 35");
    expect(rows()).toHaveLength(20);

    await userEvent.click(screen.getByRole("button", { name: "Load 10 more" }));
    expect(rows()).toHaveLength(30);

    // The tail says how many are actually left, rather than promising ten it cannot give.
    await userEvent.click(screen.getByRole("button", { name: "Load 5 more" }));
    expect(rows()).toHaveLength(35);
    expect(screen.queryByRole("button", { name: /Load .* more/ })).not.toBeInTheDocument();
    expect(screen.getByText("Showing 35 of 35")).toBeInTheDocument();
  });

  it("collapses ten at a time, no further than the twenty it opened with", async () => {
    // The mirror of "load more", and the two have to agree about the list actually on
    // screen: the last "more" of a 35-row list takes the counter to 40, so a "less"
    // computed off that counter would hide five rows while promising ten.
    const many = Array.from({ length: 35 }, (_, index) =>
      application({ id: `j${index}`, company: `Company ${index}` }),
    );
    stubFetch({ ...BASE, "/api/v1/jobs": { applications: many, count: 35 } });
    renderPage(<Jobs />);

    const rows = () => screen.getAllByLabelText(/^Move Company \d+ to a stage$/);
    const less = () => screen.queryByRole("button", { name: /Load .* less/ });

    // Nothing to collapse yet, so the control is absent rather than present and inert.
    await screen.findByText("Showing 20 of 35");
    expect(less()).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Load 10 more" }));
    await userEvent.click(screen.getByRole("button", { name: "Load 5 more" }));
    expect(rows()).toHaveLength(35);

    await userEvent.click(screen.getByRole("button", { name: "Load 10 less" }));
    expect(rows()).toHaveLength(25);

    // Five left above the floor, and the label says five rather than ten.
    await userEvent.click(screen.getByRole("button", { name: "Load 5 less" }));
    expect(rows()).toHaveLength(20);
    expect(screen.getByText("Showing 20 of 35")).toBeInTheDocument();
    expect(less()).not.toBeInTheDocument();
  });

  it("leaves an expanded board expanded after a stage change", async () => {
    // The workflow the search and the paging exist for is *moving* a row, and a stage
    // change refetches the list. If that collapsed the board back to twenty, updating
    // row thirty would scroll the row you were working on out of existence — so the
    // window survives new data, and only a filter change resets it.
    const many = Array.from({ length: 35 }, (_, index) =>
      application({ id: `j${index}`, company: `Company ${index}` }),
    );
    stubFetch({ ...BASE, "/api/v1/jobs": { applications: many, count: 35 } });
    renderPage(<Jobs />);

    await screen.findByText("Showing 20 of 35");
    await userEvent.click(screen.getByRole("button", { name: "Load 10 more" }));

    await userEvent.selectOptions(
      screen.getByLabelText("Move Company 25 to a stage"),
      "phone_screen",
    );

    // Asserted, so the test cannot pass by the mutation never having fired: the board
    // is only proven to survive a refetch if a refetch was actually provoked.
    await vi.waitFor(() =>
      expect(
        vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith("/jobs/j25/stage")),
      ).toBe(true),
    );
    expect(await screen.findByText("Showing 30 of 35")).toBeInTheDocument();
    expect(screen.getAllByLabelText(/^Move Company \d+ to a stage$/)).toHaveLength(30);
  });

  it("renders an empty board without dividing by zero", async () => {
    stubFetch({
      ...BASE,
      "/api/v1/jobs/stats": {
        ...STATS,
        total: 0,
        open: 0,
        responded: 0,
        response_rate: 0,
        needs_review: 0,
        rejected: 0,
        funnel: STATS.funnel.map((row) => ({ ...row, reached: 0, share: 0, conversion: 0 })),
        by_category: {},
      },
      "/api/v1/jobs": { applications: [], count: 0 },
    });
    renderPage(<Jobs />);

    expect(await screen.findByText("Nothing applied to yet")).toBeInTheDocument();
    expect(await screen.findByText("No applications yet")).toBeInTheDocument();
  });
});
