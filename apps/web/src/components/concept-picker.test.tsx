import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ConceptPicker } from "./concept-picker";
import { fixtures, renderPage, stubFetch } from "@/test/harness";

/**
 * The concept picker is the correction path for everything the classifier could not
 * name, and the thing a person types into it is the problem they just solved. These pin
 * that an alias reaches the concept, and that the alias is shown as the reason it did.
 */

const taxonomy = {
  ...fixtures.concepts,
  concepts: [
    ...fixtures.concepts.concepts,
    {
      id: "interval-overlap-count",
      name: "Sweep line and overlap counting",
      domain: "coding",
      description: "Count how many intervals are live at once…",
      band: "core",
      tags: ["meeting rooms ii", "sweep line", "car pooling"],
      topic: "Intervals",
      prereqs: [],
      unlocks: [],
      servable: false,
      measured_by_some_item: false,
    },
  ],
  total: 3,
};

afterEach(() => vi.unstubAllGlobals());

describe("concept picker", () => {
  it("finds a concept by the name of a problem that exercises it", async () => {
    stubFetch({ "/api/v1/concepts": taxonomy });
    const onChange = vi.fn();
    renderPage(<ConceptPicker value={null} onChange={onChange} />);

    const input = await screen.findByPlaceholderText("Search concepts…");
    await userEvent.type(input, "meeting rooms");

    // The alias is shown beside the name, so it is clear why this concept came up.
    expect(await screen.findByText("· meeting rooms ii")).toBeInTheDocument();
    await userEvent.click(screen.getByText("Sweep line and overlap counting"));
    expect(onChange).toHaveBeenCalledWith("interval-overlap-count");
  });

  it("ranks a match on the concept's own name above a match on an alias", async () => {
    stubFetch({
      "/api/v1/concepts": {
        ...taxonomy,
        concepts: [
          ...taxonomy.concepts,
          {
            id: "sliding-window-alias-only",
            name: "Something else entirely",
            domain: "coding",
            description: "Not a window at all…",
            band: "core",
            tags: ["sliding window trick"],
            topic: "Sliding Window",
            prereqs: [],
            unlocks: [],
            servable: false,
            measured_by_some_item: false,
          },
        ],
      },
    });
    renderPage(<ConceptPicker value={null} onChange={vi.fn()} />);

    const input = await screen.findByPlaceholderText("Search concepts…");
    await userEvent.type(input, "sliding window");

    const options = await screen.findAllByRole("button");
    expect(options[0]).toHaveTextContent("Sliding window");
    expect(options[1]).toHaveTextContent("Something else entirely");
  });
});
