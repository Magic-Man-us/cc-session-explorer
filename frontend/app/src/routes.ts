import type { NavHeading, NavItem } from "@cc-session/dashboard-ui";

/** Every routable page in the dashboard. Detail pages carry their own route params,
 * so stale selection state cannot keep a list page hidden after navigation. */
export type Page =
  | { kind: "overview" }
  | { kind: "time" }
  | { kind: "time-bucket"; grain: string; bucket: string }
  | { kind: "live-feed" }
  | { kind: "sessions" }
  | { kind: "models" }
  | { kind: "projects" }
  | { kind: "data" }
  | { kind: "context-sessions" }
  | { kind: "context-session"; sessionId: string }
  | { kind: "context-projects" }
  | { kind: "context-project"; project: string }
  | { kind: "context-ledger" };

/** Sidebar entries are always parameter-free list/dashboard pages. */
export type NavKind =
  | "overview"
  | "time"
  | "live-feed"
  | "sessions"
  | "models"
  | "projects"
  | "data"
  | "context-sessions"
  | "context-projects"
  | "context-ledger";

export const NAV: ReadonlyArray<NavItem<NavKind> | NavHeading> = [
  { heading: "Explore" },
  { value: "overview", label: "Dashboard" },
  { value: "live-feed", label: "Live Session" },
  { value: "sessions", label: "Session History" },
  { value: "time", label: "Usage Over Time" },
  { heading: "Breakdowns" },
  { value: "projects", label: "Projects" },
  { value: "models", label: "Models" },
  { value: "data", label: "Data Source" },
  { heading: "Context Replay" },
  { value: "context-sessions", label: "Session Explorer" },
  { value: "context-projects", label: "Project Explorer" },
  { value: "context-ledger", label: "Context Ledger" },
];

export const NAV_LABELS = Object.fromEntries(
  NAV.filter((item): item is NavItem<NavKind> => !("heading" in item)).map((item) => [item.value, item.label]),
) as Record<NavKind, string>;

export const isContextPage = (page: Page): boolean => page.kind.startsWith("context-");

/** Detail pages highlight their parent collection in the sidebar. */
export function navKindFor(page: Page): NavKind {
  switch (page.kind) {
    case "time-bucket":
      return "time";
    case "context-session":
      return "context-sessions";
    case "context-project":
      return "context-projects";
    default:
      return page.kind;
  }
}

export function pageForNavKind(kind: NavKind): Page {
  return { kind } as Page;
}

export function pathForPage(page: Page): string {
  switch (page.kind) {
    case "time-bucket":
      return `/cost/time/${encodeURIComponent(page.grain)}/${encodeURIComponent(page.bucket)}`;
    case "context-session":
      return `/context/sessions/${encodeURIComponent(page.sessionId)}`;
    case "context-project":
      return `/context/projects/${encodeURIComponent(page.project)}`;
    case "context-sessions":
      return "/context/sessions";
    case "context-projects":
      return "/context/projects";
    case "context-ledger":
      return "/context/ledger";
    default:
      return `/cost/${page.kind}`;
  }
}

const COST_KINDS: ReadonlySet<string> = new Set<NavKind>([
  "overview",
  "time",
  "live-feed",
  "sessions",
  "models",
  "projects",
  "data",
]);

export function pageFromPath(pathname: string): Page {
  const parts = pathname.split("/").filter(Boolean).map(decodeURIComponent);
  const [section, sub, a, b] = parts;

  if (section === "context") {
    if (sub === "sessions") return a ? { kind: "context-session", sessionId: a } : { kind: "context-sessions" };
    if (sub === "projects") return a ? { kind: "context-project", project: a } : { kind: "context-projects" };
    if (sub === "ledger") return { kind: "context-ledger" };
  }

  if (section === "cost") {
    if (sub === "time" && a && b) return { kind: "time-bucket", grain: a, bucket: b };
    if (sub && COST_KINDS.has(sub)) return pageForNavKind(sub as NavKind);
  }

  return { kind: "overview" };
}
