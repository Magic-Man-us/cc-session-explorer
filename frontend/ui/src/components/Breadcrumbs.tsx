export interface Crumb {
  label: string;
  /** Omit on the last crumb — the current page renders as plain text, not a link. */
  onClick?: () => void;
}

export interface BreadcrumbsProps {
  crumbs: ReadonlyArray<Crumb>;
}

/** A clickable trail showing where the current view sits — lens › view › selected item. */
export function Breadcrumbs({ crumbs }: BreadcrumbsProps) {
  return (
    <nav className="ju-breadcrumbs" aria-label="Breadcrumb">
      {crumbs.map((crumb, index) => (
        <span key={index} className="ju-breadcrumbs-item">
          {index > 0 && <span className="ju-breadcrumbs-sep">›</span>}
          {crumb.onClick ? (
            <button type="button" className="ju-link" onClick={crumb.onClick}>
              {crumb.label}
            </button>
          ) : (
            <span className="ju-muted">{crumb.label}</span>
          )}
        </span>
      ))}
    </nav>
  );
}
