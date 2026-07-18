import { useMemo, useState } from "react";

export interface SankeyNode {
  id: string;
  label: string;
  tier: number;
  group: string;
}

export interface SankeyLink {
  source: string;
  target: string;
  value: number;
  group: string;
}

export interface SankeyGraphData {
  title: string;
  unit: string;
  nodes: SankeyNode[];
  links: SankeyLink[];
}

export interface SankeyChartProps {
  graph: SankeyGraphData;
  /** group -> CSS color (hex or var()). Ungrouped/unknown groups fall back to `--muted`. */
  colors: Record<string, string>;
  width?: number;
  fmt?: (n: number) => string;
}

const NODE_W = 15;
const GAP = 12;
const PADX = 8;
const PADY = 14;
const ROW = 46;

interface PosEntry {
  x: number;
  y: number;
  h: number;
  node: SankeyNode;
  so: number;
  ti: number;
  val: number;
}

interface LaidOutLink extends SankeyLink {
  sy: number;
  ty: number;
  th: number;
}

interface Layout {
  width: number;
  height: number;
  pos: Record<string, PosEntry>;
  links: LaidOutLink[];
}

/** Ribbon-width-proportional tier layout: nodes sized by max(inflow, outflow), positioned
 *  left-to-right by tier, top-aligned within each tier by descending value. Mirrors
 *  cc_session_explorer.viz.sankey's standalone-page JS 1:1 so the SPA embed and the
 *  downloadable page always agree. */
function layout(graph: SankeyGraphData, width: number): Layout {
  const tiers = [...new Set(graph.nodes.map((n) => n.tier))].sort((a, b) => a - b);
  const maxTier = tiers[tiers.length - 1] ?? 0;
  const outSum: Record<string, number> = {};
  const inSum: Record<string, number> = {};
  graph.links.forEach((l) => {
    outSum[l.source] = (outSum[l.source] || 0) + l.value;
    inSum[l.target] = (inSum[l.target] || 0) + l.value;
  });
  const nodeVal = (id: string) => Math.max(outSum[id] || 0, inSum[id] || 0);
  const byTier: Record<number, SankeyNode[]> = {};
  tiers.forEach((ti) => {
    byTier[ti] = graph.nodes.filter((n) => n.tier === ti);
  });
  const maxCount = tiers.length ? Math.max(...tiers.map((ti) => byTier[ti].length)) : 0;
  const height = Math.max(240, maxCount * ROW);

  let unit = Infinity;
  tiers.forEach((ti) => {
    const sum = byTier[ti].reduce((s, n) => s + nodeVal(n.id), 0) || 1;
    const avail = height - 2 * PADY - (byTier[ti].length - 1) * GAP;
    unit = Math.min(unit, avail / sum);
  });

  const innerW = width - 2 * PADX - NODE_W;
  const pos: Record<string, PosEntry> = {};
  tiers.forEach((ti) => {
    const x = PADX + (maxTier ? (ti / maxTier) * innerW : 0);
    const col = byTier[ti].slice().sort((a, b) => nodeVal(b.id) - nodeVal(a.id));
    const colH = col.reduce((s, n) => s + Math.max(nodeVal(n.id) * unit, 2), 0) + (col.length - 1) * GAP;
    let y = (height - colH) / 2;
    col.forEach((n) => {
      const h = Math.max(nodeVal(n.id) * unit, 2);
      pos[n.id] = { x, y, h, node: n, so: 0, ti: 0, val: nodeVal(n.id) };
      y += h + GAP;
    });
  });

  const links: LaidOutLink[] = graph.links
    .map((l) => ({ ...l, sy: 0, ty: 0, th: 0 }))
    .sort((a, b) => pos[a.source].y - pos[b.source].y || pos[a.target].y - pos[b.target].y);
  links.forEach((l) => {
    const s = pos[l.source];
    const t = pos[l.target];
    const th = l.value * unit;
    l.sy = s.y + s.so + th / 2;
    s.so += th;
    l.ty = t.y + t.ti + th / 2;
    t.ti += th;
    l.th = th;
  });

  return { width, height, pos, links };
}

function ribbonPath(l: LaidOutLink, pos: Record<string, PosEntry>): string {
  const x0 = pos[l.source].x + NODE_W;
  const x1 = pos[l.target].x;
  const xm = (x0 + x1) / 2;
  const h = l.th / 2;
  return (
    `M${x0},${l.sy - h} C${xm},${l.sy - h} ${xm},${l.ty - h} ${x1},${l.ty - h}` +
    ` L${x1},${l.ty + h} C${xm},${l.ty + h} ${xm},${l.sy + h} ${x0},${l.sy + h} Z`
  );
}

const defaultFmt = (n: number) =>
  Number.isInteger(n) ? n.toLocaleString() : n.toLocaleString(undefined, { maximumFractionDigits: 1 });

/** One flow graph — nodes + conserving ribbons, colored by group, tiered left to right.
 *  Hovering a node dims every ribbon except the ones touching it. */
export function SankeyChart({ graph, colors, width = 900, fmt = defaultFmt }: SankeyChartProps) {
  const [hoverNode, setHoverNode] = useState<string | null>(null);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; text: string } | null>(null);
  const L = useMemo(() => layout(graph, width), [graph, width]);
  const color = (group: string) => colors[group] ?? "var(--muted)";

  return (
    <div className="ju-sankey-card">
      <div className="ju-sankey-head">
        <h3>{graph.title}</h3>
        <span className="ju-muted">by {graph.unit}</span>
      </div>
      <svg
        viewBox={`0 0 ${L.width} ${L.height}`}
        preserveAspectRatio="xMinYMin meet"
        className={hoverNode ? "ju-sankey-svg ju-sankey-dim" : "ju-sankey-svg"}
      >
        <g>
          {L.links.map((l, i) => (
            <path
              key={i}
              d={ribbonPath(l, L.pos)}
              fill={color(l.group)}
              className={
                hoverNode && (l.source === hoverNode || l.target === hoverNode)
                  ? "ju-sankey-link ju-sankey-hot"
                  : "ju-sankey-link"
              }
              onMouseMove={(e) =>
                setTooltip({
                  x: e.clientX,
                  y: e.clientY,
                  text: `${L.pos[l.source].node.label} → ${L.pos[l.target].node.label}: ${fmt(l.value)} ${graph.unit}`,
                })
              }
              onMouseLeave={() => setTooltip(null)}
            />
          ))}
        </g>
        {Object.values(L.pos).map((pn) => {
          const right = pn.x < L.width / 2;
          return (
            <g
              key={pn.node.id}
              className="ju-sankey-node"
              onMouseEnter={() => setHoverNode(pn.node.id)}
              onMouseLeave={() => setHoverNode(null)}
            >
              <rect x={pn.x} y={pn.y} width={NODE_W} height={pn.h} rx={3} fill={color(pn.node.group)} />
              <text x={right ? pn.x + NODE_W + 7 : pn.x - 7} y={pn.y + pn.h / 2} textAnchor={right ? "start" : "end"}>
                {pn.node.label}{" "}
                <tspan className="ju-sankey-val">{fmt(pn.val)}</tspan>
              </text>
            </g>
          );
        })}
      </svg>
      {tooltip && (
        <div className="ju-sankey-tooltip" style={{ left: tooltip.x + 12, top: tooltip.y + 12 }}>
          {tooltip.text}
        </div>
      )}
    </div>
  );
}
