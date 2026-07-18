"""Session Sankey: typed flow graphs over a parsed cc_session_core session, rendered to a
single self-contained HTML page (inline SVG, no external deps, theme-aware).

Three conserving flows are built from the typed views in ``cc_session_core``:

* **tool activity** (calls)   Session → tool category → tool → outcome
* **token flow**    (tokens)  Total → attribution → model → token-kind
* **cost flow**     (USD)     the same, weighted by published-rate cost

Attribution ("where the tokens went") is per **API request** — the finest unit
usage actually records; tokens cannot be split below a request (the API doesn't
report per-message/per-tool token counts). Within that limit each request is
tagged by what spent it: main vs a sidechain, or an explicit agent/skill/mcp/
plugin attribution.

``build_page(session)`` returns the HTML string; the CLI writes it to a file.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Literal

from cc_session_core import ModelPrice, Session, cost_breakdown_for, price_for_usage
from cc_session_core import types as t
from cc_session_core.models import AssistantRecord, SnakeModel, Usage
from pydantic import TypeAdapter

from . import types as vt
from .htmlshell import StatTile, assign_colors, render_page, safe_json

FlowUnit = Literal["calls", "tokens", "USD"]
FlowWeight = Literal["tokens", "USD"]
_SUBTITLE = "Session breakdown — flows conserve; ribbon width is proportional to volume."


class SankeyNode(SnakeModel):
    id: vt.SankeyNodeId
    label: vt.SankeyLabel
    tier: vt.Tier
    group: vt.NodeGroup


class SankeyLink(SnakeModel):
    source: vt.SankeyNodeId
    target: vt.SankeyNodeId
    value: vt.FlowValue
    group: vt.NodeGroup


class SankeyGraph(SnakeModel):
    title: vt.SankeyTitle
    unit: FlowUnit
    nodes: list[SankeyNode] = []
    links: list[SankeyLink] = []


class SessionPage(SnakeModel):
    """Everything the HTML page renders: header stats and the flow graphs."""

    title: vt.SankeyTitle
    stats: list[StatTile] = []
    graphs: list[SankeyGraph] = []


# --------------------------------------------------------------------------- #
# tool taxonomy
# --------------------------------------------------------------------------- #
_TOOL_CATEGORY: dict[str, str] = {
    "Read": "File",
    "Edit": "File",
    "Write": "File",
    "NotebookEdit": "File",
    "Glob": "Search",
    "Grep": "Search",
    "ToolSearch": "Search",
    "Bash": "Shell",
    "BashOutput": "Shell",
    "KillShell": "Shell",
    "WebFetch": "Web",
    "WebSearch": "Web",
    "Task": "Agent",
    "Agent": "Agent",
    "TaskCreate": "Task",
    "TaskUpdate": "Task",
    "TaskGet": "Task",
    "TaskList": "Task",
    "TaskOutput": "Task",
    "TaskStop": "Task",
}

# Token kinds a request's usage is split into (key, display label).
_KINDS: tuple[tuple[str, str], ...] = (
    ("input", "Input"),
    ("output", "Output"),
    ("cache_read", "Cache read"),
    ("cache_write_5m", "Cache write 5m"),
    ("cache_write_1h", "Cache write 1h"),
)


def _category(name: t.ToolName) -> str:
    if name.startswith("mcp__"):
        return "MCP"
    return _TOOL_CATEGORY.get(name, "Other")


def _attribution(rec: AssistantRecord) -> tuple[str, str]:
    """(group key, label) for where a request's tokens are attributed — an explicit
    agent/skill/mcp/plugin tag when present, else sidechain vs main."""
    for prefix, value in (
        ("agent", rec.attribution_agent),
        ("skill", rec.attribution_skill),
        ("mcp", rec.attribution_mcp_server),
        ("plugin", rec.attribution_plugin),
    ):
        if value:
            return f"{prefix}:{value}", f"{prefix}: {value}"
    if rec.is_sidechain:
        return "sidechain", "sidechain"
    return "main", "main"


def _kind_tokens(usage: Usage) -> dict[str, float]:
    return {
        "input": usage.input_tokens,
        "output": usage.output_tokens,
        "cache_read": usage.cache_read_input_tokens,
        "cache_write_5m": usage.cache_creation.ephemeral_5m_input_tokens,
        "cache_write_1h": usage.cache_creation.ephemeral_1h_input_tokens,
    }


def _kind_cost(usage: Usage, price: ModelPrice | None) -> dict[str, float]:
    breakdown = cost_breakdown_for(usage, price)
    if breakdown is None:
        return {key: 0.0 for key, _ in _KINDS}
    return {
        "input": breakdown.input,
        "output": breakdown.output,
        "cache_read": breakdown.cache_read,
        "cache_write_5m": breakdown.cache_write_5m,
        "cache_write_1h": breakdown.cache_write_1h,
    }


# --------------------------------------------------------------------------- #
# graph builders
# --------------------------------------------------------------------------- #
def tool_activity_graph(session: Session) -> SankeyGraph:
    """Session → category → tool → outcome, weighted by number of calls."""
    cat_calls: Counter[str] = Counter()
    cat_tool: Counter[tuple[str, str]] = Counter()
    tool_outcome: Counter[tuple[str, str]] = Counter()
    for call in session.tool_calls():
        category = _category(call.name)
        outcome = "error" if call.is_error else "ok"
        cat_calls[category] += 1
        cat_tool[(category, call.name)] += 1
        tool_outcome[(call.name, outcome)] += 1

    nodes: dict[str, SankeyNode] = {
        "root": SankeyNode(id="root", label="Session", tier=0, group="root")
    }
    links: list[SankeyLink] = []
    for category, n in cat_calls.items():
        cid = f"cat:{category}"
        nodes[cid] = SankeyNode(id=cid, label=category, tier=1, group=category)
        links.append(SankeyLink(source="root", target=cid, value=n, group=category))
    for (category, name), n in cat_tool.items():
        tid = f"tool:{name}"
        nodes.setdefault(tid, SankeyNode(id=tid, label=name, tier=2, group=category))
        links.append(SankeyLink(source=f"cat:{category}", target=tid, value=n, group=category))
    for (name, outcome), n in tool_outcome.items():
        oid = f"outcome:{outcome}"
        nodes.setdefault(oid, SankeyNode(id=oid, label=outcome, tier=3, group=outcome))
        links.append(SankeyLink(source=f"tool:{name}", target=oid, value=n, group=outcome))

    return SankeyGraph(title="Tool activity", unit="calls", nodes=list(nodes.values()), links=links)


def token_graph(session: Session, *, weight: FlowWeight) -> SankeyGraph:
    """Total → attribution → model → token-kind, weighted by tokens or cost.

    Every node conserves (in-flow == out-flow), so a ribbon traced end to end
    accounts for exactly where each token — or dollar — was spent.
    """
    root_attr: defaultdict[str, float] = defaultdict(float)
    attr_model: defaultdict[tuple[str, str], float] = defaultdict(float)
    model_kind: defaultdict[tuple[str, str], float] = defaultdict(float)
    attr_label: dict[str, str] = {}

    for rec in session.assistant_requests():
        usage = rec.message.usage
        model = rec.message.model or "unknown"
        akey, alabel = _attribution(rec)
        attr_label[akey] = alabel
        amounts = (
            _kind_tokens(usage)
            if weight == "tokens"
            else _kind_cost(usage, price_for_usage(rec.message.model, usage))
        )
        if sum(amounts.values()) <= 0:
            continue
        for key, amount in amounts.items():
            if amount <= 0:
                continue
            root_attr[akey] += amount
            attr_model[(akey, model)] += amount
            model_kind[(model, key)] += amount

    nodes: dict[str, SankeyNode] = {
        "root": SankeyNode(id="root", label="Total", tier=0, group="root")
    }
    links: list[SankeyLink] = []
    kind_labels = dict(_KINDS)

    for akey, value in root_attr.items():
        nid = f"attr:{akey}"
        group = akey if akey in ("main", "sidechain") else akey.split(":", 1)[0]
        nodes[nid] = SankeyNode(id=nid, label=attr_label[akey], tier=1, group=group)
        links.append(SankeyLink(source="root", target=nid, value=value, group=group))
    for (akey, model), value in attr_model.items():
        mid = f"model:{model}"
        nodes.setdefault(mid, SankeyNode(id=mid, label=model, tier=2, group=model))
        links.append(SankeyLink(source=f"attr:{akey}", target=mid, value=value, group=model))
    for (model, key), value in model_kind.items():
        kid = f"kind:{key}"
        nodes.setdefault(kid, SankeyNode(id=kid, label=kind_labels[key], tier=3, group=key))
        links.append(SankeyLink(source=f"model:{model}", target=kid, value=value, group=key))

    title = "Token flow" if weight == "tokens" else "Cost flow"
    unit: FlowUnit = "tokens" if weight == "tokens" else "USD"
    used = {ln.source for ln in links} | {ln.target for ln in links}
    return SankeyGraph(
        title=title,
        unit=unit,
        nodes=[n for n in nodes.values() if n.id in used],
        links=links,
    )


# --------------------------------------------------------------------------- #
# page assembly
# --------------------------------------------------------------------------- #
def _stat_tiles(session: Session) -> list[StatTile]:
    cost = session.cost_summary()
    calls = session.tool_calls()
    tokens = (
        cost.input_tokens
        + cost.output_tokens
        + cost.cache_creation_input_tokens
        + cost.cache_read_input_tokens
    )
    cache_share = f"{cost.cache_read_input_tokens / tokens:.0%}" if tokens else "n/a"
    money = f"${cost.total_cost_usd:,.2f}" if cost.total_cost_usd is not None else "n/a"
    return [
        StatTile(label="Cost", value=money),
        StatTile(label="Tokens", value=f"{tokens:,}"),
        StatTile(label="Cache-read share", value=cache_share),
        StatTile(label="API requests", value=f"{cost.requests:,}"),
        StatTile(label="Tool calls", value=f"{len(calls):,}"),
        StatTile(label="Errors", value=f"{sum(1 for c in calls if c.is_error):,}"),
    ]


def build_page_model(session: Session) -> SessionPage:
    return SessionPage(
        title=session.label(),
        stats=_stat_tiles(session),
        graphs=[
            token_graph(session, weight="tokens"),
            token_graph(session, weight="USD"),
            tool_activity_graph(session),
        ],
    )


_PAGE_ADAPTER: TypeAdapter[SessionPage] = TypeAdapter(SessionPage)


def build_page(session: Session) -> str:
    page = build_page_model(session)
    colors = assign_colors([n.group for g in page.graphs for n in g.nodes])
    page_json = safe_json(_PAGE_ADAPTER.dump_json(page).decode())
    body = '<div class="stats" id="stats"></div><div id="charts"></div>'
    return render_page(
        title=page.title,
        subtitle=_SUBTITLE,
        colors=colors,
        body=body,
        script=f"const PAGE = {page_json};\n{_SANKEY_JS}",
        extra_css=_SANKEY_CSS,
    )


_SANKEY_CSS = r"""
.node rect{stroke:var(--surface);stroke-width:2}
.node text{fill:var(--ink);font-size:12px;dominant-baseline:middle}
.node .val{fill:var(--muted);font-variant-numeric:tabular-nums}
.link{fill-opacity:.42;transition:fill-opacity .12s}
.link:hover{fill-opacity:.72}
.dim .link{fill-opacity:.08}
.dim .link.hot{fill-opacity:.78}
"""

_SANKEY_JS = r"""
const NS = "http://www.w3.org/2000/svg";
PAGE.stats.forEach(s => {
  const tile = el("div", "tile");
  tile.append(el("div", "v", s.value), el("div", "l", s.label));
  document.getElementById("stats").appendChild(tile);
});

