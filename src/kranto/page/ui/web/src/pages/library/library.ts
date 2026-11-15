// The Library's Observations (and a topic's Evidence, the same list) and Rollups (WORKSPACE.md 1.4, 2.1; W3): the server's
// /api/observations (a page of the library, or a search by meaning), one observation's page
// (/api/observations/<id>?k=12), the latest grades of a page's rows (/api/feedback?target=&ids=)
// and the compacted weeks (/api/rollups). The shapes are the server's, generated from its
// web/types.py (api/afk.gen.ts).
import type { Rollup, Rollups, StatusSource, StatusTopic } from "../../api/afk.gen";
export type { FeedbackGrades, Observation, ObservationPage, Observations, Rollup, Rollups, Status } from "../../api/afk.gen";

/** a score to two places; "–" without one */
export const n2 = (v: number | null | undefined): string => (v == null ? "–" : Number(v).toFixed(2));
/** "mild_signal" as "mild signal" */
export const words = (s: string | null | undefined): string => (s || "").replace(/_/g, " ");
export const obsHref = (id: number | string): string => "#/library/o/" + id;

/** what an observation's row shows: the library's rows, a page's neighbours, one step away (no
 * time), a theme's or a watch's members */
export interface ObsRow {
  id: number;
  signal: number;
  summary: string;
  title: string | null;
  kind: string;
  created_at?: string | null;
  source_id?: number | null;
  source_label?: string | null;
  new?: boolean;
  grade?: unknown;
}

export const KINDS: [string, string][] = [["beat", "beat"], ["mild_signal", "mild signal"], ["sharp_signal", "sharp signal"]];
const SINCE: Record<string, number> = { "24h": 24, "7d": 168 };

/** the read a list's filters make: a page of newest (or by signal, or oldest) with the filters,
 * or with q a search by meaning (by=words: the words in it); top=20 is the first 20 alone */
export interface ObsQuery {
  path: string;
  at: number;
  size: number;
  meaning: boolean;
  top: number;
}
export function obsQuery(q: Record<string, string>, now = Date.now()): ObsQuery {
  const p = new URLSearchParams(), at = Math.max(1, parseInt(q.page || "", 10) || 1), meaning = !!q.q && q.by !== "words";
  for (const k of ["topic", "source", "kind", "min_signal", "cluster", "theme"]) if (q[k]) p.set(k, q[k] as string);
  const top = meaning ? 0 : Math.max(0, parseInt(q.top || "", 10) || 0); // top=20: the first 20 only, no pages (Today's "See the top 20")
  const size = top || (meaning ? 20 : 100);
  const since = q.since ? SINCE[q.since] : undefined;
  // the cut is to the minute: a path that changed every second was a new read on every draw
  if (q.since) p.set("since", since ? new Date(Math.floor((now - since * 3600e3) / 60e3) * 60e3).toISOString().slice(0, 19) + "Z" : "last");
  if (meaning) {
    p.set("q", q.q as string);
    p.set("cutoff", "1");
  } else {
    if (q.q) p.set("contains", q.q);
    p.set("sort", q.sort || "new");
  }
  p.set("limit", String(size));
  p.set("offset", String(top ? 0 : (at - 1) * size));
  return { path: "/api/observations?" + p, at: top ? 1 : at, size, meaning, top };
}
/** the latest grades of a page's rows (the library's JSON does not carry them) */
export const gradesPath = (ids: number[]): string => `/api/feedback?target=observation&ids=${ids.map((i) => encodeURIComponent(i)).join(",")}`;

/** a filter of the toolbar: [its key in the URL, its name, its options as [value, words]] */
export type Select = [string, string, [string, string][]];
/** a topic's Evidence: the library's list with the topic fixed, its sources the Source filter's */
export interface EvidenceOf {
  id: number;
  name: string;
  source_rows: { id: number }[];
}
/** the library's filters (Filter ▾) and its sort; a search by meaning has no sort. A topic's
 * Evidence has no Topic filter, no Parallax archive and only the topic's sources */
