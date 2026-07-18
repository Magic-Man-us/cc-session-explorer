"""Shared chrome for the self-contained report pages.

Holds the validated data-viz colour palette, a colour-assignment pass over group
keys, HTML/JSON escaping, the base component CSS, and :func:`render_page` — which
wraps a page's body markup and script in the charset / theme / tooltip / toggle
shell and injects the per-group CSS colour variables. Each page supplies only its
own body, its own script, and any extra CSS; the palette and theming live here.
"""

from __future__ import annotations

from cc_session_core import SnakeModel
from cc_session_core import types as t
from pydantic_core import to_json


class StatTile(SnakeModel):
    """One header KPI: a big value over a small uppercase label."""

    label: t.DisplayName
    value: t.ResultText


# Categorical slots from the validated data-viz reference palette (light, dark).
_SLOTS: list[tuple[str, str]] = [
    ("#2a78d6", "#3987e5"),
    ("#1baf7a", "#199e70"),
    ("#eda100", "#c98500"),
    ("#008300", "#008300"),
    ("#4a3aa7", "#9085e9"),
    ("#e34948", "#e66767"),
    ("#e87ba4", "#d55181"),
    ("#eb6834", "#d95926"),
]
_FIXED: dict[str, tuple[str, str]] = {
    "root": ("#898781", "#898781"),
    "ok": ("#0ca30c", "#0ca30c"),
    "error": ("#d03b3b", "#d03b3b"),
    "cost": ("#2a78d6", "#3987e5"),
    "input": ("#2a78d6", "#3987e5"),
    "output": ("#1baf7a", "#199e70"),
    "cache_read": ("#4a3aa7", "#9085e9"),
    "cache_write_5m": ("#eb6834", "#d95926"),
    "cache_write_1h": ("#eda100", "#c98500"),
    "main": ("#2a78d6", "#3987e5"),
    "sidechain": ("#eb6834", "#d95926"),
}


def css_token(group: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in group)


def assign_colors(groups: list[str]) -> dict[str, tuple[str, str]]:
    """Map each group to a (light, dark) hex pair — fixed roles by name, every
    other group to the next categorical slot in first-seen order."""
    colors: dict[str, tuple[str, str]] = {}
    cursor = 0
    for group in groups:
        if group in colors:
            continue
        if group in _FIXED:
            colors[group] = _FIXED[group]
        else:
            colors[group] = _SLOTS[cursor % len(_SLOTS)]
            cursor += 1
    return colors


def escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def safe_json(payload: str) -> str:
    """Neutralize a ``</script>`` break-out inside embedded JSON."""
    return payload.replace("</", "<\\/")


def render_page(
    *,
    title: str,
    subtitle: str,
    colors: dict[str, tuple[str, str]],
    body: str,
    script: str,
    extra_css: str = "",
) -> str:
    """Assemble a full self-contained page from a page's body/script and the
    colour map. The body may reference the shared JS helpers (``color``, ``fmt``,
    ``el``, ``tip``/``hideTip``) and every ``--g-<group>`` CSS variable."""
    var_map = {group: f"--g-{css_token(group)}" for group in colors}
    light = "".join(f"{var_map[g]}:{lo};" for g, (lo, _) in colors.items())
    dark = "".join(f"{var_map[g]}:{hi};" for g, (_, hi) in colors.items())
    prelude = _PRELUDE.replace("%%GROUP_VARS%%", safe_json(to_json(var_map).decode()))
    return (
        _SHELL.replace("%%LIGHT_VARS%%", light)
        .replace("%%DARK_VARS%%", dark)
        .replace("%%BASE_CSS%%", _BASE_CSS)
        .replace("%%EXTRA_CSS%%", extra_css)
        .replace("%%TITLE%%", escape_html(title))
        .replace("%%SUBTITLE%%", escape_html(subtitle))
        .replace("%%BODY%%", body)
        .replace("%%PRELUDE%%", prelude)
        .replace("%%SCRIPT%%", script)
    )


_BASE_CSS = r"""
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.4}
.wrap{max-width:1180px;margin:0 auto;padding:32px 24px 64px}
h1{font-size:22px;font-weight:650;margin:0 0 4px;letter-spacing:-.01em}
.sub{color:var(--ink2);font-size:13px;margin-bottom:24px}
.stats{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin-bottom:28px}
@media(max-width:720px){.stats{grid-template-columns:repeat(3,1fr)}}
.tile{background:var(--surface);border:1px solid var(--ring);border-radius:12px;padding:14px 16px}
.tile .v{font-size:22px;font-weight:650;letter-spacing:-.02em}
.tile .l{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-top:3px}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:16px;
  padding:18px 18px 14px;margin-bottom:22px;overflow-x:auto}
.card h2{font-size:14px;font-weight:600;margin:0 0 2px}
.card .unit{font-size:12px;color:var(--muted);margin-bottom:10px}
svg{display:block;width:100%;height:auto}
.tip{position:fixed;pointer-events:none;background:var(--ink);color:var(--page);
  font-size:12px;padding:5px 9px;border-radius:7px;opacity:0;transition:opacity .1s;
  white-space:nowrap;z-index:9;font-variant-numeric:tabular-nums}
.toggle{position:fixed;top:14px;right:16px;background:var(--surface);color:var(--ink2);
  border:1px solid var(--ring);border-radius:8px;padding:6px 11px;font-size:12px;cursor:pointer}
"""

_PRELUDE = r"""
const GROUP_VARS = %%GROUP_VARS%%;
const color = g => `var(${GROUP_VARS[g] || "--muted"})`;
const fmt = n => n.toLocaleString();
const el = (tag, cls, text) => { const e = document.createElement(tag);
  if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const tipEl = document.getElementById("tip");
function tip(e, text){ tipEl.textContent = text; tipEl.style.opacity = 1;
  tipEl.style.left = (e.clientX+12)+"px"; tipEl.style.top = (e.clientY+12)+"px"; }
function hideTip(){ tipEl.style.opacity = 0; }
document.getElementById("themeBtn").addEventListener("click", () => {
  const cur = document.documentElement.getAttribute("data-theme");
  const next = cur==="dark" ? "light" : cur==="light" ? "dark"
    : (matchMedia("(prefers-color-scheme:dark)").matches ? "light" : "dark");
  document.documentElement.setAttribute("data-theme", next);
});
"""

_SHELL = r"""<meta charset="utf-8">
<style>
:root{
  --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --ring:rgba(11,11,11,.10); --hair:#e1e0d9;
  %%LIGHT_VARS%%
}
@media (prefers-color-scheme:dark){:root{
  --page:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
  --ring:rgba(255,255,255,.10); --hair:#2c2c2a;
  %%DARK_VARS%%
}}
:root[data-theme=light]{
  --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e;
  --ring:rgba(11,11,11,.10); --hair:#e1e0d9;
  %%LIGHT_VARS%%
}
:root[data-theme=dark]{
  --page:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7;
  --ring:rgba(255,255,255,.10); --hair:#2c2c2a;
  %%DARK_VARS%%
}
%%BASE_CSS%%
%%EXTRA_CSS%%
</style>

<button class="toggle" id="themeBtn">◐ theme</button>
<div class="wrap">
  <h1>%%TITLE%%</h1>
  <div class="sub">%%SUBTITLE%%</div>
  %%BODY%%
</div>
<div class="tip" id="tip"></div>

<script>
%%PRELUDE%%
%%SCRIPT%%
</script>
"""
