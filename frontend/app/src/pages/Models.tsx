import { UsageTable } from "../components/UsageTable";
import type { ModelUsage } from "../api";

export function Models({
  rows,
  query,
  onQueryChange,
}: {
  rows: ModelUsage[];
  query: string;
  onQueryChange: (value: string) => void;
}) {
  return (
    <UsageTable
      rows={rows}
      label={(r) => r.model}
      title="model usage"
      subtitle="priced by model family"
      header="model"
      query={query}
      onQueryChange={onQueryChange}
      filename="model-usage"
    />
  );
}
