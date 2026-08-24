/**
 * The small set of primitives everything else is built from.
 *
 * shadcn/ui's model is that components are copied into the repo and owned
 * there rather than imported from a package, so these are written by hand in
 * that shape — `cva` variants, a `cn` merge, and no runtime dependency beyond
 * the two utility libraries. Nothing here knows anything about interviewing.
 */

import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps, ReactNode } from "react";
import { cn } from "@/lib/cn";

export function Card({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "bg-surface rounded-lg border border-hairline shadow-[0_1px_2px_rgba(0,0,0,0.04)]",
        className,
      )}
      {...props}
    />
  );
}

export function CardHeader({
  title,
  hint,
  action,
  className,
}: {
  title: ReactNode;
  hint?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-start justify-between gap-4 px-4 pt-4 pb-2", className)}>
      <div className="min-w-0">
        <h2 className="text-ink text-sm font-semibold tracking-tight">{title}</h2>
        {hint ? <p className="text-ink-muted mt-0.5 text-xs">{hint}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

export function CardBody({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("px-4 pb-4", className)} {...props} />;
}

const button = cva(
  "inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        primary: "bg-accent text-accent-ink hover:opacity-90",
        secondary: "bg-sunken text-ink border border-hairline hover:border-axis",
        ghost: "text-ink-secondary hover:bg-sunken hover:text-ink",
        danger: "border border-transparent bg-[var(--status-critical)] text-white hover:opacity-90",
      },
      size: {
        sm: "h-8 px-3",
        md: "h-9 px-4",
        lg: "h-11 px-6 text-base",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export function Button({
  className,
  variant,
  size,
  ...props
}: ComponentProps<"button"> & VariantProps<typeof button>) {
  return <button className={cn(button({ variant, size }), className)} {...props} />;
}

const badge = cva(
  "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap",
  {
    variants: {
      tone: {
        neutral: "bg-sunken text-ink-secondary border border-hairline",
        accent: "border border-transparent bg-[var(--accent)] text-[var(--accent-ink)]",
        good: "border border-[var(--status-good)] text-[var(--status-good-text)]",
        warning: "border border-[var(--status-warning)] text-ink",
        serious: "border border-[var(--status-serious)] text-ink",
        critical: "border border-[var(--status-critical)] text-ink",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

/**
 * A status badge always carries its label. The palette's status colours are
 * sub-3:1 on the light surface by design, and the mitigation is that the text
 * is the message and the colour only reinforces it.
 */
export function Badge({
  className,
  tone,
  ...props
}: ComponentProps<"span"> & VariantProps<typeof badge>) {
  return <span className={cn(badge({ tone }), className)} {...props} />;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("bg-sunken animate-pulse rounded", className)} />;
}

export function Empty({ title, detail }: { title: string; detail?: ReactNode }) {
  return (
    <div className="border-hairline rounded-md border border-dashed px-4 py-8 text-center">
      <p className="text-ink-secondary text-sm">{title}</p>
      {detail ? <p className="text-ink-muted mx-auto mt-1 max-w-prose text-xs">{detail}</p> : null}
    </div>
  );
}

/**
 * A headline number. `note` is not decoration — a figure whose denominator is
 * invisible reads as more complete than it is, which is the specific failure
 * `GET /mastery` reporting `measured` alongside its rows exists to prevent.
 */
export function Stat({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: ReactNode;
  note?: ReactNode;
  tone?: "default" | "muted";
}) {
  return (
    <div className="min-w-0">
      <div className="text-ink-muted text-xs font-medium tracking-wide uppercase">{label}</div>
      <div
        className={cn(
          "mt-1 truncate text-2xl font-semibold",
          tone === "muted" ? "text-ink-muted" : "text-ink",
        )}
      >
        {value}
      </div>
      {note ? <div className="text-ink-muted mt-0.5 text-xs">{note}</div> : null}
    </div>
  );
}
