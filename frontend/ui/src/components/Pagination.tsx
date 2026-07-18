import { Button } from "./Button";

export interface PaginationProps {
  /** 0-based current page. */
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
}

/** "X–Y of Z" plus Prev/Next, for any table whose full row set is already loaded
 *  client-side and just needs paging through rather than fetching more. */
export function Pagination({ page, pageSize, total, onPageChange }: PaginationProps) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const start = total === 0 ? 0 : page * pageSize + 1;
  const end = Math.min(total, (page + 1) * pageSize);
  return (
    <div className="ju-pagination">
      <span className="ju-muted">
        {start}–{end} of {total}
      </span>
      <div className="ju-pagination-controls">
        <Button variant="ghost" disabled={page <= 0} onClick={() => onPageChange(page - 1)}>
          ← Prev
        </Button>
        <span className="ju-muted ju-pagination-page">
          page {page + 1} of {pageCount}
        </span>
        <Button variant="ghost" disabled={page >= pageCount - 1} onClick={() => onPageChange(page + 1)}>
          Next →
        </Button>
      </div>
    </div>
  );
}