const NODE_W = 15, GAP = 12, PADX = 8, PADY = 14, ROW = 46;

function layout(graph, width){
  const tiers = [...new Set(graph.nodes.map(n => n.tier))].sort((a,b)=>a-b);
  const maxTier = tiers[tiers.length-1];
  const outSum = {}, inSum = {};
  graph.links.forEach(l => { outSum[l.source]=(outSum[l.source]||0)+l.value;
                             inSum[l.target]=(inSum[l.target]||0)+l.value; });
  const nodeVal = id => Math.max(outSum[id]||0, inSum[id]||0);
  const byTier = {}; tiers.forEach(ti => byTier[ti] = graph.nodes.filter(n => n.tier===ti));
  const maxCount = Math.max(...tiers.map(ti => byTier[ti].length));
  const height = Math.max(240, maxCount * ROW);

  let unit = Infinity;
  tiers.forEach(ti => {
    const sum = byTier[ti].reduce((s,n)=>s+nodeVal(n.id),0) || 1;
    const avail = height - 2*PADY - (byTier[ti].length-1)*GAP;
    unit = Math.min(unit, avail / sum);
  });

  const innerW = width - 2*PADX - NODE_W;
  const pos = {};
  tiers.forEach(ti => {
    const x = PADX + (maxTier ? ti/maxTier : 0) * innerW;
    const col = byTier[ti].slice().sort((a,b)=>nodeVal(b.id)-nodeVal(a.id));
    const colH = col.reduce((s,n)=>s+Math.max(nodeVal(n.id)*unit,2),0) + (col.length-1)*GAP;
    let y = (height - colH)/2;
    col.forEach(n => { const h = Math.max(nodeVal(n.id)*unit,2);
      pos[n.id] = {x, y, h, node:n, so:0, ti:0, val:nodeVal(n.id)}; y += h + GAP; });
  });

  const links = graph.links.map(l => ({...l})).sort((a,b)=>
    pos[a.source].y - pos[b.source].y || pos[a.target].y - pos[b.target].y);
  links.forEach(l => {
    const s=pos[l.source], tg=pos[l.target], th=l.value*unit;
    l.sy = s.y + s.so + th/2; s.so += th;
    l.ty = tg.y + tg.ti + th/2; tg.ti += th;
    l.th = th;
  });
  return {height, width, pos, links};
}

