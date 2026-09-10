"use client";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";
import { ApiErrorNotice } from "@/components/api-error";
import { Badge, Button, Card, CardBody, CardHeader, Empty, Skeleton } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { relativeDue, when } from "@/lib/format";
import type { PracticeProblem, ProblemStatus } from "@/lib/types";

/**
 * Everything logged — searchable, filterable, sortable, and groupable.
 *
 * The whole log is in the browser before anything is typed (`api.allProblems`
 * follows the cursor to the end), so every control here is instant and none of
 * them can go stale against the list it narrows. That is the applications
 * board's scale decision applied again: a personal practice log is a few
 * hundred rows, and the day it is not, these filters belong in SQL and this
 * component keeps its shape.
 *
 * Two axes of category, kept apart on purpose. **Topic** is derived — the
 * family the primary concept is filed under (docs/CONCEPTS.md), so it exists
 * the moment a problem is tagged and cannot disagree with the tag. **Labels**
 * are yours: free text, edited on the row, never read by anything that writes
 * evidence. "Blind 75", "redo", a company — none of those is a concept, and
 * none of them belongs in the taxonomy.
 *
 * Paging is the board's: twenty rows, then ten per click, and the count prints
 * both numbers so a list that stops at twenty never reads as a list of twenty.
 * A grouped view shows every match, because a section cut off mid-way would
 * misreport the size of every group after it.
 */

type Difficulty = "Easy" | "Medium" | "Hard" | "Other";
type Due = "any" | "now" | "scheduled" | "unscheduled";
type Sort = "newest" | "oldest" | "due" | "title" | "difficulty" | "solves";
type GroupBy = "none" | "topic" | "difficulty" | "label" | "status";

const FIRST_PAGE = 20;
const PAGE = 10;

const STATUSES: { label: string; value: ProblemStatus | undefined }[] = [
  { label: "All", value: undefined },
  { label: "Needs a tag", value: "pending_classification" },
  { label: "Active", value: "active" },
  { label: "Retired", value: "retired" },
];

const DIFFICULTY_ORDER: Record<Difficulty, number> = { Easy: 0, Medium: 1, Hard: 2, Other: 3 };
const DIFFICULTY_TONE = { Easy: "good", Medium: "warning", Hard: "critical", Other: "neutral" } as const;

const LIST_LABEL: Record<string, string> = {
  neetcode150: "NeetCode 150",
  blind75: "Blind 75",
  neetcode250: "NeetCode 250",
};

/** LeetCode says Easy/Medium/Hard; Codeforces says 1700; a person says anything. */
export function difficultyOf(label: string | null): Difficulty {
  const text = (label ?? "").toLowerCase();
  if (text.includes("easy")) return "Easy";
  if (text.includes("medium") || text.includes("med")) return "Medium";
  if (text.includes("hard")) return "Hard";
  return "Other";
}

function statusLabel(status: ProblemStatus): string {
  return STATUSES.find((entry) => entry.value === status)?.label ?? status;
}

interface Filters {
  status: ProblemStatus | undefined;
  topic: string;
  difficulty: Difficulty | "";
  source: string;
  list: string;
  label: string;
  due: Due;
}

const NO_FILTERS: Filters = {
  status: undefined,
  topic: "",
  difficulty: "",
  source: "",
  list: "",
  label: "",
  due: "any",
};

