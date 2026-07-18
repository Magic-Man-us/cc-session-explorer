import type { InputHTMLAttributes } from "react";

export type InputProps = InputHTMLAttributes<HTMLInputElement>;

/** Full-width text/search/datetime input on the panel-2 surface. */
export function Input({ className, ...rest }: InputProps) {
  return <input className={["ju-input", className].filter(Boolean).join(" ")} {...rest} />;
}
