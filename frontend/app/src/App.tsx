import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Breadcrumbs, Button, EmptyState, LoadingState, Root, Sidebar, type Crumb } from "@cc-session/dashboard-ui";

import { fetchSnapshot } from "./api";
import { NavProvider, type NavRequest } from "./nav";
import { NAV, VIEW_LABELS, isContextView, pathForView, routeFromPath, type View } from "./routes";
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

export function App() {
  const [view, setView] = useState<View>(() => routeFromPath(window.location.pathname).view);
  const { data, isPending, isError, error, refetch } = useQuery({ queryKey: ["snapshot"], queryFn: fetchSnapshot });
  const stamp = isPending
    ? "Loading"
    : isError
      ? "Unavailable"
      : "Generated " + data.generated_at.slice(0, 19).replace("T", " ");

  const [sessionsQuery, setSessionsQuery] = useState("");
  const [modelsQuery, setModelsQuery] = useState("");
  const [projectsQuery, setProjectsQuery] = useState("");
  const [contextSession, setContextSession] = useState<string | null>(
    () => routeFromPath(window.location.pathname).contextSession,
  );
  const [contextProject, setContextProject] = useState<string | null>(
    () => routeFromPath(window.location.pathname).contextProject,
  );
  const [timeGrain, setTimeGrain] = useState<string | null>(
    () => routeFromPath(window.location.pathname).timeGrain,
  );
  const [timeBucket, setTimeBucket] = useState<string | null>(
    () => routeFromPath(window.location.pathname).timeBucket,
  );

  // Keep the URL, browser history, and this state in sync both ways: a state change here
  // pushes a history entry (so back/forward and shareable links work), and popstate (back/
  // forward, or a fresh load) re-derives state from the URL without re-pushing it.
  const skipNextPush = useRef(false);
  useEffect(() => {
    const path = pathForView(view, contextSession, contextProject, timeGrain, timeBucket);
    if (skipNextPush.current) {
      skipNextPush.current = false;
      if (window.location.pathname !== path) window.history.replaceState(null, "", path);
      return;
    }
    if (window.location.pathname !== path) window.history.pushState(null, "", path);
  }, [view, contextSession, contextProject, timeGrain, timeBucket]);

  useEffect(() => {
    const onPopState = () => {
      const route = routeFromPath(window.location.pathname);
      skipNextPush.current = true;
      setView(route.view);
      setContextSession(route.contextSession);
      setContextProject(route.contextProject);
      setTimeGrain(route.timeGrain);
      setTimeBucket(route.timeBucket);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const navigate = (request: NavRequest) => {
    if (request.lens === "context") {
      setView(request.contextView ?? "ctx-sessions");
      if (request.contextSession !== undefined) setContextSession(request.contextSession);
      if (request.contextProject !== undefined) setContextProject(request.contextProject);
      return;
    }
    setView(request.view ?? "overview");
    if (request.timeGrain !== undefined) setTimeGrain(request.timeGrain);
    if (request.timeBucket !== undefined) setTimeBucket(request.timeBucket);
    if (request.query !== undefined) {
      if (request.view === "sessions") setSessionsQuery(request.query);
      if (request.view === "models") setModelsQuery(request.query);
      if (request.view === "projects") setProjectsQuery(request.query);
    }
  };

  // The trail shown above the page title — lens ▸ view ▸ selected item. Each non-terminal
  // segment clears one level of drill-down rather than resetting the whole view.
  const crumbs: Crumb[] = (() => {
    if (view === "ctx-sessions") {
      const trail: Crumb[] = [{ label: "Context windows", onClick: () => setView("ctx-sessions") }];
      trail.push(
        contextSession
          ? { label: "Sessions", onClick: () => setContextSession(null) }
          : { label: "Sessions" },
      );
      if (contextSession) trail.push({ label: contextSession.slice(0, 12) });
      return trail;
    }
    if (view === "ctx-projects") {
      const trail: Crumb[] = [{ label: "Context windows", onClick: () => setView("ctx-sessions") }];
      trail.push(
        contextProject
          ? { label: "Projects", onClick: () => setContextProject(null) }
          : { label: "Projects" },
      );
      if (contextProject) trail.push({ label: contextProject });
      return trail;
    }
    if (view === "ctx-ledger") {
      return [{ label: "Context windows", onClick: () => setView("ctx-sessions") }, { label: "Ledger" }];
    }
    if (view === "overview") return [{ label: "Cost & usage" }];
    if (view === "time" && timeBucket) {
      return [
        { label: "Cost & usage", onClick: () => setView("overview") },
        { label: "Time", onClick: () => setTimeBucket(null) },
        { label: timeBucket },
      ];
    }
    return [{ label: "Cost & usage", onClick: () => setView("overview") }, { label: VIEW_LABELS[view] }];
  })();

  return (
    <NavProvider navigate={navigate}>
      <Root style={{ display: "grid", gridTemplateColumns: "248px 1fr", minHeight: "100vh" }}>
        <Sidebar brand="cc-sessions" subtitle="cost · context" items={NAV} active={view} onSelect={setView} />
        <main style={{ padding: 24, minWidth: 0 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 18, marginBottom: 22 }}>
            <div>
              <Breadcrumbs crumbs={crumbs} />
              <h1 style={{ margin: 0, fontSize: 24, lineHeight: 1.15 }}>
                {isContextView(view) ? "Context-window replay" : "Session cost and token flow"}
              </h1>
              <div className="ju-muted" style={{ fontSize: 12, marginTop: 6 }}>{stamp}</div>
            </div>
            <Button onClick={() => refetch()}>Refresh</Button>
          </div>

          {view === "ctx-sessions" && (contextSession ? <ContextSessionDetail session={contextSession} /> : <ContextSessions />)}
          {view === "ctx-projects" && (contextProject ? <ContextProjectDetail project={contextProject} /> : <ContextProjects />)}
          {view === "ctx-ledger" && <ContextLedger />}
          {!isContextView(view) && isError && <EmptyState>{error.message}</EmptyState>}
          {!isContextView(view) && isPending && <LoadingState>Loading dashboard…</LoadingState>}
          {!isContextView(view) && !isPending && !isError && (
            <>
              {view === "overview" && <Overview data={data} />}
              {view === "time" && (timeGrain && timeBucket ? <BucketDetail grain={timeGrain} bucket={timeBucket} /> : <Time data={data} />)}
              {view === "live-log" && <LiveFeed />}
              {view === "sessions" && (
                <Sessions rows={data.recent_sessions} query={sessionsQuery} onQueryChange={setSessionsQuery} />
              )}
              {view === "models" && (
                <Models rows={data.models} query={modelsQuery} onQueryChange={setModelsQuery} />
              )}
              {view === "projects" && (
                <Projects rows={data.projects} query={projectsQuery} onQueryChange={setProjectsQuery} />
              )}
              {view === "data" && <Data data={data} />}
            </>
          )}
        </main>
      </Root>
    </NavProvider>
  );
}
