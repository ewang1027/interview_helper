import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { BehavioralWorkspace } from "./behavioral";
import { DesignWorkspace } from "./design";
import { QuantWorkspace } from "./quant";
import type { Draft } from "./types";

/**
 * What each workspace hands to `POST /sessions/{id}/submissions`.
 *
 * The coding workspace is not here: it renders Monaco, which loads from a CDN
 * and does not run under jsdom. Its contract is the thinnest of the four
 * (`{kind: "code", language}` around editor text), and asserting against a stub
 * of the editor would test the stub.
 */
function lastDraft(onChange: ReturnType<typeof vi.fn>): Draft {
  return onChange.mock.calls.at(-1)![0] as Draft;
}

describe("quant workspace", () => {
  it("declares the answer on the final line", async () => {
    // The grader reads the answer from a declaration or, failing that, from the
    // last line carrying arithmetic. Appending "Answer: x" is what stops a
    // sanity bound inside the derivation being graded as the conclusion.
    const onChange = vi.fn();
    render(<QuantWorkspace onChange={onChange} />);

    await userEvent.type(screen.getByLabelText("Derivation"), "The naive answer is 27.");
    await userEvent.type(screen.getByLabelText("Final answer"), "39");

    const draft = lastDraft(onChange);
    expect(draft.kind).toBe("answer");
    expect(draft.content).toBe("The naive answer is 27.\n\nAnswer: 39");
    expect(draft.content.split("\n").at(-1)).toBe("Answer: 39");
  });

  it("sends no declaration when nothing was answered", async () => {
    // Stating nothing and being wrong score differently, so the client must not
    // manufacture a declaration out of an empty field.
    const onChange = vi.fn();
    render(<QuantWorkspace onChange={onChange} />);

    await userEvent.type(screen.getByLabelText("Derivation"), "I got as far as 2/3.");

    expect(lastDraft(onChange).content).toBe("I got as far as 2/3.");
    expect(lastDraft(onChange).content).not.toMatch(/Answer:/);
  });
});

describe("design workspace", () => {
  it("serialises components and connections, not a drawing", async () => {
    const onChange = vi.fn();
    render(<DesignWorkspace onChange={onChange} />);

    await userEvent.click(screen.getByRole("button", { name: "+ client" }));
    await userEvent.click(screen.getByRole("button", { name: "+ database" }));
    await userEvent.click(screen.getByRole("button", { name: /\+ connection/i }));

    const draft = lastDraft(onChange);
    expect(draft.kind).toBe("design");
    expect(draft.content).toContain("# Components");
    expect(draft.content).toContain("- client [client]");
    expect(draft.content).toContain("- database [database]");
    expect(draft.content).toContain("client [client] -> database [database]");
  });

  it("drops connections to a component that was removed", async () => {
    // An edge to a deleted node would serialise as "?", which is a grader
    // reading a citation to something that is not there.
    const onChange = vi.fn();
    render(<DesignWorkspace onChange={onChange} />);

    await userEvent.click(screen.getByRole("button", { name: "+ client" }));
    await userEvent.click(screen.getByRole("button", { name: "+ database" }));
    await userEvent.click(screen.getByRole("button", { name: /\+ connection/i }));
    await userEvent.click(screen.getByRole("button", { name: "Remove database" }));

    const draft = lastDraft(onChange);
    expect(draft.content).not.toContain("?");
    expect(draft.content).toContain("- (none)");
  });

  it("cannot add a connection before there are two components", async () => {
    const onChange = vi.fn();
    render(<DesignWorkspace onChange={onChange} />);

    expect(screen.getByRole("button", { name: /\+ connection/i })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "+ client" }));
    expect(screen.getByRole("button", { name: /\+ connection/i })).toBeDisabled();
  });
});

describe("behavioral workspace", () => {
  it("omits sections that were left empty", async () => {
    // A heading with nothing under it reads to a rubric grader as an attempt at
    // that section, which is worse than its absence.
    const onChange = vi.fn();
    render(<BehavioralWorkspace onChange={onChange} />);

    await userEvent.type(screen.getByLabelText(/Situation/), "Prod was down.");
    await userEvent.type(screen.getByLabelText(/Result/), "Recovered in nine minutes.");

    const draft = lastDraft(onChange);
    expect(draft.kind).toBe("narrative");
    expect(draft.content).toBe("## Situation\nProd was down.\n\n## Result\nRecovered in nine minutes.");
    expect(draft.content).not.toContain("## Task");
    expect(draft.content).not.toContain("## Action");
  });
});