export function obsSelects(host: { sources: Pick<StatusSource, "id" | "kind" | "label" | "status">[]; topics: Pick<StatusTopic, "id" | "name">[] }, meaning: boolean, topic: EvidenceOf | null = null): Select[] {
  const srcs = host.sources.filter((s) => ["approved", "imported", "retired"].includes(s.status || ""));
  // the Parallax archive (afk import parallax): all its sources at once, or one by its label
  const archive: [string, string][] = !topic && srcs.some((s) => s.kind === "parallax") ? [["parallax", "Parallax archive (all)"]] : [];
  const mine = topic ? srcs.filter((s) => topic.source_rows.some((x) => x.id === s.id)) : srcs;
  const out: Select[] = [["by", "Match", [["", "meaning"], ["words", "words"]]],
    ["since", "Since", [["", ""], ["last", "last visit"], ["24h", "24 h"], ["7d", "7 days"]]],
    ...(topic ? [] : [["topic", "Topic", [["", ""], ...host.topics.map((t): [string, string] => [String(t.id), t.name])]] as Select]),
    ["source", "Source", [["", ""], ...archive, ...mine.map((s): [string, string] => [String(s.id), s.label])]],
    ["kind", "Kind", [["", ""], ...KINDS]],
    ["min_signal", "Signal", [["", ""], ...["0.2", "0.3", "0.4", "0.5"].map((v): [string, string] => [v, v + " or more"])]]];
  if (!meaning) out.push(["sort", "Sort", [["", "newest"], ["signal", "highest signal"], ["old", "oldest"]]]);
  return out;
}
/** is the list narrowed by a filter (its empty state says "Nothing matches."); a topic's Evidence
 * is not narrowed by its own topic */
export const filtered = (q: Record<string, string>, topic = false): boolean =>
  ["q", "source", "kind", "min_signal", "cluster", "theme", "since", ...(topic ? [] : ["topic"])].some((k) => q[k]);
/** the order a page is in, in words */
export const byWords = (sort: string | undefined): string => ({ signal: "by signal", old: "oldest first" } as Record<string, string>)[sort || ""] || "newest first";
/** the last visit, as "Thu 09:12" */
export const visitWord = (ts: number | null): string => (ts ? new Date(ts * 1000).toLocaleString("en-GB", { weekday: "short", hour: "2-digit", minute: "2-digit" }) : "");

/** the compacted weeks: 50 a page newest first, or with q the 100 best matches (paged here) */
export const ROLLUPS_PAGE = 50;
export const rollupsPath = (q: Record<string, string>): string => {
  const at = Math.max(1, parseInt(q.page || "", 10) || 1);
  return q.q ? "/api/rollups?k=100&q=" + encodeURIComponent(q.q) : `/api/rollups?k=50&offset=${(at - 1) * ROLLUPS_PAGE}`;
};
/** a rollup of the list it was read in: the rollups' page, or a search's compacted weeks */
export function rollupIn(d: Rollups | { rollups?: Rollup[]; results?: unknown[] } | null, id: string): Rollup | null {
  if (!d) return null;
  const xs = (Array.isArray(d.rollups) ? d.rollups : d.results || []) as (Rollup | null)[];
  return xs.find((y) => y && String(y.id) === String(id) && y.period_start) || null;
}
/** a mix ({source: n}) as "HN 4, Lobsters 2 and 3 more" */
export const mix = (o: Record<string, number> | null | undefined, n: number): string => {
  const e = Object.entries(o || {});
  return e.slice(0, n).map(([k, v]) => `${k} ${v}`).join(", ") + (e.length > n ? ` and ${e.length - n} more` : "");
};
/** a rollup's mean signal: blue from 0.4 */
export const rollupSt = (x: Rollup): [string, string, string] => ["dot", x.mean_signal >= 0.4 ? "blue" : "grey", "mean signal " + n2(x.mean_signal)];
