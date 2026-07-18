import { Button } from "./Button";
import { downloadCSV, downloadJSON, type ExportColumn } from "../export";

export interface ExportButtonsProps<Row> {
  /** Rows to export — the same data the table renders, not its React output. */
  rows: readonly Row[];
  /** Raw-value columns for the CSV; the JSON export always serializes `rows` in full. */
  columns: readonly ExportColumn<Row>[];
  /** Base filename, without extension. */
  filename: string;
}

/** CSV + JSON download buttons for a table's rows. Disabled when there's nothing to export. */
export function ExportButtons<Row>({ rows, columns, filename }: ExportButtonsProps<Row>) {
  const empty = rows.length === 0;
  return (
    <span style={{ display: "inline-flex", gap: 6 }}>
      <Button variant="ghost" disabled={empty} onClick={() => downloadCSV(filename, rows, columns)}>
        CSV
      </Button>
      <Button variant="ghost" disabled={empty} onClick={() => downloadJSON(filename, rows)}>
        JSON
      </Button>
    </span>
  );
}
