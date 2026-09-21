"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import type { Mode } from "./types";

export const keys = {
  mastery: ["mastery"] as const,
  weaknesses: (mode?: Mode) => ["weaknesses", mode ?? "all"] as const,
  concept: (id: string) => ["concept", id] as const,
  // `limit` is part of the key, and that is load-bearing. Without it the dashboard's
  // 20-row page and History's 25-row page shared one entry: arriving at History from the
  // dashboard inside `staleTime` found it fresh, so History's own fetch never ran and the
  // page rendered its empty state over a cache holding twenty sessions.
  sessions: (cursor?: string, limit = 20) => ["sessions", cursor ?? "first", limit] as const,
  // History's accumulated pages, kept by `useInfiniteQuery` rather than in component
  // state — a separate entry from the single page the dashboard reads.
  sessionPages: (limit: number) => ["sessions", "paged", limit] as const,
  session: (id: string) => ["session", id] as const,
  report: (id: string) => ["report", id] as const,
  plan: (mode: Mode, minutes: number) => ["plan", mode, minutes] as const,
  corpus: ["corpus-status"] as const,
  costs: (days: number) => ["costs", days] as const,
  budget: (sessionId?: string) => ["budget", sessionId ?? "day"] as const,
  reviewQueue: ["review-queue"] as const,
};

export const useMastery = () => useQuery({ queryKey: keys.mastery, queryFn: api.mastery });
export const useCorpusStatus = () => useQuery({ queryKey: keys.corpus, queryFn: api.corpusStatus });
export const useCosts = (days = 7) =>
  useQuery({ queryKey: keys.costs(days), queryFn: () => api.costs(days) });
export const useReviewQueue = () =>
  useQuery({ queryKey: keys.reviewQueue, queryFn: api.reviewQueue });
export const useSessions = (cursor?: string) =>
  useQuery({ queryKey: keys.sessions(cursor), queryFn: () => api.listSessions({ cursor }) });
export const useWeaknesses = (mode?: Mode, limit = 20) =>
  useQuery({ queryKey: [...keys.weaknesses(mode), limit], queryFn: () => api.weaknesses({ mode, limit }) });

/**
 * Every concept in the taxonomy.
 *
 * One request to `GET /concepts`. Until 2026-08-25 there was no such endpoint, and this
 * assembled the taxonomy from **one weakness ranking per mode** — four requests to answer
 * a question about static build-time content — because `GET /mastery` returns only
 * *measured* concepts and carries no name or domain. The endpoint now exists and also
 * reports the prerequisite edges and which concepts are servable, neither of which the
 * ranking could supply.
 */
export function useTaxonomy() {
  const query = useQuery({
    queryKey: ["concepts"],
    queryFn: () => api.concepts(),
    // Build-time content: it cannot change while the server is up.
    //
    // `gcTime` has to say so as well, and did not. `staleTime` alone only means
    // "do not refetch while something is watching"; five minutes after the last
    // consumer unmounts, the default `gcTime` evicts the entry and the next
    // mount pays for it again. Three pages read this — the dashboard,
    // `/concepts` and the picker on every `/practice/{id}` — so tagging a
    // problem, going for coffee and tagging another re-downloaded 81 KB of
    // taxonomy that by construction had not changed.
    staleTime: Infinity,
    gcTime: Infinity,
  });

  return {
    concepts: query.data?.concepts ?? [],
    servable: query.data?.servable ?? 0,
    isLoading: query.isLoading,
    error: query.error,
  };
}
