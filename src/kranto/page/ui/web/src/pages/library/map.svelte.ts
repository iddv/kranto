// The Library's Map and Clusters (WORKSPACE.md 2.6, 4, 5; W3): the server's /api/map (the latest
// snapshot's 2-d projection, its clusters and its points as columns), /api/clusters (the clusters
// as themes, with their movement) and /api/archive/themes (the Parallax archive's own themes).
// The shapes are the server's, generated from its web/types.py (api/afk.gen.ts).
//
// The map's SVG is built once per snapshot (thousands of points) and kept here, outside the
// components: a draw only moves its highlight (mapHighlight), and the list's "Highlight
// observations containing…" (MAP.words) reaches the pane's SVG through this module.
import type { ArchivePoint, ArchiveThemes, Cluster, Map, TrajectoryPoint } from "../../api/afk.gen";
import { pct } from "../../lib/format";
import { go, parse } from "../../lib/router";
import { peek, read, type Read } from "../../lib/reads.svelte";
export type { ArchiveTheme, ArchiveThemes, Cluster, Clusters, Map, ObservationPage } from "../../api/afk.gen";

export const MAP_API = "/api/map";
export const ARCHIVE_THEMES = "/api/archive/themes";
export const CLUSTERS_API = "/api/clusters";
/** the map, asked for only once there is one: /api/clusters answers 200 before the first map
 * (no snapshot, with the progress), so a fresh install's page never asks /api/map for the 404
 * that means "not yet", an error in the console (QA B20). Before the first map: an error read
 * ("no map yet"), as the 404 was; a the server whose clusters cannot be read: /api/map as before */
export function mapRead(): Read<Map> {
  const cl = read<{ snapshot: unknown }>(CLUSTERS_API, 60000);
  if (cl.data && !cl.data.snapshot) return { data: null, error: "no map yet", at: cl.at, loading: false };
  if (!cl.data && !cl.error) return { data: null, error: null, at: 0, loading: true };
  return read<Map>(MAP_API, 600000);
}
/** the list's highlight: the words typed in "Highlight observations containing…", kept across
 * draws and pages as the old page kept them */
export const MAP = $state({ words: "" });

const SVGNS = "http://www.w3.org/2000/svg";
const PAD = 24, SIDE = 1000;
/** the SVG of one snapshot: each point's place (at: id → [x, y, index]), its circle, each
 * cluster's colour slot (the eight largest 1–8, the rest 0, grey) */
export interface MapView {
  id: number;
  svg: SVGSVGElement;
  hl: SVGGElement;
  at: globalThis.Map<number, [number, number, number]>;
  dots: globalThis.Map<number, SVGCircleElement>;
  slot: globalThis.Map<number, number>;
  shown: string | null;
}
let MAPV: MapView | null = null;
/** the colour slots alone (the list's swatches), without building the SVG */
export const slots = (d: Map): globalThis.Map<number, number> => new globalThis.Map(d.clusters.map((c, i) => [c.cluster, i < 8 ? i + 1 : 0]));
/** the map as an SVG scatter coloured by cluster, built once per snapshot; a click on a point
 * selects it (?p=) */
