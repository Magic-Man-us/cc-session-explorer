import type { NavHeading, NavItem } from "@cc-session/dashboard-ui";

export type CostView =
  | "overview"
  | "time"
  | "live-log"
  | "sessions"
  | "models"
  | "projects"
  | "data";

export type ContextView = "ctx-sessions" | "ctx-projects" | "ctx-ledger";

export type View = CostView | ContextView;

// One window, both lenses: the cost/usage views and the context-window views live
// in a single sectioned sidebar instead of behind a lens toggle.
export const NAV: ReadonlyArray<NavItem<View> | NavHeading> = [
  { heading: "cost & usage" },
  { value: "overview", label: "Overview" },
  { value: "time", label: "Time" },
  { value: "live-log", label: "Live Feed" },
  { value: "sessions", label: "Session History" },
  { value: "models", label: "Models" },
  { value: "projects", label: "Projects" },
  { value: "data", label: "Data" },
  { heading: "context windows" },
  { value: "ctx-sessions", label: "Sessions" },
  { value: "ctx-projects", label: "Projects" },
  { value: "ctx-ledger", label: "Ledger" },
];

export const VIEW_LABELS = Object.fromEntries(
  NAV.filter((item): item is NavItem<View> => !("heading" in item)).map((item) => [item.value, item.label]),
) as Record<View, string>;

export const isContextView = (view: View): view is ContextView => view.startsWith("ctx-");

export const COST_VIEWS: ReadonlySet<string> = new Set<CostView>([
  "overview",
  "time",
  "live-log",
  "sessions",
  "models",
  "projects",
  "data",
]);

export interface Route {
  view: View;
  contextSession: string | null;
  contextProject: string | null;
  timeGrain: string | null;
  timeBucket: string | null;
}

const EMPTY_DRILLDOWN = { contextSession: null, contextProject: null, timeGrain: null, timeBucket: null } as const;

/** The URL a given view/selection renders as — the inverse of `routeFromPath`. */
export function pathForView(
  view: View,
  contextSession: string | null,
  contextProject: string | null,
  timeGrain: string | null,
  timeBucket: string | null,
): string {
  if (view === "ctx-sessions") {
    return contextSession ? `/context/sessions/${encodeURIComponent(contextSession)}` : "/context/sessions";
  }
  if (view === "ctx-projects") {
    return contextProject ? `/context/projects/${encodeURIComponent(contextProject)}` : "/context/projects";
  }
  if (view === "ctx-ledger") return "/context/ledger";
  if (view === "time" && timeGrain && timeBucket) {
    return `/cost/time/${encodeURIComponent(timeGrain)}/${encodeURIComponent(timeBucket)}`;
  }
  return `/cost/${view}`;
}

/** Parses a URL path into the view/selection it names — the inverse of `pathForView`.
 *  Anything unrecognized falls back to the overview so a stale/hand-typed link never 404s. */
export function routeFromPath(pathname: string): Route {
  const [, section, sub, id, extra] = pathname.split("/");
  if (section === "context") {
    if (sub === "projects") {
      return { view: "ctx-projects", ...EMPTY_DRILLDOWN, contextProject: id ? decodeURIComponent(id) : null };
    }
    if (sub === "ledger") return { view: "ctx-ledger", ...EMPTY_DRILLDOWN };
    return { view: "ctx-sessions", ...EMPTY_DRILLDOWN, contextSession: id ? decodeURIComponent(id) : null };
  }
  if (section === "cost" && sub && COST_VIEWS.has(sub)) {
    if (sub === "time" && id && extra) {
      return { view: "time", ...EMPTY_DRILLDOWN, timeGrain: decodeURIComponent(id), timeBucket: decodeURIComponent(extra) };
    }
    return { view: sub as View, ...EMPTY_DRILLDOWN };
  }
  return { view: "overview", ...EMPTY_DRILLDOWN };
}
