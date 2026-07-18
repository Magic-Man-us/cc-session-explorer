import type { ButtonHTMLAttributes, ReactNode } from "react";

export interface LinkButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "type"> {
  children: ReactNode;
}

/** Inline text styled as a link — for cross-navigating from a table cell (e.g. a model,
 *  project, or session id) without the visual weight of a full Button. */
export function LinkButton({ className, children, ...rest }: LinkButtonProps) {
  return (
    <button type="button" className={["ju-link", className].filter(Boolean).join(" ")} {...rest}>
      {children}
    </button>
  );
}
