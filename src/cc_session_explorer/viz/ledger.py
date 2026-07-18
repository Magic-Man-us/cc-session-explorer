"""Cost-ledger HTML report over a directory of Claude Code sessions.

The aggregation is owned by :func:`cc_session_core.ledger.build_ledger` (counted once per
API request); this module only renders that :class:`~cc_session_core.ledger.ProjectLedger`
to a self-contained page: KPI tiles, cost-over-time bars, cost-by-model bars, and
a sortable per-session table.
"""

from __future__ import annotations

import argparse
import webbrowser
from pathlib import Path

from cc_session_core import DEFAULT_PROJECTS_ROOT, ProjectLedger, build_ledger
from pydantic import TypeAdapter

from .htmlshell import StatTile, assign_colors, render_page, safe_json

_SUBTITLE = "Every session under this tree, counted once per API request."

_LEDGER_ADAPTER: TypeAdapter[ProjectLedger] = TypeAdapter(ProjectLedger)
_STATS_ADAPTER: TypeAdapter[list[StatTile]] = TypeAdapter(list[StatTile])


def _stat_tiles(ledger: ProjectLedger) -> list[StatTile]:
    per_session = ledger.total_cost_usd / ledger.sessions if ledger.sessions else 0.0
    span = f"{ledger.start_date} → {ledger.end_date}" if ledger.start_date else "—"
    return [
        StatTile(label="Total cost", value=f"${ledger.total_cost_usd:,.2f}"),
        StatTile(label="Sessions", value=f"{ledger.sessions:,}"),
        StatTile(label="Tokens", value=f"{ledger.total_tokens:,}"),
        StatTile(label="API requests", value=f"{ledger.total_requests:,}"),
        StatTile(label="Avg $/session", value=f"${per_session:,.2f}"),
        StatTile(label="Date range", value=span),
    ]


def build_page(directory: str | Path) -> str:
    ledger = build_ledger(directory)
    colors = assign_colors(["cost", *(m.model for m in ledger.by_model)])
    ledger_json = safe_json(_LEDGER_ADAPTER.dump_json(ledger).decode())
    stats_json = safe_json(_STATS_ADAPTER.dump_json(_stat_tiles(ledger)).decode())
    body = (
        '<div class="stats" id="stats"></div>'
        '<div class="card"><h2>Cost over time</h2><div class="unit">USD per day</div>'
        '<div id="days"></div></div>'
        '<div class="card"><h2>Cost by model</h2><div class="unit">USD, all sessions</div>'
        '<div id="models"></div></div>'
        '<div class="card"><h2>Sessions</h2>'
        '<div class="unit">click a column to sort</div><div id="table"></div></div>'
    )
    script = f"const LEDGER = {ledger_json};\nconst STATS = {stats_json};\n{_LEDGER_JS}"
    return render_page(
        title=f"Cost ledger — {ledger.root}",
        subtitle=_SUBTITLE,
        colors=colors,
        body=body,
        script=script,
        extra_css=_LEDGER_CSS,
    )


_LEDGER_CSS = r"""
table{width:100%;border-collapse:collapse;font-size:12px}
th{text-align:left;color:var(--muted);font-weight:600;cursor:pointer;padding:6px 10px;
  border-bottom:1px solid var(--hair);white-space:nowrap;user-select:none}
th.num,td.num{text-align:right;font-variant-numeric:tabular-nums}
th.up::after{content:" ▴"} th.down::after{content:" ▾"}
td{padding:6px 10px;border-bottom:1px solid var(--hair);color:var(--ink)}
tr:hover td{background:var(--page)}
.trunc{max-width:340px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.swatch{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:6px;vertical-align:middle}
.mrow{display:flex;align-items:center;gap:10px;margin:5px 0}
.mrow .name{width:190px;flex:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mrow .track{flex:1;height:16px;background:var(--page);border-radius:4px;overflow:hidden}
.mrow .fill{height:100%;border-radius:4px}
.mrow .amt{width:150px;flex:none;text-align:right;color:var(--ink2);font-variant-numeric:tabular-nums}
"""

