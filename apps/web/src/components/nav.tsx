"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";

const LINKS = [
  { href: "/", label: "Dashboard" },
  { href: "/session/new", label: "New session" },
  { href: "/practice", label: "Practice" },
  { href: "/concepts", label: "Concepts" },
  { href: "/history", label: "History" },
  { href: "/corpus", label: "Corpus" },
  { href: "/costs", label: "Costs" },
] as const;

export function Nav() {
  const pathname = usePathname();

  return (
    <header className="border-hairline bg-surface sticky top-0 z-20 border-b">
      <div className="mx-auto flex h-14 max-w-7xl items-center gap-6 px-4">
        <Link href="/" className="text-ink text-sm font-semibold tracking-tight">
          interview<span className="text-ink-muted">_helper</span>
        </Link>
        <nav className="flex items-center gap-1 overflow-x-auto" aria-label="Main">
          {LINKS.map((link) => {
            const active =
              link.href === "/" ? pathname === "/" : pathname.startsWith(link.href);
            return (
              <Link
                key={link.href}
                href={link.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "rounded-md px-3 py-1.5 text-sm whitespace-nowrap transition-colors",
                  active
                    ? "bg-sunken text-ink font-medium"
                    : "text-ink-secondary hover:text-ink hover:bg-sunken",
                )}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
