import type { HTMLAttributes, ReactNode } from "react";

export interface RootProps extends HTMLAttributes<HTMLDivElement> {
  /** Paint the app background token and fill the viewport. Default true. */
  fillBackground?: boolean;
  children: ReactNode;
}

/**
 * Theme root. Establishes the base font, text color, and (optionally) the app
 * background. Every design built with this system should wrap its tree in `Root`
 * — the design tokens live on `:root`, but this applies the typography and
 * surface that the components assume.
 */
export function Root({ fillBackground = true, className, style, children, ...rest }: RootProps) {
  return (
    <div
      className={["ju-root", className].filter(Boolean).join(" ")}
      style={{
        ...(fillBackground ? { background: "var(--bg)", minHeight: "100vh" } : {}),
        ...style,
      }}
      {...rest}
    >
      {children}
    </div>
  );
}
