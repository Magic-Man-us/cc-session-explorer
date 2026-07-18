export interface NavItem<T extends string = string> {
  value: T;
  label: string;
}

/** A non-selectable section label between groups of nav items. */
export interface NavHeading {
  heading: string;
}

export interface SidebarProps<T extends string = string> {
  /** Product name shown at the top. */
  brand: string;
  /** Muted subtitle under the brand. */
  subtitle?: string;
  items: ReadonlyArray<NavItem<T> | NavHeading>;
  active: T;
  onSelect: (value: T) => void;
}

/** Left navigation rail: brand, subtitle, and a vertical list of view buttons,
 *  optionally broken into sections by `NavHeading` entries. */
export function Sidebar<T extends string = string>({
  brand,
  subtitle,
  items,
  active,
  onSelect,
}: SidebarProps<T>) {
  return (
    <aside className="ju-side">
      <div className="ju-brand">{brand}</div>
      {subtitle && <div className="ju-sub">{subtitle}</div>}
      <div className="ju-nav">
        {items.map((item) =>
          "heading" in item ? (
            <div key={`h-${item.heading}`} className="ju-nav-heading">
              {item.heading}
            </div>
          ) : (
            <button
              key={item.value}
              type="button"
              className={item.value === active ? "ju-active" : undefined}
              onClick={() => onSelect(item.value)}
            >
              {item.label}
            </button>
          ),
        )}
      </div>
    </aside>
  );
}
