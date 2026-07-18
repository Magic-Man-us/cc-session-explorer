import { Spinner } from "./Spinner";

export interface LoadingStateProps {
  children?: string;
}

/** The dashed placeholder box a view shows while its data is in flight — same shape as
 *  `EmptyState`, but with a spinner, so "still loading" never reads as "genuinely empty". */
export function LoadingState({ children = "Loading…" }: LoadingStateProps) {
  return (
    <div className="ju-empty ju-loading">
      <Spinner />
      <span>{children}</span>
    </div>
  );
}
