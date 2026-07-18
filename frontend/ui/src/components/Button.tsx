import type { ButtonHTMLAttributes, ReactNode } from "react";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** `solid` uses the panel surface; `ghost` is transparent until hovered. */
  variant?: "solid" | "ghost";
  children: ReactNode;
}

export function Button({ variant = "solid", className, children, ...rest }: ButtonProps) {
  const classes = ["ju-button", variant === "ghost" && "ju-button--ghost", className]
    .filter(Boolean)
    .join(" ");
  return (
    <button className={classes} {...rest}>
      {children}
    </button>
  );
}
