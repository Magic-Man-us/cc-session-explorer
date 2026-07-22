import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { Breadcrumbs, Button, EmptyState, LoadingState, Root, Sidebar, type Crumb } from "@cc-session/dashboard-ui";

import { fetchSnapshot } from "./api";
import { NavProvider, type NavRequest } from "./nav";
import {
  NAV,
  NAV_LABELS,
  isContextPage,
  navKindFor,
  pageForNavKind,
  pageFromPath,
  pathForPage,
  type Page,
} from "./routes";
import { Overview } from "./pages/Overview";
import { Time } from "./pages/Time";
import { BucketDetail } from "./pages/BucketDetail";
import { LiveFeed } from "./pages/LiveFeed";
import { Sessions } from "./pages/Sessions";
import { Models } from "./pages/Models";
import { Projects } from "./pages/Projects";
import { Data } from "./pages/Data";
import { ContextSessions } from "./pages/context/Sessions";
import { ContextSessionDetail } from "./pages/context/SessionDetail";
import { ContextProjects } from "./pages/context/Projects";
import { ContextProjectDetail } from "./pages/context/ProjectDetail";
import { ContextLedger } from "./pages/context/Ledger";

function pageTitle(page: Page): string {
  switch (page.kind) {
    case "overview":
      return "Session dashboard";
    case "live-feed":
      return "Live session monitor";
    case "sessions":
      return "Session history";
    case "time":
      return "Usage over time";
    case "time-bucket":
      return "Time bucket details";
    case "models":
      return "Model usage";
    case "projects":
      return "Project usage";
    case "data":
      return "Data source";
    case "context-sessions":
      return "Context session explorer";
    case "context-session":
      return "Session context replay";
    case "context-projects":
      return "Context project explorer";
    case "context-project":
      return "Project context breakdown";
    case "context-ledger":
      return "Context ledger";
  }
}

function pageDescription(page: Page): string {
  switch (page.kind) {
    case "overview":
      return "Start with total spend, token flow, recent activity, and data-health signals.";
    case "live-feed":
      return "Follow active Claude sessions and expand each message to inspect its tools and thinking.";
    case "sessions":
      return "Search historical sessions; select a session identifier to open its full context replay.";
    case "time":
      return "Compare usage by week, day, hour, or five-minute interval and drill into any bucket.";
    case "time-bucket":
      return `Inspect the sessions and transcript activity recorded in ${page.bucket}.`;
    case "models":
      return "Compare token volume, turns, and estimated cost across models.";
    case "projects":
      return "Compare usage across projects and jump directly into their sessions.";
    case "data":
      return "Inspect the generated snapshot and the underlying ledger source.";
    case "context-sessions":
      return "Browse captured transcripts and open the context-flow report for any session.";
    case "context-session":
      return "Trace token flow, context chains, tool activity, and the complete transcript in one report.";
    case "context-projects":
      return "Find projects with captured context data and inspect their session breakdowns.";
    case "context-project":
      return "Compare the context-window load across sessions for this project.";
    case "context-ledger":
      return "Review context-window events across the complete historical ledger.";
  }
}

function breadcrumbs(page: Page, go: (page: Page) => void): Crumb[] {
  const root = isContextPage(page)
    ? { label: "Context replay", onClick: () => go({ kind: "context-sessions" }) }
    : { label: "Cost & usage", onClick: () => go({ kind: "overview" }) };

  switch (page.kind) {
    case "overview":
      return [{ label: "Cost & usage" }];
    case "time-bucket":
      return [root, { label: "Usage Over Time", onClick: () => go({ kind: "time" }) }, { label: page.bucket }];
    case "context-session":
      return [root, { label: "Sessions", onClick: () => go({ kind: "context-sessions" }) }, { label: page.sessionId.slice(0, 12) }];
    case "context-project":
      return [root, { label: "Projects", onClick: () => go({ kind: "context-projects" }) }, { label: page.project }];
    default:
      return [root, { label: NAV_LABELS[navKindFor(page)] }];
  }
}

