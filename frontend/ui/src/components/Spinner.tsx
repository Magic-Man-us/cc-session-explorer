export interface SpinnerProps {
  /** Diameter in px. */
  size?: number;
}

/** A rotating ring — the one loading indicator in the design system. */
export function Spinner({ size = 20 }: SpinnerProps) {
  return (
    <span
      className="ju-spinner"
      style={{ width: size, height: size }}
      role="status"
      aria-label="Loading"
    />
  );
}
