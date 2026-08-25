import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import NewSession from "./new/page";
import Report from "./[id]/report/page";
import { renderPage, stubFetch } from "@/test/harness";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  usePathname: () => "/session/new",
  useParams: () => ({ id: "s1" }),
}));

afterEach(() => vi.unstubAllGlobals());

const PLAN = {
  strategy: "weakness-priority@1",
  adaptive: true,
  calibration: false,
  why: "Concepts ranked by weakness priority.",
  mode: "coding",
  budget_minutes: 45,
  band: [0.6, 0.75],
  focus_concepts: [],
  estimated_minutes: 30,
  items: [
    {
      item_id: "i.code.0004",
      title: "Longest certifiable stretch",
      primary_concept: "sliding-window",
      expected_minutes: 15,
      elo: 1360,
      reason: {
        targets: "sliding-window",
        priority: 0.213,
        terms: { weakness: 0.199, recent_errors: 0, overdue: 0, unlocks: 0.014, recent_exposure: -0 },
        expected_score: 0.749,
        in_band: true,
        calibrating: false,
        prerequisite_note: null,
      },
    },
  ],
  considered: [],
};

describe("/session/new", () => {
  it("shows the plan before you commit to it", async () => {
    // docs/API.md returns the plan up front deliberately: opaque adaptation is
    // untrustworthy adaptation.
    stubFetch({ "/api/v1/plan/next": PLAN });
    renderPage(<NewSession />);

    expect(await screen.findByText("Longest certifiable stretch")).toBeInTheDocument();
    expect(await screen.findByText(/targets/)).toBeInTheDocument();
    expect(await screen.findByText("in band")).toBeInTheDocument();
    expect(await screen.findByText(/Concepts ranked by weakness priority/)).toBeInTheDocument();
  });

  it("says when a plan adapted to nothing", async () => {
    // A calibration spread is not an adapted plan, and claiming otherwise would be the
    // engine overstating what it knows.
    stubFetch({ "/api/v1/plan/next": { ...PLAN, calibration: true } });
    renderPage(<NewSession />);

    expect(await screen.findByText("calibrating — no evidence yet")).toBeInTheDocument();
  });

  it("re-plans when the mode changes", async () => {
    const stub = stubFetch({ "/api/v1/plan/next": PLAN });
    renderPage(<NewSession />);
    await screen.findByText("Longest certifiable stretch");

    await userEvent.click(screen.getByRole("button", { name: "Quant" }));
    await waitFor(() => expect(stub.calls.some((u) => u.includes("mode=quant"))).toBe(true));
  });

  it("admits the preview does not include the difficulty bias", async () => {
    // GET /plan/next takes a mode and a budget only, so a biased preview would silently
    // disagree with what the button produces.
    stubFetch({ "/api/v1/plan/next": PLAN });
    renderPage(<NewSession />);
    await screen.findByText("Longest certifiable stretch");

    // A range input does not respond to typing; `fireEvent.change` is the supported way.
    fireEvent.change(screen.getByLabelText("Difficulty bias"), { target: { value: "1" } });

    expect(await screen.findByText(/does not include this/)).toBeInTheDocument();
  });

  it("refuses to start a session the planner could not fill", async () => {
    stubFetch({ "/api/v1/plan/next": { ...PLAN, items: [] } });
    renderPage(<NewSession />);

    expect(await screen.findByText(/The planner chose nothing/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start this session/ })).toBeDisabled();
  });
});

describe("/session/[id]/report", () => {
  const REPORT = {
    session_id: "s1",
    mode: "coding",
    state: "complete",
    started_at: "2026-08-22T14:05:08Z",
    ended_at: "2026-08-22T14:45:00Z",
    items: [
      { item_id: "i.code.0004", title: "Longest stretch", status: "graded", artifact_id: "a1", score: 0.75, detail: null },
      { item_id: "i.code.0007", title: "Parcel pairs", status: "failed", artifact_id: "a2", score: null, detail: null },
    ],
    mean_score: 0.75,
    graded: 1,
    failed: 1,
    not_attempted: 0,
    evidence: [
      { concept_id: "sliding-window", score: 0.75, confidence: 0.9, item_id: "i.code.0004", grader_version: "coding.tests@1" },
    ],
    notes: ["Some scores are a model's judgement against a rubric, not a test result."],
  };

  it("renders the server's own notes rather than restating them", async () => {
    // The notes are built from what actually happened in that session, so they are shown
    // verbatim — a hardcoded equivalent is what this project keeps finding to be stale.
    stubFetch({ "/api/v1/sessions/s1/report": REPORT });
    renderPage(<Report />);

    expect(await screen.findByText(/a model's judgement against a rubric/)).toBeInTheDocument();
  });

  it("separates a failed grading from a zero", async () => {
    // A failed grading writes no evidence. Showing it as 0% would be a fabricated score.
    stubFetch({ "/api/v1/sessions/s1/report": REPORT });
    renderPage(<Report />);

    expect(await screen.findByText("failed")).toBeInTheDocument();
    expect(await screen.findByText("no evidence written for these")).toBeInTheDocument();
  });

  it("shows the confidence behind each evidence row", async () => {
    // A hidden-test pass and a model's read of a rubric are not the same claim, and both
    // scale the rating move.
    stubFetch({ "/api/v1/sessions/s1/report": REPORT });
    renderPage(<Report />);

    expect(await screen.findByText("conf 0.90")).toBeInTheDocument();
    expect(await screen.findByText("coding.tests@1")).toBeInTheDocument();
  });

  it("explains a 409 instead of rendering an empty report", async () => {
    stubFetch({
      "/api/v1/sessions/s1/report": {
        __status: 409,
        type: "https://interview-helper.local/errors/wrong-state",
        title: "Wrong session state",
        detail: "Session is 'interviewing'; a report exists once it is complete.",
        status: 409,
      },
    });
    renderPage(<Report />);

    expect(await screen.findByText("wrong-state")).toBeInTheDocument();
    expect(await screen.findByText(/not in a state where this is possible yet/)).toBeInTheDocument();
    expect(await screen.findByText("Back to the session")).toBeInTheDocument();
  });
});
