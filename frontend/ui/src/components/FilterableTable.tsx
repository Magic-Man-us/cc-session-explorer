import { useState, type ReactNode } from "react";
import { Card } from "./Card";
import { DataTable, type Column } from "./DataTable";
import { ExportButtons } from "./ExportButtons";
import { Input } from "./Input";
import { Pagination } from "./Pagination";
import type { ExportColumn } from "../export";

export interface FilterableTableProps<Row> {
  title: ReactNode;
  meta?: ReactNode;
  rows: Row[];
  columns: Column<Row>[];
  rowKey: (row: Row) => string;
  onRowClick?: (row: Row) => void;
  selectedKey?: string;
  expandedKey?: string;
  renderExpanded?: (row: Row) => ReactNode;
  query?: string;
  onQueryChange?: (query: string) => void;
  filterPlaceholder?: string;
  matches?: (row: Row, query: string) => boolean;
  exportColumns?: ExportColumn<Row>[];
  filename?: string;
  pageSize?: number;
  /** Controlled pagination — provide both to drive the page externally (e.g. to jump to the
   *  page containing a deep-linked row). Omit both to let FilterableTable own its own page state. */
  page?: number;
  onPageChange?: (page: number) => void;
  /** Extra content rendered inside the Card, between the header and the table — e.g. a
   *  SegmentedControl or a summary line that isn't itself a column. */
  children?: ReactNode;
}

/** Generic filter Input -> Card (title/meta/ExportButtons) -> DataTable -> Pagination shell,
 *  wrapping the library's own components. Filtering, export, and pagination are each opt-in
 *  by providing their respective props; omit them to render that part of the shell out. */
export function FilterableTable<Row>({
  title,
  meta,
  rows,
  columns,
  rowKey,
  onRowClick,
  selectedKey,
  expandedKey,
  renderExpanded,
  query,
  onQueryChange,
  filterPlaceholder,
  matches,
  exportColumns,
  filename,
  pageSize,
  page: controlledPage,
  onPageChange: setControlledPage,
  children,
}: FilterableTableProps<Row>) {
  const [internalPage, setInternalPage] = useState(0);
  const pageControlled = controlledPage !== undefined && setControlledPage !== undefined;
  const page = pageControlled ? controlledPage : internalPage;
  const setPage = pageControlled ? setControlledPage : setInternalPage;

  const filterable = query !== undefined && onQueryChange !== undefined && filterPlaceholder !== undefined && matches !== undefined;
  const filtered = filterable ? rows.filter((r) => matches(r, query)) : rows;
  const pageRows = pageSize === undefined ? filtered : filtered.slice(page * pageSize, (page + 1) * pageSize);

  const cardMeta =
    exportColumns !== undefined && filename !== undefined ? (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 12 }}>
        <span>{meta}</span>
        <ExportButtons rows={filtered} columns={exportColumns} filename={filename} />
      </span>
    ) : (
      meta
    );

  const card = (
    <Card title={title} {...(cardMeta != null ? { meta: cardMeta } : {})}>
      {children}
      <DataTable
        columns={columns}
        rows={pageRows}
        rowKey={rowKey}
        onRowClick={onRowClick}
        selectedKey={selectedKey}
        expandedKey={expandedKey}
        renderExpanded={renderExpanded}
      />
      {pageSize !== undefined && (
        <Pagination page={page} pageSize={pageSize} total={filtered.length} onPageChange={setPage} />
      )}
    </Card>
  );

  if (!filterable) return card;

  return (
    <div style={{ display: "grid", gap: 12 }}>
      <Input
        placeholder={filterPlaceholder}
        value={query}
        onChange={(e) => {
          onQueryChange(e.target.value);
          setPage(0);
        }}
      />
      {card}
    </div>
  );
}
