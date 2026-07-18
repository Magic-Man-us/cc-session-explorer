import { Pill, fmtTok, type Accent, type ExportColumn, type SankeyGraphData } from "@cc-session/dashboard-ui";
import type { ContextEvent, EventGroup, KindSummary, SessionRef } from "../../api";

export const KIND_ACCENT: Record<ContextEvent["kind"], Accent> = {
  auto: "blue",
  user: "green",
  claude: "violet",
  hook: "amber",
  sub: "red",
};

// Mirrors cc_session_explorer.viz.htmlshell.assign_colors' dark-mode hex pairs, so the
// inline Sankey embed and the standalone downloadable page always agree on colors.
export const SANKEY_FIXED: Record<string, string> = {
  root: "#898781",
  ok: "#0ca30c",
  error: "#d03b3b",
  cost: "#3987e5",
  input: "#3987e5",
  output: "#199e70",
  cache_read: "#9085e9",
  cache_write_5m: "#d95926",
  cache_write_1h: "#c98500",
  main: "#3987e5",
  sidechain: "#d95926",
};
export const SANKEY_SLOTS = ["#3987e5", "#199e70", "#c98500", "#008300", "#9085e9", "#e66767", "#d55181", "#d95926"];

export function assignSankeyColors(graphs: SankeyGraphData[]): Record<string, string> {
  const colors: Record<string, string> = {};
  let cursor = 0;
  for (const graph of graphs) {
    for (const node of graph.nodes) {
      if (node.group in colors) continue;
      colors[node.group] = SANKEY_FIXED[node.group] ?? SANKEY_SLOTS[cursor++ % SANKEY_SLOTS.length];
    }
  }
  return colors;
}

export function kindPills(kinds: KindSummary[]) {
  return (
    <span style={{ display: "inline-flex", gap: 6, flexWrap: "wrap" }}>
      {kinds.map((k) => (
        <Pill key={k.kind} accent={KIND_ACCENT[k.kind]} dot={false}>
          {k.kind} {fmtTok(k.tokens)}
        </Pill>
      ))}
    </span>
  );
}

export const fmtBytes = (n: number) =>
  n >= 1_048_576 ? `${(n / 1_048_576).toFixed(1)} MB` : `${(n / 1024).toFixed(0)} KB`;

export const fmtWhen = (iso: string) => iso.slice(0, 16).replace("T", " ");

export const matchesSession = (row: SessionRef, query: string): boolean =>
  [row.session_id, row.project].join(" ").toLowerCase().includes(query.toLowerCase());

export const sessionExportColumns: ExportColumn<SessionRef>[] = [
  { header: "session_id", value: (r) => r.session_id },
  { header: "project", value: (r) => r.project },
  { header: "size_bytes", value: (r) => r.size_bytes },
  { header: "last_modified", value: (r) => r.last_modified },
];

export const groupExportColumns: ExportColumn<EventGroup>[] = [
  { header: "kind", value: (g) => g.kind },
  { header: "label", value: (g) => g.label },
  { header: "events", value: (g) => g.count },
  { header: "tokens", value: (g) => g.tokens },
];
