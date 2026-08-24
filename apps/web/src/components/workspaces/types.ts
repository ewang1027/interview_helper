import type { Language, SubmissionKind } from "@/lib/types";

/** What a workspace hands back when the candidate submits. */
export interface Draft {
  kind: SubmissionKind;
  content: string;
  language?: Language;
}

export interface WorkspaceProps {
  /** Called on every edit, so the session shell can enable or disable submit. */
  onChange: (draft: Draft) => void;
  disabled?: boolean;
}
