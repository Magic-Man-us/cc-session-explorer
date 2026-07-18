import { UsageTable } from "../components/UsageTable";
import type { ProjectUsage } from "../api";

export function Projects({
  rows,
  query,
  onQueryChange,
}: {
  rows: ProjectUsage[];
  query: string;
  onQueryChange: (value: string) => void;
}) {
  return (
    <UsageTable
      rows={rows}
      label={(r) => r.project}
      title="project usage"
      subtitle="top 25 by total tokens"
      header="project"
      query={query}
      onQueryChange={onQueryChange}
      filename="project-usage"
    />
  );
}
