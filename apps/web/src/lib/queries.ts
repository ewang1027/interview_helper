"use client";

import { useQueries, useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { MODES, type Mode, type RankedConcept } from "./types";

export const keys = {
  mastery: ["mastery"] as const,
  weaknesses: (mode?: Mode) => ["weaknesses", mode ?? "all"] as const,
  concept: (id: string) => ["concept", id] as const,
  sessions: (cursor?: string) => ["sessions", cursor ?? "first"] as const,
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
 * Every concept in the taxonomy, with its name and domain.
 *
 * There is no `GET /concepts`, and `GET /mastery` returns only concepts that
 * have been *measured* — and without a name or a domain on the row, because
 * `mastery_row_view` projects the mastery table alone. What does carry both is
 * the weakness ranking, which ranks the whole taxonomy rather than the measured
 * part of it (`unseen: true` on the rest).
 *
 * So the taxonomy is assembled from one ranking per mode. `limit` is capped at
 * 100 by the API and the taxonomy holds 159 concepts, which one unfiltered call
 * could not return — but the largest single domain is 52, so the per-mode split
 * is what makes this complete rather than merely convenient.
 */
export function useTaxonomy() {
  const results = useQueries({
    queries: MODES.map((mode) => ({
      queryKey: [...keys.weaknesses(mode), 100],
      queryFn: () => api.weaknesses({ mode, limit: 100 }),
      staleTime: 60_000,
    })),
  });

  const isLoading = results.some((result) => result.isLoading);
  const error = results.find((result) => result.error)?.error ?? null;

  // Deduplicated by id: a concept can be ranked under more than one mode when
  // its domain is served by several, and the same concept twice in a heatmap
  // reads as two concepts.
  const byId = new Map<string, RankedConcept>();
  for (const result of results) {
    for (const concept of result.data?.concepts ?? []) {
      if (!byId.has(concept.concept_id)) byId.set(concept.concept_id, concept);
    }
  }

  return { concepts: [...byId.values()], isLoading, error };
}
