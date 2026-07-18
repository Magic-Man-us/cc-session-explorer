import { createContext, useContext, type ReactNode } from "react";
import type { CostView, ContextView } from "./routes";

export type Lens = "cost" | "context";

/** A cross-view jump: switch lens/tab and optionally prefill a filter or selection so the
 *  destination lands already scoped to what was clicked. */
export interface NavRequest {
  lens: Lens;
  view?: CostView;
  contextView?: ContextView;
  /** Prefills the Sessions/Models/Projects filter box on arrival. */
  query?: string;
  /** Auto-selects a session on the Context lens's Sessions tab. */
  contextSession?: string;
  /** Auto-selects a project on the Context lens's Projects tab. */
  contextProject?: string;
  /** Drills into a bucket on the Time tab (both required together). */
  timeGrain?: string;
  timeBucket?: string;
}

type Navigate = (request: NavRequest) => void;

const NavContext = createContext<Navigate | null>(null);

export function NavProvider({ navigate, children }: { navigate: Navigate; children: ReactNode }) {
  return <NavContext.Provider value={navigate}>{children}</NavContext.Provider>;
}

/** The cross-view navigate function; call from anywhere under `<NavProvider>`. */
export function useNavigate(): Navigate {
  const navigate = useContext(NavContext);
  if (!navigate) throw new Error("useNavigate must be used within NavProvider");
  return navigate;
}

// Convenience builders for the common jump targets, so call sites read as intent, not payload.
export const toSessions = (query: string): NavRequest => ({ lens: "cost", view: "sessions", query });
export const toModels = (query: string): NavRequest => ({ lens: "cost", view: "models", query });
export const toProjects = (query: string): NavRequest => ({ lens: "cost", view: "projects", query });
export const toContextSession = (sessionId: string): NavRequest => ({
  lens: "context",
  contextView: "ctx-sessions",
  contextSession: sessionId,
});
export const toContextProject = (project: string): NavRequest => ({
  lens: "context",
  contextView: "ctx-projects",
  contextProject: project,
});
export const toTimeBucket = (grain: string, bucket: string): NavRequest => ({
  lens: "cost",
  view: "time",
  timeGrain: grain,
  timeBucket: bucket,
});
