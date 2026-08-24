"use client";

import type { Mode } from "@/lib/types";
import { BehavioralWorkspace } from "./behavioral";
import { CodingWorkspace } from "./coding";
import { DesignWorkspace } from "./design";
import { QuantWorkspace } from "./quant";
import type { WorkspaceProps } from "./types";

export type { Draft, WorkspaceProps } from "./types";

/** One shell, four workspaces (docs/WEB.md). */
export function Workspace({ mode, ...props }: WorkspaceProps & { mode: Mode }) {
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
}