export function App() {
  const [page, setPage] = useState<Page>(() => pageFromPath(window.location.pathname));
  const [sessionsQuery, setSessionsQuery] = useState("");
  const [modelsQuery, setModelsQuery] = useState("");
  const [projectsQuery, setProjectsQuery] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const skipNextPush = useRef(false);
  const queryClient = useQueryClient();

  const { data, isPending, isError, error } = useQuery({
    queryKey: ["snapshot"],
    queryFn: fetchSnapshot,
  });

  const go = (nextPage: Page) => setPage(nextPage);
  const navigate = (request: NavRequest) => {
    setPage(request.page);
    if (request.query === undefined) return;
    if (request.page.kind === "sessions") setSessionsQuery(request.query);
    if (request.page.kind === "models") setModelsQuery(request.query);
    if (request.page.kind === "projects") setProjectsQuery(request.query);
  };

  const refreshData = async () => {
    setRefreshing(true);
    try {
      await queryClient.invalidateQueries({ refetchType: "active" });
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    const path = pathForPage(page);
    if (skipNextPush.current) {
      skipNextPush.current = false;
      if (window.location.pathname !== path) window.history.replaceState(null, "", path);
      return;
    }
    if (window.location.pathname !== path) window.history.pushState(null, "", path);
  }, [page]);

  useEffect(() => {
    document.title = `${pageTitle(page)} · cc-session-explorer`;
  }, [page]);

  useEffect(() => {
    const onPopState = () => {
      skipNextPush.current = true;
      setPage(pageFromPath(window.location.pathname));
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const stamp = isPending
    ? "Loading latest usage snapshot"
    : isError
      ? "Usage snapshot unavailable"
      : `Usage snapshot generated ${data.generated_at.slice(0, 19).replace("T", " ")}`;

  const renderPage = () => {
    switch (page.kind) {
      case "context-sessions":
        return <ContextSessions />;
      case "context-session":
        return <ContextSessionDetail session={page.sessionId} />;
      case "context-projects":
        return <ContextProjects />;
      case "context-project":
        return <ContextProjectDetail project={page.project} />;
      case "context-ledger":
        return <ContextLedger />;
      default:
        if (isError) return <EmptyState>{error.message}</EmptyState>;
        if (isPending) return <LoadingState>Loading dashboard…</LoadingState>;
        switch (page.kind) {
          case "overview":
            return <Overview data={data} />;
          case "time":
            return <Time data={data} />;
          case "time-bucket":
            return <BucketDetail grain={page.grain} bucket={page.bucket} />;
          case "live-feed":
            return <LiveFeed />;
          case "sessions":
            return <Sessions rows={data.recent_sessions} query={sessionsQuery} onQueryChange={setSessionsQuery} />;
          case "models":
            return <Models rows={data.models} query={modelsQuery} onQueryChange={setModelsQuery} />;
          case "projects":
            return <Projects rows={data.projects} query={projectsQuery} onQueryChange={setProjectsQuery} />;
          case "data":
            return <Data data={data} />;
        }
    }
  };

  return (
    <NavProvider navigate={navigate}>
      <Root className="cc-shell">
        <Sidebar
          brand="cc-session-explorer"
          subtitle="Claude session intelligence"
          items={NAV}
          active={navKindFor(page)}
          onSelect={(kind) => go(pageForNavKind(kind))}
        />
        <main className="cc-main">
          <header className="cc-page-header">
            <div className="cc-page-heading">
              <Breadcrumbs crumbs={breadcrumbs(page, go)} />
              <h1>{pageTitle(page)}</h1>
              <p className="cc-page-description">{pageDescription(page)}</p>
              <div className="ju-muted cc-page-stamp">{stamp}</div>
            </div>
            <Button disabled={refreshing} onClick={refreshData}>
              {refreshing ? "Refreshing…" : "Refresh active data"}
            </Button>
          </header>
          <div className="cc-page-content">{renderPage()}</div>
        </main>
      </Root>
    </NavProvider>
  );
}
