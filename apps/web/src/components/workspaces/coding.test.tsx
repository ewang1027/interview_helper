import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useCallback, useEffect, useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Workspace } from "./index";

/**
 * What a streamed token is allowed to cost the coding workspace.
 *
 * The live session page re-renders once per `agent.message.delta` — tens of
 * times a second while the interviewer is talking. This pins the two things
 * that used to make each one expensive:
 *
 * - `Workspace` is `memo`'d, so a parent re-render with unchanged props does
 *   not reach the editor at all.
 * - `options` and `onChange` are stable identities, so even when the workspace
 *   *does* re-render — on every character the candidate types — Monaco is not
 *   handed new ones. `@monaco-editor/react` keys `editor.updateOptions()` on
 *   the first and a `dispose()`/re-subscribe of the content listener on the
 *   second, so a fresh object per render meant both fired per render.
 *
 * Monaco itself is stubbed. That is the one thing worth being suspicious of
 * here, and the reason this asserts on *prop identity* rather than on anything
 * the real editor does: the claim is about what this component hands over, not
 * about how Monaco reacts, and a stub can only honestly answer the first.
 */
const seen: { options: unknown; onChange: unknown; value: string }[] = [];

vi.mock("@monaco-editor/react", () => ({
  __esModule: true,
  default: (props: {
    options: unknown;
    onChange: (value: string | undefined) => void;
    value: string;
  }) => {
    seen.push({ options: props.options, onChange: props.onChange, value: props.value });
    return (
      <textarea
        aria-label="Source"
        value={props.value}
        onChange={(event) => props.onChange(event.target.value)}
      />
    );
  },
  loader: { config: vi.fn() },
}));

beforeEach(() => {
  seen.length = 0;
});

/** Stands in for the session page: re-renders `ticks` times, props unchanged. */
function StreamingParent({ ticks }: { ticks: number }) {
  const [n, setN] = useState(0);
  // Stable, exactly as src/app/session/[id]/page.tsx makes it.
  const onChange = useCallback(() => {}, []);

  useEffect(() => {
    if (n < ticks) setN((current) => current + 1);
  }, [n, ticks]);

  return (
    <>
      <span data-testid="tick">{n}</span>
      <Workspace mode="coding" onChange={onChange} disabled={false} />
    </>
  );
}

describe("coding workspace under a token stream", () => {
  it("does not re-render when the page around it does", async () => {
    render(<StreamingParent ticks={50} />);

    // The parent has rendered 51 times; the editor was rendered once.
    expect(await screen.findByText("50")).toBeInTheDocument();
    expect(seen.length).toBe(1);
  });

  it("hands Monaco the same options and onChange on every render", async () => {
    render(<StreamingParent ticks={0} />);

    await userEvent.type(screen.getByLabelText("Source"), "xyz");

    // One render per character, so the stability claim has something to bite on.
    expect(seen.length).toBeGreaterThan(3);
    expect(new Set(seen.map((render) => render.options)).size).toBe(1);
    expect(new Set(seen.map((render) => render.onChange)).size).toBe(1);
    expect(seen.at(-1)!.value).toContain("xyz");
  });

  it("still rebuilds options when the one thing they depend on changes", async () => {
    const onChange = () => {};
    const { rerender } = render(
      <Workspace mode="coding" onChange={onChange} disabled={false} />,
    );
    const before = seen.at(-1)!.options;

    rerender(<Workspace mode="coding" onChange={onChange} disabled={true} />);

    expect(seen.at(-1)!.options).not.toBe(before);
    expect(seen.at(-1)!.options).toMatchObject({ readOnly: true });
  });
});
