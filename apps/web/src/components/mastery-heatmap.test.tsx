import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { MasteryHeatmap, toHeatmapConcepts, type HeatmapConcept } from "./mastery-heatmap";
import type { MasteryRow, RankedConcept } from "@/lib/types";

const YESTERDAY = new Date(Date.now() - 86_400_000).toISOString();
const NEXT_WEEK = new Date(Date.now() + 7 * 86_400_000).toISOString();

function concept(over: Partial<HeatmapConcept> = {}): HeatmapConcept {
  return {
    concept_id: "sliding-window",
    name: "Sliding window",
    domain: "coding",
    observations: 5,
    normalized: 0.41,
    ability: 1501,
    due_at: NEXT_WEEK,
    calibrating: false,
    ...over,
  };
}

describe("mastery heatmap", () => {
  it("shows the denominator behind every cell", () => {
    // docs/WEB.md: an ability from two attempts is a different situation from
    // the same ability from thirty, and a heatmap hiding that misleads.
    render(<MasteryHeatmap concepts={[concept({ observations: 30 })]} />);
    expect(screen.getByText("30")).toBeInTheDocument();
  });

  it("says how much of the taxonomy has been measured", () => {
    render(
      <MasteryHeatmap
        concepts={[
          concept(),
          concept({ concept_id: "two-pointer", name: "Two pointer", normalized: null }),
        ]}
      />,
    );
    expect(screen.getByText(/1 of 2 concepts measured/)).toBeInTheDocument();
  });

  it("marks an overdue concept with a shape, not only a colour", () => {
    // The rule from docs/WEB.md: overdue and weak are different states and must
    // be separable without relying on hue.
    const { container } = render(
      <MasteryHeatmap concepts={[concept({ due_at: YESTERDAY })]} />,
    );
    const cell = container.querySelector('a[href="/concepts/sliding-window"]')!;

    expect(cell.className).toContain("ring-[var(--status-critical)]");
    // The wedge is a separate element, so the state survives greyscale.
    expect(cell.querySelector("span[aria-hidden]")).toBeTruthy();
  });

  it("draws a never-measured concept outside the ability ramp", () => {
    // Absence is not a low score.
    const { container } = render(
      <MasteryHeatmap concepts={[concept({ normalized: null, ability: 1550 })]} />,
    );
    const cell = container.querySelector('a[href="/concepts/sliding-window"]')!;

    expect(cell.className).toContain("bg-ability-none");
    expect(cell.className).not.toContain("bg-ability-3");
  });

  it("separates abilities that normalize to nearly the same number", () => {
    // 1501 and 1660 normalise to 0.410 and 0.482 on the server's 600-2800
    // scale. Banded on that they are one shade; banded on Elo they are two.
    const { container } = render(
      <MasteryHeatmap
        concepts={[
          concept({ concept_id: "a", ability: 1501, normalized: 0.41 }),
          concept({ concept_id: "b", ability: 1660, normalized: 0.482 }),
        ]}
      />,
    );

    const weak = container.querySelector('a[href="/concepts/a"]')!;
    const strong = container.querySelector('a[href="/concepts/b"]')!;
    expect(weak.className).toContain("bg-ability-3");
    expect(strong.className).toContain("bg-ability-4");
  });

  it("offers a table view of the same data", async () => {
    render(<MasteryHeatmap concepts={[concept({ name: "Sliding window" })]} />);

    await userEvent.click(screen.getByRole("button", { name: /show as table/i }));

    const table = screen.getByRole("table");
    expect(within(table).getByText("Sliding window")).toBeInTheDocument();
    expect(within(table).getByText("1501")).toBeInTheDocument();
  });

  it("groups by domain and counts each group", () => {
    render(
      <MasteryHeatmap
        concepts={[
          concept({ concept_id: "a", domain: "coding" }),
          concept({ concept_id: "b", domain: "quant", normalized: null }),
        ]}
      />,
    );

    expect(screen.getByText(/Coding/)).toBeInTheDocument();
    expect(screen.getByText(/Quant/)).toBeInTheDocument();
  });
});

describe("toHeatmapConcepts", () => {
  const ranked: RankedConcept = {
    concept_id: "sliding-window",
    name: "Sliding window",
    domain: "coding",
    priority: 0.2,
    ability: 1550,
    observations: 0,
    calibrating: true,
    unseen: true,
    terms: { weakness: 0, recent_errors: 0, overdue: 0, unlocks: 0, recent_exposure: 0 },
  };

  it("keeps a concept with no mastery row unmeasured", () => {
    const [merged] = toHeatmapConcepts([ranked], []);
    expect(merged.normalized).toBeNull();
    expect(merged.name).toBe("Sliding window");
  });

  it("prefers the mastery row's numbers over the ranking's", () => {
    const row: MasteryRow = {
      concept_id: "sliding-window",
      ability: 1501.14,
      normalized_ability: 0.4096,
      observations: 5,
      calibrating: false,
      stability_days: 0.02,
      due_at: YESTERDAY,
      last_seen: YESTERDAY,
    };

    const [merged] = toHeatmapConcepts([ranked], [row]);
    expect(merged.ability).toBeCloseTo(1501.14);
    expect(merged.observations).toBe(5);
    expect(merged.due_at).toBe(YESTERDAY);
    // The name still comes from the ranking — the mastery row has none.
    expect(merged.name).toBe("Sliding window");
  });
});
