import type { ReactNode } from "react";

export interface KpiCardProps {
  /** Small muted label above the value (e.g. "corrected tokens"). */
  label: ReactNode;
  /** The headline figure — a pre-formatted string or any node. */
  value: ReactNode;
  /** Muted supporting text below the value. */
  hint?: ReactNode;
  /** Makes the tile clickable — e.g. jump to a related, filtered view. */
  onClick?: () => void;
}

/** Single big-number metric tile used in the KPI row. */
export function KpiCard({ label, value, hint, onClick }: KpiCardProps) {
  const clickable = onClick !== undefined;
  return (
    <div
      className={["ju-card", "ju-kpi", clickable && "ju-clickable"].filter(Boolean).join(" ")}
      onClick={onClick}
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
    >
      <div className="ju-kpi-label">{label}</div>
      <div className="ju-kpi-value">{value}</div>
      {hint != null && <div className="ju-kpi-hint">{hint}</div>}
    </div>
  );
}
