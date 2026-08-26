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

  it("marks a row whose tag was proposed rather than confirmed", async () => {
    stubFetch({
      ...BASE,
      "/api/v1/jobs": {
        applications: [
          application({ status: "pending_classification", classification_confidence: 0.3 }),
        ],
        count: 1,
      },
    });
    renderPage(<Jobs />);

    expect(await screen.findByText("needs a tag")).toBeInTheDocument();
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