_LEDGER_JS = r"""
const NS = "http://www.w3.org/2000/svg";
const money = n => "$" + n.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});

STATS.forEach(s => {
  const tile = el("div", "tile");
  tile.append(el("div", "v", s.value), el("div", "l", s.label));
  document.getElementById("stats").appendChild(tile);
});

function drawDays(){
  const host = document.getElementById("days");
  while (host.firstChild) host.removeChild(host.firstChild);
  const days = LEDGER.by_day;
  if (!days.length) { host.appendChild(el("div", "unit", "no dated sessions")); return; }
  const W = Math.max(720, host.clientWidth || 900), H = 200, PAD = 26, GAP = 2;
  const max = Math.max(...days.map(d => d.cost_usd), 0.0001);
  const bw = (W - 2*PAD) / days.length;
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  days.forEach((d, i) => {
    const h = (d.cost_usd / max) * (H - 2*PAD);
    const r = document.createElementNS(NS, "rect");
    r.setAttribute("x", PAD + i*bw + GAP/2); r.setAttribute("y", H - PAD - h);
    r.setAttribute("width", Math.max(bw - GAP, 1)); r.setAttribute("height", Math.max(h, 0));
    r.setAttribute("rx", 2); r.setAttribute("fill", color("cost"));
    r.addEventListener("mousemove", e =>
      tip(e, `${d.date}: ${money(d.cost_usd)} · ${d.sessions} session(s)`));
    r.addEventListener("mouseleave", hideTip);
    svg.appendChild(r);
  });
  [days[0], days[days.length-1]].forEach((d, k) => {
    const tx = document.createElementNS(NS, "text");
    tx.setAttribute("x", k ? W - PAD : PAD); tx.setAttribute("y", H - 8);
    tx.setAttribute("text-anchor", k ? "end" : "start");
    tx.setAttribute("fill", "var(--muted)"); tx.setAttribute("font-size", "11");
    tx.textContent = d.date; svg.appendChild(tx);
  });
  host.appendChild(svg);
}

function drawModels(){
  const host = document.getElementById("models");
  while (host.firstChild) host.removeChild(host.firstChild);
  const models = LEDGER.by_model;
  const total = models.reduce((s,m)=>s+m.cost_usd,0) || 1;
  const max = Math.max(...models.map(m=>m.cost_usd), 0.0001);
  models.forEach(m => {
    const row = el("div", "mrow");
    const name = el("div", "name");
    const sw = el("span", "swatch"); sw.style.background = color(m.model);
    name.append(sw, document.createTextNode(m.model));
    const track = el("div", "track");
    const fill = el("div", "fill");
    fill.style.width = (m.cost_usd/max*100) + "%"; fill.style.background = color(m.model);
    track.appendChild(fill);
    const amt = el("div", "amt", `${money(m.cost_usd)} · ${(m.cost_usd/total*100).toFixed(1)}%`);
    row.append(name, track, amt);
    host.appendChild(row);
  });
}

const COLS = [
  {k:"date", label:"Date", num:false},
  {k:"title", label:"Session", num:false, trunc:true},
  {k:"project", label:"Project", num:false, trunc:true},
  {k:"model", label:"Model", num:false},
  {k:"requests", label:"Req", num:true},
  {k:"tool_calls", label:"Tools", num:true},
  {k:"tokens", label:"Tokens", num:true},
  {k:"cost_usd", label:"Cost", num:true, money:true},
];
let sortKey = "cost_usd", sortDown = true;

function buildTable(){
  const host = document.getElementById("table");
  while (host.firstChild) host.removeChild(host.firstChild);
  const rows = LEDGER.rows.slice().sort((a,b) => {
    const x = a[sortKey], y = b[sortKey];
    const cmp = typeof x === "number" ? x - y : String(x).localeCompare(String(y));
    return sortDown ? -cmp : cmp;
  });
  const table = el("table");
  const thead = el("thead"), htr = el("tr");
  COLS.forEach(c => {
    const th = el("th", c.num ? "num" : null, c.label);
    if (c.k === sortKey) th.classList.add(sortDown ? "down" : "up");
    th.addEventListener("click", () => {
      if (sortKey === c.k) sortDown = !sortDown; else { sortKey = c.k; sortDown = true; }
      buildTable();
    });
    htr.appendChild(th);
  });
  thead.appendChild(htr); table.appendChild(thead);
  const tbody = el("tbody");
  rows.forEach(r => {
    const tr = el("tr");
    COLS.forEach(c => {
      const v = r[c.k];
      const text = c.money ? money(v) : (c.num ? fmt(v) : v);
      const td = el("td", c.num ? "num" : (c.trunc ? "trunc" : null), text);
      if (c.trunc) td.title = v;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody); host.appendChild(table);
}

function renderAll(){ drawDays(); drawModels(); buildTable(); }
renderAll();
addEventListener("resize", () => { drawDays(); drawModels(); });
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render a cost ledger over a directory of Claude Code sessions."
    )
    parser.add_argument(
        "directory",
        nargs="?",
        help="a projects directory (default: ~/.claude/projects)",
    )
    parser.add_argument("-o", "--out", help="output HTML path (default: ./ledger.html)")
    parser.add_argument("--open", action="store_true", help="open the page in the default browser")
    args = parser.parse_args(argv)

    directory = Path(args.directory).expanduser() if args.directory else DEFAULT_PROJECTS_ROOT
    out = Path(args.out).expanduser() if args.out else Path.cwd() / "ledger.html"
    out.write_text(build_page(directory), encoding="utf-8")
    print(f"wrote {out}")
    if args.open:
        webbrowser.open(out.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
