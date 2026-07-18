import { Fragment, type ReactNode } from "react";

export interface Column<Row> {
  /** Stable column id. */
  key: string;
  header: ReactNode;
  /** Right-align + tabular-nums, for numeric columns. */
  numeric?: boolean;
  /** Cell renderer. Return any node; falls back to nothing if omitted. */
  render: (row: Row) => ReactNode;
}

export interface DataTableProps<Row> {
  columns: ReadonlyArray<Column<Row>>;
  rows: ReadonlyArray<Row>;
  /** Stable key per row. */
  rowKey: (row: Row) => string;
  /** Makes rows clickable/hoverable and fires with the row. */
  onRowClick?: (row: Row) => void;
  /** Key of the currently selected row, if any. */
  selectedKey?: string;
  /** Render extra content in a full-width row beneath the expanded row. */
  renderExpanded?: (row: Row) => ReactNode;
  /** Key of the row whose expanded content is shown. */
  expandedKey?: string;
  /** Shown in place of the body when `rows` is empty — e.g. a filter matched nothing. */
  emptyMessage?: ReactNode;
}

/** Bordered table with muted headers, numeric alignment, and optional row selection. */
export function DataTable<Row>({
  columns,
  rows,
  rowKey,
  onRowClick,
  selectedKey,
  renderExpanded,
  expandedKey,
  emptyMessage = "No results",
}: DataTableProps<Row>) {
  return (
    <table className="ju-table">
      <thead>
        <tr>
          {columns.map((column) => (
            <th key={column.key} className={column.numeric ? "ju-num" : undefined}>
              {column.header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 && (
          <tr>
            <td colSpan={columns.length} className="ju-table-empty">
              {emptyMessage}
            </td>
          </tr>
        )}
        {rows.map((row) => {
          const key = rowKey(row);
          const classes = [onRowClick && "ju-clickable", key === selectedKey && "ju-selected"]
            .filter(Boolean)
            .join(" ");
          const expanded = renderExpanded && key === expandedKey;
          return (
            <Fragment key={key}>
              <tr
                className={classes || undefined}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
              >
                {columns.map((column) => (
                  <td key={column.key} className={column.numeric ? "ju-num" : undefined}>
                    {column.render(row)}
                  </td>
                ))}
              </tr>
              {expanded && (
                <tr className="ju-expanded-row">
                  <td colSpan={columns.length}>{renderExpanded(row)}</td>
                </tr>
              )}
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}