export function mapView(d: Map): MapView {
  if (MAPV && MAPV.id === d.snapshot.id) return MAPV;
  const slot = slots(d);
  const svg = document.createElementNS(SVGNS, "svg"), at: MapView["at"] = new globalThis.Map(), dots: MapView["dots"] = new globalThis.Map();
  svg.setAttribute("viewBox", `${-PAD} ${-PAD} ${SIDE + 2 * PAD} ${SIDE + 2 * PAD}`);
  svg.setAttribute("class", "viz");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `Map of ${d.points.id.length} observations in ${d.clusters.length} clusters. The list below the map has the same points.`);
  const g = document.createElementNS(SVGNS, "g"), hl = document.createElementNS(SVGNS, "g");
  const p = d.points; // the projection is scaled to about the unit square, outliers beyond it
  const lo = (k: "x" | "y") => Math.min(0, ...p[k]), span = (k: "x" | "y") => Math.max(1, ...p[k]) - lo(k) || 1;
  const x0 = lo("x"), y0 = lo("y"), xs = span("x"), ys = span("y");
  for (let i = 0; i < p.id.length; i++) {
    const id = p.id[i] as number, c = p.c[i] as number;
    const x = (((p.x[i] as number) - x0) / xs) * SIDE, y = (1 - ((p.y[i] as number) - y0) / ys) * SIDE, el = document.createElementNS(SVGNS, "circle");
    el.setAttribute("cx", x.toFixed(1));
    el.setAttribute("cy", y.toFixed(1));
    el.setAttribute("r", "8");
    el.setAttribute("class", "pt k" + slot.get(c));
    el.dataset.id = String(id);
    el.dataset.c = String(c);
    const t = document.createElementNS(SVGNS, "title");
    t.textContent = p.t[i] ?? "";
    el.append(t);
    g.append(el);
    at.set(id, [x, y, i]);
    dots.set(id, el);
  }
  svg.append(g, hl);
  svg.addEventListener("click", (e) => {
    const el = (e.target as Element).closest<SVGElement>("circle[data-id]");
    if (el) go("library/map", { ...parse().q, p: el.dataset.id || "" });
  });
  MAPV = { id: d.snapshot.id, svg, hl, at, dots, slot, shown: null };
  return MAPV;
}
/** is a point dimmed: outside the one cluster shown (?c=), or without the highlighted words */
export const dimmed = (text: string, c: number, only: string | null | undefined, words: string): boolean => {
  const w = words.trim().toLowerCase();
  // only: one cluster (?c=), or a topic's clusters as "3,7,9" (a topic's Map, WT)
  return (only !== "" && only != null && !String(only).split(",").includes(String(c))) || (w.length > 1 && !text.toLowerCase().includes(w));
};
/** the highlight: the points dimmed, the selected one ringed with lines to its nearest */
export function mapHighlight(v: MapView, sel: number | null, near: { id: number }[], only: string | null | undefined, words: string): void {
  const key = [sel, near.map((n) => n.id).join(","), only, words].join("|");
  if (v.shown === key) return;
  v.shown = key;
  for (const el of v.dots.values()) el.classList.toggle("dim", dimmed(el.firstChild?.textContent || "", Number(el.dataset.c), only, words));
  v.hl.replaceChildren();
  const me = sel == null ? undefined : v.at.get(sel);
  if (!me) return;
  const add = (tag: string, a: Record<string, string | number>) => {
    const el = document.createElementNS(SVGNS, tag);
    for (const k in a) el.setAttribute(k, String(a[k]));
    v.hl.append(el);
  };
  for (const n of near) {
    const o = v.at.get(n.id);
    if (o) add("line", { x1: me[0], y1: me[1], x2: o[0], y2: o[1], class: "nb-line" });
  }
  for (const n of near) {
    const o = v.at.get(n.id);
    if (o) add("circle", { cx: o[0], cy: o[1], r: 13, class: "nb" });
  }
  add("circle", { cx: me[0], cy: me[1], r: 17, class: "sel" });
}

/** an observation's theme, from the map when it has been read (WORKSPACE.md 6.4); else null */
export function mapTheme(oid: number | string): { cluster: number; label: string } | null {
  const m = peek<Map>(MAP_API)?.data;
  if (!m || !m.points) return null;
  const k = m.points.id.indexOf(Number(oid));
  if (k < 0) return null;
  const cl = m.clusters.find((x) => x.cluster === m.points.c[k]);
  return cl ? { cluster: cl.cluster, label: cl.label || cl.name || "cluster " + cl.cluster } : null;
}

/** a theme's state: rising, a burst, or steady, as [glyph, colour, word] */
export const themeSt = (c: Pick<Cluster, "rising" | "movement">): [string, string, string] =>
  c.rising ? ["ready", "blue", "Rising"] : c.movement?.burst === 1 ? ["ready", "grey", "Burst"] : ["skipped", "grey", "Steady"];
/** a theme's movement since the last map, in words */
export function moveText(c: Pick<Cluster, "movement">): string | null {
  const m = c.movement;
  if (!m) return null;
  const pts = (v: number) => (v >= 0 ? "+" : "") + (v * 100).toFixed(2);
  return `${pts(m.delta)} pts` + (m.excess != null ? `, excess ${pts(m.excess)}` : "")
    + (m.new_total != null ? ` · new ${m.new_in_cluster}/${m.new_total}` + (m.expected_new != null ? ` vs ${Number(m.expected_new).toFixed(1)} expected` : "")
      + (m.q_value != null ? `, q ${Number(m.q_value).toPrecision(3)}` : "") : "");
}
/** a sparkline's line and its words: the share over the maps (or Parallax's snapshots); null
 * with fewer than two */
export function sparkLine(traj: (TrajectoryPoint | ArchivePoint)[] | null | undefined): { points: string; label: string } | null {
  if (!traj || traj.length < 2) return null;
  const raw = traj.map((t) => t.share), s = raw.map(Number), hi = Math.max(...s), lo = Math.min(...s), span = hi > lo ? hi - lo : 1;
  return {
    points: s.map((v, i) => `${((i / (s.length - 1)) * 100).toFixed(1)},${(22 - ((v - lo) / span) * 20).toFixed(1)}`).join(" "),
    label: `share over ${s.length} maps: ${pct(raw[0], 1)} to ${pct(raw[raw.length - 1], 1)}`,
  };
}
/** a Parallax theme's name, by its lineage (its id until the themes are read) */
export const archiveName = (d: ArchiveThemes | null | undefined, lineage: string): string => {
  const t = d?.themes.find((x) => x.lineage_id === lineage);
  return t ? t.name || lineage : lineage;
};
