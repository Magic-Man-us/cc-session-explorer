import { useMemo, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

type Json = string | number | boolean | null | Json[] | { [key: string]: Json };

const MAX_ITEMS = 100;

// Past this length a quoted, single-line primitive stops being readable — render it as
// a block instead. Below it, JSON.stringify's quotes/escapes read fine inline.
const BLOCK_STRING_THRESHOLD = 200;

/** A string worth its own preformatted block rather than an inline `JSON.stringify`
 *  primitive: multi-line content escapes to a literal `\n` run-on otherwise, and long
 *  single-line content (a path, a diff, a stack frame) reads better with room to breathe. */
function isBlockString(value: string): boolean {
  return value.includes("\n") || value.length > BLOCK_STRING_THRESHOLD;
}

function Primitive({ value }: { value: string | number | boolean | null }) {
  if (value === null) return <span className="ju-json-null">null</span>;
  if (typeof value === "boolean") return <span className="ju-json-bool">{String(value)}</span>;
  if (typeof value === "number") return <span className="ju-json-num">{value}</span>;
  return <span className="ju-json-str">{JSON.stringify(value)}</span>;
}

function entriesOf(value: Json[] | { [key: string]: Json }): [string, Json][] {
  return Array.isArray(value)
    ? value.map((item, index): [string, Json] => [String(index), item])
    : Object.entries(value);
}

/** One JSON node: a leaf renders its value inline; a container is a collapsible
 * row that expands to its own entries, indented one level deeper. */
function JsonNode({
  label,
  value,
  depth,
  defaultExpandDepth,
}: {
  label?: string;
  value: Json;
  depth: number;
  defaultExpandDepth: number;
}) {
  const [open, setOpen] = useState(depth < defaultExpandDepth);
  const [showAll, setShowAll] = useState(false);
  const indent = { paddingLeft: depth * 14 };

  if (value === null || typeof value !== "object") {
    if (typeof value === "string" && isBlockString(value)) {
      return (
        <div className="ju-json-row" style={indent}>
          {label !== undefined && <div className="ju-json-key">{label}:</div>}
          <pre className="ju-json-block">{value}</pre>
        </div>
      );
    }
    return (
      <div className="ju-json-row" style={indent}>
        {label !== undefined && <span className="ju-json-key">{label}: </span>}
        <Primitive value={value} />
      </div>
    );
  }

  const isArr = Array.isArray(value);
  const entries = entriesOf(value);
  const openBrace = isArr ? "[" : "{";
  const closeBrace = isArr ? "]" : "}";

  if (entries.length === 0) {
    return (
      <div className="ju-json-row" style={indent}>
        {label !== undefined && <span className="ju-json-key">{label}: </span>}
        <span className="ju-json-punct">
          {openBrace}
          {closeBrace}
        </span>
      </div>
    );
  }

  const shown = showAll ? entries : entries.slice(0, MAX_ITEMS);
  const hiddenCount = entries.length - shown.length;

  return (
    <div>
      <div
        className="ju-json-row ju-json-toggle-row"
        style={indent}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="ju-json-toggle">{open ? "▾" : "▸"}</span>
        {label !== undefined && <span className="ju-json-key">{label}: </span>}
        <span className="ju-json-punct">{openBrace}</span>
        {!open && (
          <span className="ju-muted">
            {" "}
            {entries.length} {isArr ? "items" : "keys"}{" "}
          </span>
        )}
        {!open && <span className="ju-json-punct">{closeBrace}</span>}
      </div>
      {open && (
        <>
          {shown.map(([key, item]) => (
            <JsonNode
              key={key}
              label={isArr ? undefined : key}
              value={item}
              depth={depth + 1}
              defaultExpandDepth={defaultExpandDepth}
            />
          ))}
          {hiddenCount > 0 && (
            <div className="ju-json-row" style={{ paddingLeft: (depth + 1) * 14 }}>
              <button
                className="ju-tl-more"
                onClick={(e) => {
                  e.stopPropagation();
                  setShowAll(true);
                }}
              >
                … {hiddenCount} more
              </button>
            </div>
          )}
          <div className="ju-json-row" style={indent}>
            <span className="ju-json-punct">{closeBrace}</span>
          </div>
        </>
      )}
    </div>
  );
}

export interface JsonViewProps {
  value: unknown;
  /** How many levels start expanded; deeper nodes start collapsed. Default 1. */
  defaultExpandDepth?: number;
}

/** A syntax-highlighted, collapsible tree for an already-parsed JSON value. */
export function JsonView({ value, defaultExpandDepth = 1 }: JsonViewProps) {
  return (
    <div className="ju-json ju-mono">
      <JsonNode value={value as Json} depth={0} defaultExpandDepth={defaultExpandDepth} />
    </div>
  );
}

interface JsonSpan {
  start: number;
  end: number;
  value: Json[] | { [key: string]: Json };
}

// A blob past this size isn't worth bracket-scanning for an embedded span — render it
// as plain text rather than risk the O(n^2) scan on something pathological.
const MAX_SCAN_CHARS = 50_000;

/** The largest balanced `{...}`/`[...]` span in `text` that parses as JSON — for content
 * that embeds a JSON blob inside otherwise-plain text (e.g. a `<result>{...}</result>`
 * tag in a tool notification). String contents are tracked so a brace inside a JSON
 * string value never miscounts the nesting depth. */
function findLargestJsonSpan(text: string): JsonSpan | null {
  if (text.length > MAX_SCAN_CHARS) return null;
  let best: JsonSpan | null = null;
  for (let i = 0; i < text.length; i++) {
    const open = text[i];
    if (open !== "{" && open !== "[") continue;
    const close = open === "{" ? "}" : "]";
    let depth = 0;
    let inString = false;
    let escape = false;
    for (let j = i; j < text.length; j++) {
      const c = text[j];
      if (inString) {
        if (escape) escape = false;
        else if (c === "\\") escape = true;
        else if (c === '"') inString = false;
        continue;
      }
      if (c === '"') {
        inString = true;
      } else if (c === open) {
        depth++;
      } else if (c === close) {
        depth--;
        if (depth === 0) {
          const candidate = text.slice(i, j + 1);
          try {
            const value: unknown = JSON.parse(candidate);
            if (
              value !== null &&
              typeof value === "object" &&
              (!best || candidate.length > best.end - best.start)
            ) {
              best = { start: i, end: j + 1, value: value as Json[] | { [key: string]: Json } };
            }
          } catch {
            // not valid JSON at this span — keep scanning from the next open bracket
          }
          break;
        }
      }
    }
  }
  return best;
}

/** A non-mono chunk is prose (chat text, thinking) — render it as markdown (GFM: tables,
 *  strikethrough, task lists) rather than a flat paragraph, so bold/lists/code/links
 *  actually format instead of showing raw `**`/`` ` ``/`-` syntax. */
function MarkdownText({ text }: { text: string }) {
  return (
    <div className="ju-tl-md">
      <Markdown remarkPlugins={[remarkGfm]}>{text}</Markdown>
    </div>
  );
}

function renderPlain(chunk: string, mono: boolean) {
  return mono ? <pre className="ju-tl-text ju-mono">{chunk}</pre> : <MarkdownText text={chunk} />;
}

export interface JsonOrTextProps {
  text: string;
  /** `true` (default) renders the surrounding plain-text portions as raw preformatted text
   * (for code/JSON-ish content); `false` renders them as markdown (for chat prose). Match
   * whatever the caller would otherwise have used for this content. */
  mono?: boolean;
  defaultExpandDepth?: number;
}

/** Renders `text` as a JsonView when it — or the largest JSON-shaped span within it —
 * parses as an object/array; the surrounding text (if any) renders plainly around it.
 * Falls back to plain text entirely when nothing inside parses. */
export function JsonOrText({ text, mono = true, defaultExpandDepth = 1 }: JsonOrTextProps) {
  const span = useMemo(() => {
    const trimmed = text.trim();
    if (!trimmed) return null;
    if (trimmed[0] === "{" || trimmed[0] === "[") {
      try {
        const value: unknown = JSON.parse(trimmed);
        if (value !== null && typeof value === "object") {
          const start = text.indexOf(trimmed);
          return { start, end: start + trimmed.length, value } as JsonSpan;
        }
      } catch {
        // fall through to the embedded-span scan below
      }
    }
    return findLargestJsonSpan(text);
  }, [text]);

  if (span === null) {
    return renderPlain(text, mono);
  }

  const before = text.slice(0, span.start);
  const after = text.slice(span.end);
  return (
    <>
      {before && renderPlain(before, mono)}
      <JsonView value={span.value} defaultExpandDepth={defaultExpandDepth} />
      {after && renderPlain(after, mono)}
    </>
  );
}