function ribbon(l, pos){
  const x0 = pos[l.source].x + NODE_W, x1 = pos[l.target].x;
  const xm = (x0+x1)/2, h = l.th/2;
  return `M${x0},${l.sy-h} C${xm},${l.sy-h} ${xm},${l.ty-h} ${x1},${l.ty-h}`
       + ` L${x1},${l.ty+h} C${xm},${l.ty+h} ${xm},${l.sy+h} ${x0},${l.sy+h} Z`;
}

function draw(graph){
  const card = el("div", "card");
  card.append(el("h2", null, graph.title), el("div", "unit", "by " + graph.unit));
  const width = Math.max(720, document.getElementById("charts").clientWidth || 900);
  const L = layout(graph, width);
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${L.height}`);
  svg.setAttribute("preserveAspectRatio", "xMinYMin meet");

  const gLinks = document.createElementNS(NS, "g");
  L.links.forEach(l => {
    const p = document.createElementNS(NS, "path");
    p.setAttribute("d", ribbon(l, L.pos));
    p.setAttribute("fill", color(l.group));
    p.setAttribute("class", "link");
    const s = L.pos[l.source].node.label, tg = L.pos[l.target].node.label;
    p.addEventListener("mousemove", e => tip(e, `${s} → ${tg}: ${fmt(l.value)} ${graph.unit}`));
    p.addEventListener("mouseleave", hideTip);
    p._nodes = [l.source, l.target];
    gLinks.appendChild(p);
  });
  svg.appendChild(gLinks);

  Object.values(L.pos).forEach(pn => {
    const g = document.createElementNS(NS, "g"); g.setAttribute("class", "node");
    const r = document.createElementNS(NS, "rect");
    r.setAttribute("x", pn.x); r.setAttribute("y", pn.y);
    r.setAttribute("width", NODE_W); r.setAttribute("height", pn.h);
    r.setAttribute("rx", 3); r.setAttribute("fill", color(pn.node.group));
    g.appendChild(r);

    const right = pn.x < width/2;
    const label = document.createElementNS(NS, "text");
    label.setAttribute("x", right ? pn.x + NODE_W + 7 : pn.x - 7);
    label.setAttribute("y", pn.y + pn.h/2);
    label.setAttribute("text-anchor", right ? "start" : "end");
    label.appendChild(document.createTextNode(pn.node.label + " "));
    const ts = document.createElementNS(NS, "tspan");
    ts.setAttribute("class", "val"); ts.textContent = fmt(pn.val);
    label.appendChild(ts);
    g.appendChild(label);

    g.addEventListener("mouseenter", () => {
      svg.classList.add("dim");
      [...gLinks.children].forEach(p => p.classList.toggle("hot", p._nodes.includes(pn.node.id)));
    });
    g.addEventListener("mouseleave", () => {
      svg.classList.remove("dim");
      [...gLinks.children].forEach(p => p.classList.remove("hot"));
    });
    svg.appendChild(g);
  });

  card.appendChild(svg);
  document.getElementById("charts").appendChild(card);
}

function renderAll(){
  const c = document.getElementById("charts");
  while (c.firstChild) c.removeChild(c.firstChild);
  PAGE.graphs.forEach(draw);
}
renderAll();
addEventListener("resize", renderAll);
"""
