export interface ExportColumn<Row> {
  header: string;
  value: (row: Row) => string | number | boolean | null | undefined;
}

const csvCell = (value: unknown): string => {
  const text = value === null || value === undefined ? "" : String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
};

/** Renders rows to CSV text using each column's raw (non-React) value. */
export function rowsToCSV<Row>(rows: readonly Row[], columns: readonly ExportColumn<Row>[]): string {
  const header = columns.map((c) => csvCell(c.header)).join(",");
  const body = rows.map((row) => columns.map((c) => csvCell(c.value(row))).join(","));
  return [header, ...body].join("\r\n");
}

function triggerDownload(filename: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** Downloads `rows` as a CSV file named `${filename}.csv`. */
export function downloadCSV<Row>(
  filename: string,
  rows: readonly Row[],
  columns: readonly ExportColumn<Row>[],
): void {
  triggerDownload(`${filename}.csv`, new Blob([rowsToCSV(rows, columns)], { type: "text/csv;charset=utf-8" }));
}

/** Downloads any JSON-serializable value as `${filename}.json`. */
export function downloadJSON(filename: string, value: unknown): void {
  triggerDownload(`${filename}.json`, new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }));
}
