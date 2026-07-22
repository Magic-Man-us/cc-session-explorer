import { createContext, useContext, type ReactNode } from "react";
import type { Page } from "./routes";

export interface NavRequest {
  page: Page;
  /** Prefills a destination list filter when navigating from a related record. */
  query?: string;
}

type Navigate = (request: NavRequest) => void;

const NavContext = createContext<Navigate | null>(null);

export function NavProvider({ navigate, children }: { navigate: Navigate; children: ReactNode }) {
  return <NavContext.Provider value={navigate}>{children}</NavContext.Provider>;
}

export function useNavigate(): Navigate {
  const navigate = useContext(NavContext);
  if (!navigate) throw new Error("useNavigate must be used within NavProvider");
  return navigate;
}

export const toSessions = (query: string): NavRequest => ({ page: { kind: "sessions" }, query });
export const toModels = (query: string): NavRequest => ({ page: { kind: "models" }, query });
export const toProjects = (query: string): NavRequest => ({ page: { kind: "projects" }, query });
export const toContextSession = (sessionId: string): NavRequest => ({
  page: { kind: "context-session", sessionId },
});
export const toContextProject = (project: string): NavRequest => ({
  page: { kind: "context-project", project },
});
export const toTimeBucket = (grain: string, bucket: string): NavRequest => ({
  page: { kind: "time-bucket", grain, bucket },
});
