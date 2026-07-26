import { queryOptions, skipToken } from "@tanstack/react-query";

import {
  fetchContextTrace,
  fetchContextTraceWindow,
} from "../../api";
import type { ProviderScope } from "../../provider";

export const contextTraceKeys = {
  all: ["context-trace"] as const,
  session: (session: string, provider: ProviderScope) =>
    [...contextTraceKeys.all, "session", session, provider] as const,
  window: (
    session: string,
    center: string | null,
    minutes: number,
    provider: ProviderScope,
  ) =>
    [
      ...contextTraceKeys.session(session, provider),
      "window",
      center,
      minutes,
    ] as const,
};

export const contextTraceOptions = (
  session: string,
  provider: ProviderScope,
) =>
  queryOptions({
    queryKey: contextTraceKeys.session(session, provider),
    queryFn: ({ signal }) => fetchContextTrace(session, provider, signal),
    staleTime: 5_000,
  });

export const contextTraceWindowOptions = (
  session: string,
  center: string | null,
  provider: ProviderScope,
  minutes = 30,
) =>
  queryOptions({
    queryKey: contextTraceKeys.window(session, center, minutes, provider),
    queryFn:
      center === null
        ? skipToken
        : ({ signal }) =>
            fetchContextTraceWindow(
              session,
              center,
              minutes,
              provider,
              signal,
            ),
    staleTime: 5_000,
  });
