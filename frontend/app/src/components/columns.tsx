import type { ReactNode } from "react";
import { LinkButton, fmtInt, fmtTok, money, type Column } from "@cc-session/dashboard-ui";

/** Session id as a LinkButton (id.slice(0, 12)), optionally with content rendered below it
 *  (e.g. a timestamp or a project link) via `extra`. Always stops propagation so it's safe to
 *  use inside a table whose rows are also clickable (e.g. to expand). */
export function sessionLinkColumn<Row>(opts: {
  idOf: (r: Row) => string;
  onClick: (r: Row) => void;
  mono?: boolean;
  extra?: (r: Row) => ReactNode;
}): Column<Row> {
  const { idOf, onClick, mono, extra } = opts;
  return {
    key: "session",
    header: "session",
    render: (r) => (
      <>
        <LinkButton
          className={mono !== false ? "ju-mono" : undefined}
          onClick={(e) => {
            e.stopPropagation();
            onClick(r);
          }}
        >
          {idOf(r).slice(0, 12)}
        </LinkButton>
        {extra && extra(r)}
      </>
    ),
  };
}

/** Project name as a muted LinkButton, or nothing if there's no project. */
export function projectLinkColumn<Row>(opts: {
  projectOf: (r: Row) => string | null | undefined;
  onClick: (project: string) => void;
}): Column<Row> {
  const { projectOf, onClick } = opts;
  return {
    key: "project",
    header: "project",
    render: (r) => {
      const project = projectOf(r);
      return project ? (
        <LinkButton
          className="ju-muted ju-clip"
          onClick={(e) => {
            e.stopPropagation();
            onClick(project);
          }}
        >
          {project}
        </LinkButton>
      ) : null;
    },
  };
}

/** Model name as a LinkButton, or nothing if there's no model. */
export function modelLinkColumn<Row>(opts: {
  modelOf: (r: Row) => string | null | undefined;
  onClick: (model: string) => void;
}): Column<Row> {
  const { modelOf, onClick } = opts;
  return {
    key: "model",
    header: "model",
    render: (r) => {
      const model = modelOf(r);
      return model ? (
        <LinkButton
          onClick={(e) => {
            e.stopPropagation();
            onClick(model);
          }}
        >
          {model}
        </LinkButton>
      ) : null;
    },
  };
}

export function tokensColumn<Row>(tokensOf: (r: Row) => number, opts?: { header?: string }): Column<Row> {
  return {
    key: "tokens",
    header: opts?.header ?? "tokens",
    numeric: true,
    render: (r) => fmtTok(tokensOf(r)),
  };
}

export function costColumn<Row>(costOf: (r: Row) => number, opts?: { header?: string }): Column<Row> {
  return {
    key: "cost",
    header: opts?.header ?? "cost",
    numeric: true,
    render: (r) => money(costOf(r)),
  };
}

export function turnsColumn<Row>(turnsOf: (r: Row) => number): Column<Row> {
  return {
    key: "turns",
    header: "turns",
    numeric: true,
    render: (r) => fmtInt(turnsOf(r)),
  };
}
