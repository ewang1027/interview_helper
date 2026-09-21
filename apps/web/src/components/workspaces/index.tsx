"use client";

import { memo } from "react";
import type { Mode } from "@/lib/types";
import { BehavioralWorkspace } from "./behavioral";
import { CodingWorkspace } from "./coding";
import { DesignWorkspace } from "./design";
import { QuantWorkspace } from "./quant";
import type { WorkspaceProps } from "./types";

export type { Draft, WorkspaceProps } from "./types";

/**
 * One shell, four workspaces (docs/WEB.md).
 *
 * **`memo`'d deliberately.** Its parent is the live session page, which
 * re-renders once per streamed token — tens of times a second while the
 * interviewer is talking. Every one of those used to reach the workspace and,
 * in coding mode, the Monaco editor inside it. All three props are stable
 * across a stream (`mode` is a string, `disabled` a boolean, and `onChange` is
 * `useCallback`'d at the call site), so this cuts the cascade at the one place
 * the token has no business crossing. If `onChange` ever stops being stable,
 * this memo silently stops working — which is why the call site says so too.
 */
export const Workspace = memo(function Workspace({
  mode,
  ...props
}: WorkspaceProps & { mode: Mode }) {
  switch (mode) {
    case "coding":
      return <CodingWorkspace {...props} />;
    case "quant":
      return <QuantWorkspace {...props} />;
    case "design":
      return <DesignWorkspace {...props} />;
    case "behavioral":
      return <BehavioralWorkspace {...props} />;
    default:
      mode satisfies never;
      return null;
  }
});