function matches(row: PracticeProblem, filters: Filters, needle: string, now: number): boolean {
  if (filters.status && row.status !== filters.status) return false;
  if (filters.topic && (row.topic ?? "Untagged") !== filters.topic) return false;
  if (filters.difficulty && difficultyOf(row.difficulty_label) !== filters.difficulty) return false;
  if (filters.source && row.source_site !== filters.source) return false;
  if (filters.list && !row.lists.includes(filters.list)) return false;
  if (filters.label && !row.labels.some((label) => label.toLowerCase() === filters.label.toLowerCase()))
    return false;
  if (filters.due === "now" && !(row.due_at && new Date(row.due_at).getTime() <= now)) return false;
  if (filters.due === "scheduled" && !row.due_at) return false;
  if (filters.due === "unscheduled" && row.due_at) return false;
  if (needle) {
    const haystack = [
      row.title,
      row.primary_concept_id,
      row.primary_concept_name,
      row.topic,
      ...row.labels,
      row.notes,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    if (!needle.split(/\s+/).every((term) => haystack.includes(term))) return false;
  }
  return true;
}

function compare(sort: Sort): (a: PracticeProblem, b: PracticeProblem) => number {
  const far = Number.POSITIVE_INFINITY;
  switch (sort) {
    case "oldest":
      return (a, b) => a.created_at.localeCompare(b.created_at);
    case "due":
      // Unscheduled last: a problem with no date is not "due soonest", it is not due.
      return (a, b) =>
        (a.due_at ? new Date(a.due_at).getTime() : far) - (b.due_at ? new Date(b.due_at).getTime() : far);
    case "title":
      return (a, b) => a.title.localeCompare(b.title);
    case "difficulty":
      return (a, b) =>
        DIFFICULTY_ORDER[difficultyOf(a.difficulty_label)] - DIFFICULTY_ORDER[difficultyOf(b.difficulty_label)] ||
        a.title.localeCompare(b.title);
    case "solves":
      return (a, b) => b.solve_count - a.solve_count || a.title.localeCompare(b.title);
    case "newest":
    default:
      return (a, b) => b.created_at.localeCompare(a.created_at);
  }
}

function groupKeys(row: PracticeProblem, by: GroupBy): string[] {
  switch (by) {
    case "topic":
      return [row.topic ?? "Untagged"];
    case "difficulty":
      return [difficultyOf(row.difficulty_label)];
    case "label":
      // A problem with two labels sits in both sections; one with none has its own.
      return row.labels.length ? row.labels : ["No label"];
    case "status":
      return [statusLabel(row.status)];
    default:
      return [""];
  }
}

function countBy<T>(items: T[], key: (item: T) => string | null | undefined): [string, number][] {
  const counts = new Map<string, number>();
  for (const item of items) {
    const value = key(item);
    if (value) counts.set(value, (counts.get(value) ?? 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

export function PracticeLog({
  rows,
  isLoading,
  error,
  onChanged,
}: {
  rows: PracticeProblem[];
  isLoading: boolean;
  error: unknown;
  onChanged: () => void;
}) {
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [sort, setSort] = useState<Sort>("newest");
  const [groupBy, setGroupBy] = useState<GroupBy>("none");
  const [shown, setShown] = useState(FIRST_PAGE);

  // The options each control offers come from the log itself, so a filter never names a
  // topic or a label that nothing carries.
  const topics = useMemo(() => countBy(rows, (row) => row.topic ?? "Untagged"), [rows]);
  const labels = useMemo(() => countBy(rows.flatMap((row) => row.labels), (label) => label), [rows]);
  const sources = useMemo(() => countBy(rows, (row) => row.source_site), [rows]);
  const lists = useMemo(() => countBy(rows.flatMap((row) => row.lists), (list) => list), [rows]);

  const needle = query.trim().toLowerCase();
  const filtered = useMemo(() => {
    const now = Date.now();
    return rows.filter((row) => matches(row, filters, needle, now)).sort(compare(sort));
  }, [rows, filters, needle, sort]);

  const active = Object.entries(filters).filter(
    ([key, value]) => value !== NO_FILTERS[key as keyof Filters],
  ).length;
  const narrowed = active > 0 || needle.length > 0;

  const set = <K extends keyof Filters>(key: K, value: Filters[K]) => {
    setFilters((current) => ({ ...current, [key]: value }));
    setShown(FIRST_PAGE);
  };

  const groups = useMemo(() => {
    if (groupBy === "none") return null;
    const sections = new Map<string, PracticeProblem[]>();
    for (const row of filtered) {
      for (const key of groupKeys(row, groupBy)) {
        sections.set(key, [...(sections.get(key) ?? []), row]);
      }
    }
    return [...sections.entries()].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));
  }, [filtered, groupBy]);

  const visible = filtered.slice(0, shown);
  const moreStep = Math.min(PAGE, filtered.length - visible.length);
  const lessStep = Math.min(PAGE, visible.length - FIRST_PAGE);

  return (
    <Card>
      <CardHeader
        title="Everything logged"
        hint={
          isLoading
            ? "Loading the whole log…"
            : narrowed
              ? `${filtered.length} of ${rows.length} match`
              : `${rows.length} problem${rows.length === 1 ? "" : "s"}`
        }
        action={
          <div className="flex gap-1">
            {STATUSES.map((entry) => (
              <button
                key={entry.label}
                type="button"
                onClick={() => set("status", entry.value)}
                aria-pressed={filters.status === entry.value}
                className={cn(
                  "rounded px-2 py-1 text-xs transition-colors",
                  filters.status === entry.value
                    ? "bg-accent text-accent-ink"
                    : "text-ink-secondary hover:bg-sunken",
                )}
              >
                {entry.label}
              </button>
            ))}
          </div>
        }
      />
      <CardBody className="space-y-3">
        <div className="flex flex-wrap items-end gap-2">
          <label className="min-w-0 flex-1 basis-48">
            <span className="sr-only">Search problems</span>
            <input
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setShown(FIRST_PAGE);
              }}
              placeholder="Search title, concept, topic, label…"
              aria-label="Search problems"
              className="border-hairline bg-surface text-ink w-full rounded-md border px-2 py-1.5 text-sm"
            />
          </label>
          <Select label="Topic" value={filters.topic} onChange={(value) => set("topic", value)}>
            <option value="">Any topic</option>
            {topics.map(([topic, count]) => (
              <option key={topic} value={topic}>
                {topic} ({count})
              </option>
            ))}
          </Select>
          <Select
            label="Difficulty"
            value={filters.difficulty}
            onChange={(value) => set("difficulty", value as Difficulty | "")}
          >
            <option value="">Any difficulty</option>
            {(["Easy", "Medium", "Hard", "Other"] as const).map((level) => (
              <option key={level} value={level}>
                {level}
              </option>
            ))}
          </Select>
          <Select label="Source" value={filters.source} onChange={(value) => set("source", value)}>
            <option value="">Any source</option>
            {sources.map(([site, count]) => (
              <option key={site} value={site}>
                {site} ({count})
              </option>
            ))}
          </Select>
          {lists.length ? (
            <Select label="List" value={filters.list} onChange={(value) => set("list", value)}>
              <option value="">Any list</option>
              {lists.map(([list, count]) => (
                <option key={list} value={list}>
                  {LIST_LABEL[list] ?? list} ({count})
                </option>
              ))}
            </Select>
          ) : null}
          {labels.length ? (
            <Select label="Label" value={filters.label} onChange={(value) => set("label", value)}>
              <option value="">Any label</option>
              {labels.map(([label, count]) => (
                <option key={label} value={label}>
                  {label} ({count})
                </option>
              ))}
            </Select>
          ) : null}
          <Select label="Due" value={filters.due} onChange={(value) => set("due", value as Due)}>
            <option value="any">Any time</option>
            <option value="now">Due for a re-solve</option>
            <option value="scheduled">Scheduled</option>
            <option value="unscheduled">Unscheduled</option>
          </Select>
          <Select label="Sort" value={sort} onChange={(value) => setSort(value as Sort)}>
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
            <option value="due">Due soonest</option>
            <option value="title">Title A–Z</option>
            <option value="difficulty">Easiest first</option>
            <option value="solves">Most solved</option>
          </Select>
          <Select label="Group by" value={groupBy} onChange={(value) => setGroupBy(value as GroupBy)}>
            <option value="none">No grouping</option>
            <option value="topic">Topic</option>
            <option value="difficulty">Difficulty</option>
            <option value="label">Label</option>
            <option value="status">Status</option>
          </Select>
          {narrowed ? (
            <button
              type="button"
              onClick={() => {
                setFilters(NO_FILTERS);
                setQuery("");
                setShown(FIRST_PAGE);
              }}
              className="text-ink-secondary hover:text-ink px-1 py-1.5 text-xs underline underline-offset-2"
            >
              Clear
            </button>
          ) : null}
        </div>

        {error ? <ApiErrorNotice error={error} /> : null}
        {isLoading ? (
          <Skeleton className="h-32" />
        ) : rows.length === 0 ? (
          <Empty title="Nothing logged yet" detail="Add the first one on the left." />
        ) : filtered.length === 0 ? (
          <Empty
            title="Nothing matches"
            detail="Clear a filter or the search — the log is not empty, this view of it is."
          />
        ) : groups ? (
          <div className="space-y-5">
            {groups.map(([section, members]) => (
              <section key={section} aria-label={section}>
                <h3 className="text-ink-secondary flex items-baseline gap-2 text-xs font-medium tracking-wide uppercase">
                  {section}
                  <span className="text-ink-muted font-normal normal-case tabular-nums">
                    {members.length}
                  </span>
                </h3>
                <ul className="divide-hairline mt-1 divide-y">
                  {members.map((problem) => (
                    <ProblemRow key={problem.id} problem={problem} onChanged={onChanged} />
                  ))}
                </ul>
              </section>
            ))}
          </div>
        ) : (
          <>
            <ul className="divide-hairline divide-y">
              {visible.map((problem) => (
                <ProblemRow key={problem.id} problem={problem} onChanged={onChanged} />
              ))}
            </ul>
            {filtered.length > FIRST_PAGE ? (
              <div className="flex flex-wrap items-center gap-3 pt-2">
                <span className="text-ink-muted text-xs tabular-nums">
                  Showing {visible.length} of {filtered.length}
                </span>
                {moreStep > 0 ? (
                  <Button variant="secondary" size="sm" onClick={() => setShown(shown + moreStep)}>
                    Load {moreStep} more
                  </Button>
                ) : null}
                {lessStep > 0 ? (
                  <Button variant="secondary" size="sm" onClick={() => setShown(shown - lessStep)}>
                    Load {lessStep} less
                  </Button>
                ) : null}
              </div>
            ) : null}
          </>
        )}
      </CardBody>
    </Card>
  );
}

function Select({
  label,
  value,
  onChange,
  children,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: React.ReactNode;
}) {
  return (
    <label className="min-w-0">
      <span className="sr-only">{label}</span>
      <select
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="border-hairline bg-surface text-ink rounded-md border px-2 py-1.5 text-xs"
      >
        {children}
      </select>
    </label>
  );
}

function ProblemRow({ problem, onChanged }: { problem: PracticeProblem; onChanged: () => void }) {
  const needsTag = problem.status === "pending_classification";
  const difficulty = difficultyOf(problem.difficulty_label);
  const list = problem.lists.includes("neetcode150")
    ? "NeetCode 150"
    : problem.lists.includes("blind75")
      ? "Blind 75"
      : null;

  return (
    <li className="py-2">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <Link
          href={`/practice/${problem.id}`}
          className="text-ink min-w-0 flex-1 truncate text-sm hover:underline"
        >
          {problem.title}
        </Link>
        {problem.difficulty_label ? (
          <Badge tone={DIFFICULTY_TONE[difficulty]}>
            {difficulty === "Other" ? problem.difficulty_label : difficulty}
          </Badge>
        ) : null}
        {problem.topic ? <span className="text-ink-secondary text-xs">{problem.topic}</span> : null}
        {problem.primary_concept_id ? (
          <span
            className="text-ink-secondary text-xs"
            title={problem.primary_concept_id}
          >
            · {problem.primary_concept_name ?? problem.primary_concept_id}
          </span>
        ) : null}
        {list ? <Badge>{list}</Badge> : null}
        {needsTag ? (
          <Badge tone={problem.primary_concept_id ? "serious" : "warning"}>
            {problem.primary_concept_id ? "suggested — confirm it" : "needs a tag"}
          </Badge>
        ) : problem.status === "retired" ? (
          <Badge tone="good">retired</Badge>
        ) : (
          <Badge>{relativeDue(problem.due_at)}</Badge>
        )}
        <span className="text-ink-muted text-xs">{problem.source_site}</span>
        <span className="text-ink-muted text-xs">{when(problem.created_at)}</span>
        <a
          href={problem.url}
          target="_blank"
          rel="noreferrer"
          aria-label={`Open ${problem.title} on ${problem.source_site}`}
          className="text-ink-muted hover:text-ink text-xs"
        >
          ↗
        </a>
      </div>
      <Labels problem={problem} onChanged={onChanged} />
    </li>
  );
}

/**
 * The row's labels, editable in place. Removing one is a click; adding one is typing and
 * Enter. Each edit sends the full list, which is what `PATCH` takes — and the server
 * deduplicates without regard to case, so the list that comes back is the truth.
 */
function Labels({ problem, onChanged }: { problem: PracticeProblem; onChanged: () => void }) {
  const [draft, setDraft] = useState("");
  const [adding, setAdding] = useState(false);

  const save = useMutation({
    mutationFn: (labels: string[]) => api.updateProblem(problem.id, { labels }),
    onSuccess: () => {
      setDraft("");
      setAdding(false);
      onChanged();
    },
  });

  const add = () => {
    const value = draft.trim();
    if (!value) {
      setAdding(false);
      return;
    }
    save.mutate([...problem.labels, value]);
  };

  return (
    <div className="mt-1 flex flex-wrap items-center gap-1">
      {problem.labels.map((label) => (
        <span
          key={label}
          className="border-hairline bg-sunken text-ink-secondary inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs"
        >
          {label}
          <button
            type="button"
            onClick={() => save.mutate(problem.labels.filter((other) => other !== label))}
            aria-label={`Remove label ${label} from ${problem.title}`}
            disabled={save.isPending}
            className="text-ink-muted hover:text-ink"
          >
            ×
          </button>
        </span>
      ))}
      {adding ? (
        <input
          autoFocus
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") add();
            if (event.key === "Escape") {
              setDraft("");
              setAdding(false);
            }
          }}
          onBlur={add}
          placeholder="label"
          aria-label={`New label for ${problem.title}`}
          className="border-hairline bg-surface text-ink w-28 rounded-full border px-2 py-0.5 text-xs"
        />
      ) : (
        <button
          type="button"
          onClick={() => setAdding(true)}
          aria-label={`Add a label to ${problem.title}`}
          className="text-ink-muted hover:text-ink rounded-full px-1.5 py-0.5 text-xs"
        >
          + label
        </button>
      )}
      {save.error ? <ApiErrorNotice error={save.error} /> : null}
    </div>
  );
}
