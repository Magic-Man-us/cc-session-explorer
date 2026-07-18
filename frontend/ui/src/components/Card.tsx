import type { HTMLAttributes, ReactNode } from "react";

export interface CardProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  /** Optional heading shown in the card title row. */
  title?: ReactNode;
  /** Optional muted text aligned to the right of the title. */
  meta?: ReactNode;
  children: ReactNode;
}

/** Panel surface with a border and optional title/meta header row. */
export function Card({ title, meta, className, children, ...rest }: CardProps) {
  return (
    <div className={["ju-card", className].filter(Boolean).join(" ")} {...rest}>
      {(title != null || meta != null) && (
        <div className="ju-title">
          <h2>{title}</h2>
          {meta != null && <span>{meta}</span>}
        </div>
      )}
      {children}
    </div>
  );
}
