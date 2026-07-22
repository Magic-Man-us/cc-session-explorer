import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

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
  const skipNextPush = useRef(false);

  const { data, isPending, isError, error, refetch } = useQuery({
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
    const onPopState = () => {
      skipNextPush.current = true;
      setPage(pageFromPath(window.location.pathname));
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const stamp = isPending
    ? "Loading latest snapshot"
    : isError
      ? "Snapshot unavailable"
      : `Generated ${data.generated_at.slice(0, 19).replace("T", " ")}`;

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
              <div className="ju-muted cc-page-stamp">{stamp}</div>
            </div>
            <Button onClick={() => refetch()}>Refresh data</Button>
          </header>
          <div className="cc-page-content">{renderPage()}</div>
        </main>
      </Root>
    </NavProvider>
  );
}
