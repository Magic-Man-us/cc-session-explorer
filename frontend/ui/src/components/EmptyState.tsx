import type { ReactNode } from "react";

export interface EmptyStateProps {
  children: ReactNode;
}

/** Dashed placeholder box for empty or error states. */
export function EmptyState({ children }: EmptyStateProps) {
  return <div className="ju-empty">{children}</div>;
}
