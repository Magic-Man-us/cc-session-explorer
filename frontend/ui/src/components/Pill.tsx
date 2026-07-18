import type { ReactNode } from "react";
import { type Accent, accentVar } from "../types";

export interface PillProps {
  children: ReactNode;
  /** Accent color for the text and leading dot. Defaults to green ("live"). */
  accent?: Accent;
  /** Show the leading status dot. */
  dot?: boolean;
}

/** Rounded status chip, e.g. a live indicator. */
export function Pill({ children, accent = "green", dot = true }: PillProps) {
  const color = accentVar(accent);
  return (
    <span className="ju-pill" style={{ color }}>
      {dot && <i className="ju-dot" style={{ background: color }} />}
      {children}
    </span>
  );
}
