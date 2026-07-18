import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { EmptyState, FilterableTable, LoadingState, type Column, type ExportColumn } from "@cc-session/dashboard-ui";
import { fetchContextProjects, type ProjectRef } from "../../api";
import { toContextProject, useNavigate } from "../../nav";
import { fmtBytes } from "./shared";

const PROJECTS_PAGE_SIZE = 10;

const projectExportColumns: ExportColumn<ProjectRef>[] = [
  { header: "project", value: (r) => r.project },
  { header: "sessions", value: (r) => r.session_count },
  { header: "size_bytes", value: (r) => r.total_bytes },
];

/** Context lens: projects list. Clicking a row navigates to its own page,
 *  `/context/projects/:project` (`ContextProjectDetail`) — never expands in place. */
export function ContextProjects() {
  const navigate = useNavigate();
  const [page, setPage] = useState(0);
  const { data: projects, isPending, isError, error } = useQuery({ queryKey: ["context", "projects"], queryFn: fetchContextProjects });

  if (isError) return <EmptyState>{error.message}</EmptyState>;
  if (isPending) return <LoadingState>Loading projects…</LoadingState>;

  const projectColumns: Column<ProjectRef>[] = [
    { key: "project", header: "project", render: (r) => r.project },
    { key: "sessions", header: "sessions", numeric: true, render: (r) => String(r.session_count) },
    { key: "bytes", header: "size", numeric: true, render: (r) => fmtBytes(r.total_bytes) },
  ];

  return (
    <FilterableTable
      title="projects"
      meta="click one for its context breakdown"
      rows={projects}
      columns={projectColumns}
      rowKey={(r) => r.project}
      onRowClick={(r) => navigate(toContextProject(r.project))}
      exportColumns={projectExportColumns}
      filename="context-projects"
      pageSize={PROJECTS_PAGE_SIZE}
      page={page}
      onPageChange={setPage}
    />
  );
}
