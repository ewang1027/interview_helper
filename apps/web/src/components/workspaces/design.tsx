"use client";

import { useEffect, useState } from "react";
import { Badge, Button } from "@/components/ui/primitives";
import type { WorkspaceProps } from "./types";

/**
 * A structured component editor, not a freehand canvas.
 *
 * docs/WEB.md is explicit about why: "A freehand diagram is far harder to grade
 * reliably, and a grader that cannot read the artifact produces vibes. A
 * constrained palette makes the artifact machine-readable." The rubric grader
 * has to cite criteria against the artifact, so the artifact has to be readable.
 *
 * What is built is the structured half — a fixed node palette, typed edges, and
 * notes — serialised to a deterministic text form the rubric grader can read.
 * The *visual* canvas (dragging nodes around) is not here, and deliberately not
 * faked: the grading value is entirely in the structure, and a layout carries
 * none of it.
 */

const NODE_TYPES = [
  "client",
  "load balancer",
  "service",
  "cache",
  "database",
  "queue",
  "object store",
  "cdn",
  "worker",
  "external api",
] as const;

type NodeType = (typeof NODE_TYPES)[number];

interface Node {
  id: number;
  type: NodeType;
  label: string;
}

interface Edge {
  id: number;
  from: number;
  to: number;
  label: string;
}

function serialise(nodes: Node[], edges: Edge[], notes: string): string {
  const name = (id: number) => {
    const node = nodes.find((n) => n.id === id);
    return node ? `${node.label || node.type} [${node.type}]` : "?";
  };

  const lines: string[] = ["# Components"];
  for (const node of nodes) lines.push(`- ${node.label || node.type} [${node.type}]`);
  lines.push("", "# Connections");
  if (edges.length === 0) lines.push("- (none)");
  for (const edge of edges) {
    lines.push(`- ${name(edge.from)} -> ${name(edge.to)}${edge.label ? `: ${edge.label}` : ""}`);
  }
  if (notes.trim()) lines.push("", "# Notes", notes.trim());
  return lines.join("\n");
}

export function DesignWorkspace({ onChange, disabled }: WorkspaceProps) {
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [notes, setNotes] = useState("");
  const [nextId, setNextId] = useState(1);

  useEffect(() => {
    onChange({ kind: "design", content: serialise(nodes, edges, notes) });
  }, [nodes, edges, notes, onChange]);

  const addNode = (type: NodeType) => {
    setNodes((current) => [...current, { id: nextId, type, label: "" }]);
    setNextId((id) => id + 1);
  };

  const addEdge = () => {
    if (nodes.length < 2) return;
    setEdges((current) => [
      ...current,
      { id: nextId, from: nodes[0]!.id, to: nodes[1]!.id, label: "" },
    ]);
    setNextId((id) => id + 1);
  };

  const removeNode = (id: number) => {
    setNodes((current) => current.filter((node) => node.id !== id));
    // An edge to a component that no longer exists would serialise as "?".
    setEdges((current) => current.filter((edge) => edge.from !== id && edge.to !== id));
  };

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <div className="border-hairline border-b p-3">
        <div className="text-ink-muted mb-1.5 text-xs font-medium tracking-wide uppercase">
          Palette
        </div>
        <div className="flex flex-wrap gap-1.5">
          {NODE_TYPES.map((type) => (
            <button
              key={type}
              type="button"
              disabled={disabled}
              onClick={() => addNode(type)}
              className="border-hairline text-ink-secondary hover:border-axis hover:text-ink rounded border px-2 py-1 text-xs disabled:opacity-50"
            >
              + {type}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-2 p-3">
        <div className="flex items-center gap-2">
          <span className="text-ink-muted text-xs font-medium tracking-wide uppercase">
            Components
          </span>
          <Badge>{nodes.length}</Badge>
        </div>
        {nodes.length === 0 ? (
          <p className="text-ink-muted text-xs">Add components from the palette above.</p>
        ) : (
          nodes.map((node) => (
            <div key={node.id} className="flex items-center gap-2">
              <Badge>{node.type}</Badge>
              <input
                value={node.label}
                disabled={disabled}
                placeholder="name it"
                onChange={(event) =>
                  setNodes((current) =>
                    current.map((n) => (n.id === node.id ? { ...n, label: event.target.value } : n)),
                  )
                }
                className="border-hairline bg-surface min-w-0 flex-1 rounded border px-2 py-1 text-sm"
              />
              <button
                type="button"
                disabled={disabled}
                onClick={() => removeNode(node.id)}
                aria-label={`Remove ${node.label || node.type}`}
                className="text-ink-muted hover:text-ink px-1 text-xs"
              >
                ✕
              </button>
            </div>
          ))
        )}
      </div>

      <div className="border-hairline space-y-2 border-t p-3">
        <div className="flex items-center gap-2">
          <span className="text-ink-muted text-xs font-medium tracking-wide uppercase">
            Connections
          </span>
          <Badge>{edges.length}</Badge>
          <Button
            size="sm"
            variant="secondary"
            disabled={disabled || nodes.length < 2}
            onClick={addEdge}
          >
            + connection
          </Button>
        </div>
        {edges.map((edge) => (
          <div key={edge.id} className="flex flex-wrap items-center gap-2">
            <NodeSelect
              nodes={nodes}
              value={edge.from}
              disabled={disabled}
              onChange={(value) =>
                setEdges((current) =>
                  current.map((e) => (e.id === edge.id ? { ...e, from: value } : e)),
                )
              }
            />
            <span className="text-ink-muted text-xs">→</span>
            <NodeSelect
              nodes={nodes}
              value={edge.to}
              disabled={disabled}
              onChange={(value) =>
                setEdges((current) =>
                  current.map((e) => (e.id === edge.id ? { ...e, to: value } : e)),
                )
              }
            />
            <input
              value={edge.label}
              disabled={disabled}
              placeholder="what flows"
              onChange={(event) =>
                setEdges((current) =>
                  current.map((e) => (e.id === edge.id ? { ...e, label: event.target.value } : e)),
                )
              }
              className="border-hairline bg-surface min-w-0 flex-1 rounded border px-2 py-1 text-sm"
            />
            <button
              type="button"
              disabled={disabled}
              onClick={() => setEdges((current) => current.filter((e) => e.id !== edge.id))}
              aria-label="Remove connection"
              className="text-ink-muted hover:text-ink px-1 text-xs"
            >
              ✕
            </button>
          </div>
        ))}
      </div>

      <div className="border-hairline border-t p-3">
        <label
          htmlFor="design-notes"
          className="text-ink-muted mb-1 block text-xs font-medium tracking-wide uppercase"
        >
          Trade-offs and capacity
        </label>
        <textarea
          id="design-notes"
          value={notes}
          disabled={disabled}
          onChange={(event) => setNotes(event.target.value)}
          rows={6}
          placeholder="Estimates, bottlenecks, what you would give up first."
          className="border-hairline bg-surface text-ink w-full resize-y rounded-md border p-2 text-sm"
        />
      </div>
    </div>
  );
}

function NodeSelect({
  nodes,
  value,
  disabled,
  onChange,
}: {
  nodes: Node[];
  value: number;
  disabled?: boolean;
  onChange: (value: number) => void;
}) {
  return (
    <select
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(Number(event.target.value))}
      className="border-hairline bg-surface text-ink rounded border px-2 py-1 text-sm"
    >
      {nodes.map((node) => (
        <option key={node.id} value={node.id}>
          {node.label || node.type}
        </option>
      ))}
    </select>
  );
}
