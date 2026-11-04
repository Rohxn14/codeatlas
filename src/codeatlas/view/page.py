# ruff: noqa: E501  (the page below is HTML, CSS and JavaScript in one string; long lines are fine there)
"""Turns view data into one self-contained HTML file.

The data is embedded as JSON; the page builds every element with `textContent`, never
`innerHTML`, because names, docstrings and paths come from an untrusted repository.
cytoscape.js is the only outside file; without it every list still works.
"""

from __future__ import annotations

import json
import webbrowser
from pathlib import Path
from typing import Any

CYTOSCAPE_URL = "https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.30.2/cytoscape.min.js"
MAX_GRAPH_NODES = 150


def render_html(data: dict[str, Any]) -> str:
    """The full page. `<` is escaped in the JSON so no repository text can close the tag."""
    payload = json.dumps(data, ensure_ascii=True).replace("<", "\\u003c")
    title = f"CodeAtlas: {data['snapshot']['repo']}"
    return (
        _TEMPLATE.replace("__TITLE__", _escape(title))
        .replace("__CYTOSCAPE__", CYTOSCAPE_URL)
        .replace("__MAX_GRAPH__", str(MAX_GRAPH_NODES))
        .replace("__DATA__", payload)
    )


def write_view(data: dict[str, Any], out: Path, open_browser: bool = True) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(data), encoding="utf-8")
    if open_browser:
        webbrowser.open(out.resolve().as_uri())
    return out


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#fff;--fg:#1d2330;--mute:#667085;--line:#d9dee7;--panel:#f6f8fb;--warn:#b54708;--warnbg:#fff4e5;--acc:#2457d6}
@media (prefers-color-scheme:dark){:root{--bg:#14171f;--fg:#e6e9f0;--mute:#9aa4b5;--line:#2b3140;--panel:#1b202b;--warn:#f7b267;--warnbg:#3a2a12;--acc:#7da2ff}}
*{box-sizing:border-box}body{margin:0;font:14px/1.45 system-ui,sans-serif;background:var(--bg);color:var(--fg)}
header,section{padding:12px 20px;border-bottom:1px solid var(--line)}
h1{margin:0 0 4px;font-size:20px}h2{margin:0 0 8px;font-size:15px}
.mute{color:var(--mute)}.warn{background:var(--warnbg);color:var(--warn);padding:6px 10px;border-radius:6px;margin:6px 0}
table{border-collapse:collapse}th,td{padding:3px 10px;border-bottom:1px solid var(--line);text-align:right}
th:first-child,td:first-child{text-align:left}
#explorer{display:grid;grid-template-columns:minmax(220px,1fr) minmax(260px,1fr) minmax(300px,2fr);gap:12px}
.pane{border:1px solid var(--line);border-radius:6px;padding:8px;max-height:520px;overflow:auto;background:var(--panel)}
.row{padding:2px 4px;cursor:pointer;border-radius:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row:hover{background:var(--line)}.row.sel{background:var(--acc);color:#fff}
code,pre{font:12px ui-monospace,monospace}pre{white-space:pre-wrap;margin:4px 0}
#graph{height:420px;border:1px solid var(--line);border-radius:6px;background:var(--panel)}
.tag{font-size:11px;padding:0 6px;border:1px solid var(--line);border-radius:8px;margin-left:4px}
@media (max-width:900px){#explorer{grid-template-columns:1fr}}
</style></head><body>
<header id="header"></header>
<section id="impactbox" hidden><h2>Impact of the change</h2><div id="impact"></div></section>
<section><h2>Census</h2><div id="census"></div></section>
<section><h2>Packages</h2><div id="packages"></div></section>
<section><h2>Explorer</h2><div id="explorer">
<div class="pane" id="tree"></div><div class="pane" id="symbols"></div><div class="pane" id="detail"></div></div></section>
<section><h2>Neighbourhood graph</h2><div id="graphnote" class="mute"></div><div id="graph"></div></section>
<section><h2>Problems</h2><div id="problems"></div></section>
<script type="application/json" id="data">__DATA__</script>
<script src="__CYTOSCAPE__" onerror="window.noGraph=true"></script>
<script>
"use strict";
const D = JSON.parse(document.getElementById("data").textContent);
const MAXG = __MAX_GRAPH__;
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") el.className = v; else if (k === "onclick") el.onclick = v; else el.setAttribute(k, v);
  }
  for (const kid of kids.flat(Infinity)) if (kid !== null && kid !== undefined) el.append(kid instanceof Node ? kid : String(kid));
  return el;
}
function fill(id, ...kids) { const el = document.getElementById(id); el.replaceChildren(...kids.flat(Infinity).filter(k => k !== null && k !== undefined)); }
function table(head, rows) {
  return h("table", {}, h("tr", {}, head.map(c => h("th", {}, c))), rows.map(r => h("tr", {}, r.map(c => h("td", {}, c)))));
}
const pct = (a, b) => b ? Math.round(100 * a / b) + "%" : "n/a";
const byKey = new Map(D.nodes.map((n, i) => [n.key, i]));
const out = D.nodes.map(() => []), inn = D.nodes.map(() => []);
D.edges.forEach((e, i) => { out[e.s].push(i); inn[e.d].push(i); });
const calls = D.nodes.map(() => []);
D.unresolved_calls.forEach(c => calls[c.n].push(c));

function header() {
  const s = D.snapshot, o = D.omitted;
  const kids = [h("h1", {}, s.repo), h("div", { class: "mute" }, `commit ${s.commit_sha.slice(0, 12)} · indexed ${s.indexed_at} · CodeAtlas ${s.indexer_version} · source ${s.source}`)];
  if (D.snapshot.limits_hit.length) kids.push(h("div", { class: "warn" }, "Limits hit: " + D.snapshot.limits_hit.join(", ") + ". The index is partial."));
  if (D.focus) kids.push(h("div", { class: "mute" }, `Focused on ${D.focus}/ (--focus).`));
  if (o.nodes || o.files || o.edges) {
    let msg = `Not shown here: ${o.files} files, ${o.nodes} nodes, ${o.edges} edges`;
    msg += o.capped ? ` (the page holds at most ${o.max_nodes} nodes). ` : " (outside the focus). ";
    msg += "Run `codeatlas view --focus <folder>` to look at one part.";
    kids.push(h("div", { class: "warn" }, msg));
  }
  if (o.unresolved_calls) kids.push(h("div", { class: "warn" }, `${o.unresolved_calls} unresolved calls are not listed.`));
  fill("header", kids);
}
function census() {
  fill("census", table(["language", "tier", "files", "symbols", "raw calls", "resolved", "errors"],
    D.census.map(r => [r.language, r.tier, r.files, r.symbols, r.calls, pct(r.resolved, r.calls), r.errors])));
}
function packages() {
  if (!D.packages.length) return fill("packages", h("div", { class: "mute" }, "No packages found."));
  fill("packages", table(["package", "ecosystem", "role", "files", "depends on"],
    D.packages.map(p => [p.name, p.ecosystem || "", p.role, p.files, p.depends_on.join(", ")])));
}
// Impact (`codeatlas view --impact DIFF`): changed nodes and the top targets.
const changedSet = new Set((D.impact || {}).changed || []);
const targetSet = new Set(((D.impact || {}).targets || []).map(t => t.key));
function impactView() {
  const I = D.impact;
  if (!I) return;
  document.getElementById("impactbox").hidden = false;
  const link = key => byKey.has(key) ? h("a", { href: "#", onclick: () => { pickNode(byKey.get(key)); return false; } }, key) : key;
  const kids = [h("div", { class: "mute" }, `${I.changed.length} changed symbols, ${I.total} targets; the top ${I.targets.length} are listed. Changed nodes are red in the graph, targets orange.`)];
  kids.push(h("h3", {}, "Changed"), h("ul", {}, I.changed.map(k => h("li", {}, link(k)))));
  kids.push(h("h3", {}, "Could break"), table(["target", "kind", "score", "signal"], I.targets.map(t => [link(t.key), t.kind, t.score.toFixed(3), t.signal])));
  if (I.warnings.length) kids.push(I.warnings.map(w => h("div", { class: "warn" }, w)));
  fill("impact", kids);
}
function problems() {
  const p = D.problems, kids = [];
  if (p.report_missing) kids.push(h("div", { class: "warn" }, "No saved index report was found, so resolver failures and dropped edges are not shown. Run `codeatlas index --force` to create it."));
  const list = (title, items) => items.length ? [h("h3", {}, `${title} (${items.length})`), h("ul", {}, items.slice(0, 200).map(i => h("li", {}, i))), items.length > 200 ? h("div", { class: "mute" }, `... and ${items.length - 200} more`) : null] : [];
  kids.push(list("Files with errors", p.files_with_errors.map(f => `${f.path}: ${f.errors.join("; ")}`)));
  kids.push(list("Files not parsed", p.skipped_files.map(f => `${f.path}: ${f.reason}`)));
  kids.push(list("Languages without a resolver", p.languages_without_resolver));
  kids.push(list("Plugin, resolver and linker failures", p.failures));
  kids.push(list("Dropped edges", Object.entries(p.dropped_edges).map(([k, v]) => `${k}: ${v}`)));
  if (kids.flat(Infinity).length <= 0) kids.push(h("div", { class: "mute" }, "None."));
  fill("problems", kids);
}

// Explorer
let selFile = null, selNode = null;
function tree() {
  const folders = new Map();
  for (const f of D.files) {
    const dir = f.path.includes("/") ? f.path.slice(0, f.path.lastIndexOf("/")) : "";
    if (!folders.has(dir)) folders.set(dir, []);
    folders.get(dir).push(f);
  }
  const kids = [];
  for (const dir of [...folders.keys()].sort()) {
    const det = h("details", { open: "" }, h("summary", {}, (dir || "(root)") + ` · ${folders.get(dir).length}`));
    for (const f of folders.get(dir)) {
      det.append(h("div", { class: "row" + (f.path === selFile ? " sel" : ""), title: f.path, onclick: () => pickFile(f.path) }, f.path.split("/").pop(), h("span", { class: "tag" }, f.tier)));
    }
    kids.push(det);
  }
  if (!kids.length) kids.push(h("div", { class: "mute" }, "No files."));
  fill("tree", kids);
}
function symbols() {
  const idx = D.nodes.map((n, i) => i).filter(i => D.nodes[i].path === selFile);
  fill("symbols", idx.map(i => h("div", { class: "row" + (i === selNode ? " sel" : ""), title: D.nodes[i].qualname, onclick: () => pickNode(i) }, `${D.nodes[i].kind} ${D.nodes[i].qualname || D.nodes[i].name}`)));
  return idx;
}
function pickFile(path) {
  selFile = path; tree();
  const idx = symbols();
  if (idx.length) pickNode(idx[0]);
}
function edgeLine(e, other) {
  const n = D.nodes[other];
  return h("div", { class: "row", title: n.key, onclick: () => pickNode(other) },
    `${e.kind} → ${n.qualname || n.name} `, h("span", { class: "tag" }, `${e.res} ${e.conf}${e.line ? " L" + e.line : ""}`));
}
function group(title, ids, pick) {
  const by = new Map();
  for (const id of ids) { const e = D.edges[id]; if (!by.has(e.kind)) by.set(e.kind, []); by.get(e.kind).push(e); }
  const kids = [h("h3", {}, title + ` (${ids.length})`)];
  for (const [kind, list] of [...by].sort()) {
    kids.push(h("div", { class: "mute" }, kind));
    list.slice(0, 100).forEach(e => kids.push(edgeLine(e, pick(e))));
    if (list.length > 100) kids.push(h("div", { class: "mute" }, `... and ${list.length - 100} more`));
  }
  return kids;
}
function pickNode(i) {
  selNode = i; const n = D.nodes[i];
  if (n.path && n.path !== selFile) { selFile = n.path; tree(); }
  symbols();
  const kids = [h("h3", {}, `${n.kind} ${n.qualname || n.name}`),
    n.path ? h("code", {}, `${n.path}:${n.start}`) : h("span", { class: "mute" }, "no file"),
    n.signature ? h("pre", {}, n.signature) : null, n.doc ? h("pre", { class: "mute" }, n.doc) : null,
    n.skipped ? h("div", { class: "warn" }, "Not parsed: " + n.skipped) : null,
    n.errors.length ? h("div", { class: "warn" }, n.errors.join("; ")) : null,
    group("Outgoing", out[i], e => e.d), group("Incoming", inn[i], e => e.s)];
  if (calls[i].length) {
    kids.push(h("h3", {}, `Unresolved calls (${calls[i].length})`));
    calls[i].slice(0, 100).forEach(c => kids.push(h("div", {}, h("code", {}, `${c.t} L${c.l}`))));
  }
  fill("detail", kids); graph(i);
}

// Neighbourhood: breadth first to depth 2, stopping at MAXG nodes.
function neighbourhood(start) {
  const seen = new Set([start]); let frontier = [start];
  for (let depth = 0; depth < 2; depth++) {
    const next = [];
    for (const i of frontier) for (const id of [...out[i], ...inn[i]]) {
      const e = D.edges[id], o = e.s === i ? e.d : e.s;
      if (seen.size >= MAXG) break;
      if (!seen.has(o)) { seen.add(o); next.push(o); }
    }
    frontier = next;
  }
  return seen;
}
function graph(i) {
  const note = document.getElementById("graphnote"), box = document.getElementById("graph");
  const nodes = neighbourhood(i);
  const edges = D.edges.map((e, id) => id).filter(id => nodes.has(D.edges[id].s) && nodes.has(D.edges[id].d));
  note.textContent = `${nodes.size} nodes, ${edges.length} edges around ${D.nodes[i].qualname || D.nodes[i].name} (depth 2, at most ${MAXG} nodes).`;
  if (typeof cytoscape === "undefined") {
    note.textContent += " The graph library did not load (offline?), so the lists above carry the same edges.";
    box.style.display = "none"; return;
  }
  box.style.display = "block";
  const els = [...nodes].map(n => ({ data: { id: "n" + n, label: D.nodes[n].name || D.nodes[n].key, sel: n === i ? 1 : 0, imp: changedSet.has(D.nodes[n].key) ? 2 : targetSet.has(D.nodes[n].key) ? 1 : 0 } })).concat(
    edges.map(id => { const e = D.edges[id]; return { data: { id: "e" + id, source: "n" + e.s, target: "n" + e.d, kind: e.kind, conf: e.conf } }; }));
  const cy = cytoscape({ container: box, elements: els, layout: { name: "cose", animate: false },
    style: [{ selector: "node", style: { label: "data(label)", "font-size": 9, width: 14, height: 14, "background-color": "#7a8aa8" } },
      { selector: "node[imp = 1]", style: { "background-color": "#e08a1e" } },
      { selector: "node[imp = 2]", style: { "background-color": "#d0342c" } },
      { selector: "node[sel = 1]", style: { "background-color": "#2457d6", width: 22, height: 22 } },
      { selector: "edge", style: { width: 1.5, "curve-style": "bezier", "target-arrow-shape": "triangle", opacity: "mapData(conf, 0, 1, 0.15, 1)", "line-color": "#8895ad", "target-arrow-color": "#8895ad" } },
      { selector: "edge[kind = 'calls']", style: { "line-color": "#2457d6", "target-arrow-color": "#2457d6" } },
      { selector: "edge[kind = 'imports']", style: { "line-color": "#1a8f5a", "target-arrow-color": "#1a8f5a" } },
      { selector: "edge[kind = 'contains']", style: { "line-style": "dotted" } },
      { selector: "edge[kind = 'tests']", style: { "line-color": "#b54708", "target-arrow-color": "#b54708" } }] });
  cy.on("tap", "node", ev => pickNode(Number(ev.target.id().slice(1))));
}
header(); impactView(); census(); packages(); problems(); tree();
</script></body></html>
"""
