import { QueryClient } from "@tanstack/react-query";
import { persistQueryClient } from "@tanstack/react-query-persist-client";
import { createAsyncStoragePersister } from "@tanstack/query-async-storage-persister";

/** The one query client for the app — every `useQuery`/`useInfiniteQuery` call shares this
 *  cache, which is what makes switching between already-fetched views instant. */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
});

const persister = createAsyncStoragePersister({ storage: window.localStorage });

persistQueryClient({
  queryClient,
  persister,
  maxAge: 5 * 60 * 1000,
  dehydrateOptions: {
    // Session-detail payloads (grouped/transcript) are multi-MB and volatile enough to blow
    // localStorage's ~5-10MB quota and break the whole persister; live-lens data is by
    // definition never worth restoring stale. Everything else (list-level views) is small
    // and safe to persist.
    shouldDehydrateQuery: (query) => {
      const [root, sub] = query.queryKey;
      if (root === "live") return false;
      if (root === "context" && sub === "session") return false;
      return true;
    },
  },
});
