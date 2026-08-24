"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError } from "@/lib/api";

/**
 * Server state lives in TanStack Query (docs/WEB.md). Two defaults are set
 * deliberately:
 *
 * - **A 401 is never retried.** `api.ts` has already redirected to the login
 *   route by the time the error surfaces; retrying would fire three more
 *   requests at a server that has no reason to change its mind.
 * - **A 409 is never retried either.** "Wrong state" is an answer, not a
 *   transient fault — the report of a session that has not finished will not
 *   become available by asking again a second later.
 */
export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            refetchOnWindowFocus: false,
            retry: (failureCount, error) => {
              if (error instanceof ApiError && [401, 403, 404, 409, 422].includes(error.status)) {
                return false;
              }
              return failureCount < 2;
            },
          },
          mutations: { retry: false },
        },
      }),
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
