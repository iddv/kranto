// What Kranto is doing: the one activity read (api/activity: the server's runs,
// the sessions) as the top bar's indicator, the Activity page, the
// one line a page says of its own subject (RunLine) and Needs you's Fix and waiting rows. Plain
// data, so the tests read it without a page; every word comes from the read, which says it.
import { byWords } from "../term/reflect.svelte";
import type { Activity, ActivityFail, ActivityIncident, ActivityRun } from "../api/types.gen";
import { dur, nextRead, plural } from "./format";

export const ACT_PATH = "api/activity";
/** the indicator's red dot stays until the owner opens Activity (stored as Mark all seen is) */
export const SEEN_KEY = "kranto.activity.seen";

export type Indicator = {
  state: "quiet" | "running" | "paused" | "failed";
  /** the word beside the dot or the ring: Quiet, 2 running, Paused */
  word: string;
  /** the words after it: "next: reading your sources at 20:23", the first running run */
  detail: string | null;
  /** runs that failed since the owner last opened Activity */
  failed: number;
  title: string;
};

/** the header facts the two lane words used, for before the read arrives (or an older the server) */
export interface LaneFacts {
  paused: boolean;
  /** the server's running job ("ingest") and its words, its next read */
  afkRunning: string | null;
  reading: string | null;
  next: string | null;
}

export const seenAt = (): string => {
  try {
    return localStorage.getItem(SEEN_KEY) || "";
  } catch {
    return "";
  }
};
export function markActivitySeen(now: Date = new Date()): void {
  try {
    localStorage.setItem(SEEN_KEY, now.toISOString().replace(/\.\d+Z$/, "Z"));
  } catch {
    /* a browser without storage: the dot stays until the failure is out of Recent */
  }
}

/** failed runs in Recent since ``seen`` (an ISO time; "" never) */
export const failedSince = (a: Activity | null, seen: string): ActivityRun[] =>
  (a ? a.recent : []).filter((r) => r.state === "failed" && (r.finished || "") > seen);

const lower = (s: string): string => (s ? s[0]!.toLowerCase() + s.slice(1) : s);

/** "Reading your sources · source 2 of 8" */
export const runWords = (r: ActivityRun): string => [r.title, r.words].filter(Boolean).join(" · ");

/** the incidents of a read (a refused model key; [] from a the server before them) */
export const incidentsOf = (a: Activity | null): ActivityIncident[] => (a && Array.isArray(a.incidents) ? a.incidents : []);
/** whether an incident raises the band and the top bar's red: Kranto's own only (the owner,
 * 2026-10-28: "That level of alert should be limited to issues in Kranto itself"). the server says
 * it (band); from a the server before it, by the id's class: a refused key (auth:) or Kranto's core
 * (core:). A feature's or a cub's incident (a cub stopped) is a Needs you row. */
export const isBand = (i: ActivityIncident): boolean => (typeof i.band === "boolean" ? i.band : /^(auth|core):/.test(i.id || ""));
/** the incidents the band says (Kranto's own) */
export const bandOf = (a: Activity | null): ActivityIncident[] => incidentsOf(a).filter(isBand);

/** a message that only repeats a run failure an incident already says ("ingest run failed",
 * one a run, from before the incidents): folded into the incident */
export function foldedByIncident(a: Activity | null, title: string): boolean {
  const kinds = new Set(incidentsOf(a).flatMap((i) => (i.kinds || []).map((k) => k.kind)));
  const m = /^(\S+) run failed$/.exec(title);
  return !!m && kinds.has(m[1]!);
}

/** the top bar's words for an incident: "OpenRouter key refused", "reading your sources stopped" */
export function incidentWords(i: ActivityIncident): { word: string; detail: string } {
  if (i.short) return { word: i.short, detail: "" }; // a feature's blocked states say their own
  // a provider's credit too low for the calls in flight: the key works, the calls try again
  if (i.cause === "low credit") return { word: `${i.name || "Model"} credit low`, detail: "calls try again" };
  const first = i.kinds?.[0]?.noun || "model calls";
  return { word: `${i.name || "Model"} key refused`, detail: `${first} stopped` };
}

/** the top bar's one item: Quiet with what is next, the ring and the count while something
 * runs, Paused, a red dot once when something failed since the owner last looked. What is still
 * broken outranks all of it: an incident (a refused key) or a Fix row keeps the item
 * red while it lasts, while something runs and after Activity is opened; only fixing it clears it. */
export function indicator(a: Activity | null, lanes: LaneFacts, seen: string, now: Date = new Date()): Indicator {
  const failed = failedSince(a, seen).length;
  const inc = bandOf(a)[0]; // Kranto's own only; a feature's incident is a Needs you row
  if (inc) {
    const w = incidentWords(inc);
    return { state: "failed", word: w.word, detail: w.detail, failed, title: `${inc.words} What Kranto is doing (g a)` };
  }
  const fixes = a && !(lanes.paused || a.paused) ? a.failing : [];
  if (fixes.length) {
    return { state: "failed", word: `${fixes.length} failing`, detail: lower(fixes[0]!.title), failed,
      title: `${fixes.map((f) => f.title).join(", ")}: failing until the next good run. What Kranto is doing (g a)` };
  }
  if (lanes.paused || (a && a.paused)) {
    return { state: "paused", word: "Paused", detail: null, failed,
      title: "Everything is paused: no source is read and no idea written until you resume" };
  }
  const running = a ? a.running : [];
  if (running.length || (!a && lanes.afkRunning)) {
    const n = a ? running.length : 1;
    const first = a ? runWords(running[0]!) : lanes.afkRunning === "ingest" ? ["Reading your sources", lanes.reading].filter(Boolean).join(" · ") : "working";
    return { state: "running", word: `${n} running`, detail: lower(first), failed,
      title: `${plural(n, "run")} now: ${first}. What Kranto is doing (g a)` };
  }
  const q = a?.next.find((x) => !QUIET_SKIP.has(x.kind));
  const detail = q ? `next: ${lower(q.title)} at ${nextRead(q.at, now)}` : lanes.next ? `next: reading your sources at ${nextRead(lanes.next, now)}` : null;
  return { state: failed ? "failed" : "quiet", word: failed ? `Quiet · ${failed} failed` : "Quiet", detail, failed,
    title: (failed ? `${plural(failed, "run")} failed since you last looked. ` : "Nothing is running. ") + "What Kranto is doing (g a)" };
}
const QUIET_SKIP = new Set(["telemetry", "cubs.gc", "xrecheck", "heartbeat"]);

/** a run's one meta line: feature · subject · stage · elapsed · spend · who started it */
export function runMeta(r: ActivityRun): string {
  // one fact, how long it has run (a duration changes whether the owner waits)
  // and which assistant ran it (a run an assistant started says so, ASK); model calls and dollars
  // are the run's trace and its Details
  return [r.state === "running" ? r.words || r.subject?.name : r.why || r.error || r.words || r.subject?.name,
    r.elapsed_s != null && r.state === "running" ? dur(r.elapsed_s) : null, byWords(r.trigger?.by)].filter(Boolean).join(" · ");
}

/** the recent runs with the ones that failed the same way folded into one (R6:
 * four runs refused by the same key are one row, "4 runs failed"), in their order */
export function foldSame(runs: ActivityRun[]): { x: ActivityRun; n: number }[] {
  const out: { x: ActivityRun; n: number }[] = [];
  const at = new Map<string, number>();
  for (const x of runs) {
    const why = x.state === "failed" ? x.error || x.why : null;
    const k = why ? `${x.kind}|${why}` : null;
    const i = k ? at.get(k) : undefined;
    if (i !== undefined) {
      out[i]!.n += 1;
      continue;
    }
    if (k) at.set(k, out.length);
    out.push({ x, n: 1 });
  }
  return out;
}

/** the runs of one subject (``topic:12``, ``kind:news.brief``, ``feature:toot``): a page's own; a
 * cub's page has its jobs' runs and the runs about it (its update, applied or waiting) */
export function about(a: Activity | null, subject: string): { running: ActivityRun[]; waiting: ActivityRun[]; recent: ActivityRun[]; failing: ActivityFail[] } {
  const [k, ...rest] = subject.split(":");
  const id = rest.join(":");
  const mine = (r: ActivityRun): boolean =>
    k === "kind" ? r.kind === id || r.kind.startsWith(id + ".")
      : k === "feature" ? r.feature === id || (r.subject?.kind === "cub" && String(r.subject.id) === id)
      : (!!r.subject && r.subject.kind === k && String(r.subject.id) === id) || ((k === "topic" || k === "source") && r.kind === "ingest");
  const fk = (f: ActivityFail): boolean => (k === "kind" ? f.kind === id || f.kind.startsWith(id + ".") : k === "feature" ? f.kind.startsWith(id + ".") : false);
  return a
    ? { running: a.running.filter(mine), waiting: a.waiting.filter(mine), recent: a.recent.filter(mine), failing: a.failing.filter(fk) }
    : { running: [], waiting: [], recent: [], failing: [] };
}

/** a page's one line: what runs of its subject, else what waits on you, else the last
 * failure, else the quiet form (or nothing). ``verb``: the one press; ``watch``: the trace */
export interface Line {
  state: "running" | "waiting" | "failed" | "quiet";
  words: string;
  watch: string | null;
  stop: string | null;
  verb: { word: string; href: string } | null;
}
export function lineOf(a: Activity | null, subject: string, quiet: string | null = null): Line | null {
  const m = about(a, subject);
  const r = m.running[0];
  if (r) return { state: "running", words: [r.title, r.words, r.elapsed_s != null ? dur(r.elapsed_s) : null].filter(Boolean).join(" · "), watch: r.trace ? r.trace + "?follow=1" : null, stop: r.stoppable ? r.id : null, verb: null };
  const w = m.waiting[0];
  if (w) return { state: "waiting", words: w.words || w.title, watch: null, stop: null, verb: w.needs?.href ? { word: w.needs.verb || "Review", href: "#/" + w.needs.href.replace(/^#?\/?/, "") } : null };
  const f = m.failing[0];
  // the verb opens Activity at the kind's row, as Needs you's Fix row does
  if (f) return { state: "failed", words: `${f.title}: ${f.error} · ${plural(f.tries, "try", "tries")}`, watch: f.trace, stop: null, verb: { word: f.verb, href: "#/activity?fix=" + encodeURIComponent(f.kind) } };
  const last = m.recent.find((x) => x.state === "failed");
  if (last) return { state: "failed", words: `${last.title} failed: ${last.error || "no reason was kept"}`, watch: last.trace, stop: null, verb: last.verb ? { word: last.verb, href: "#/activity" } : null };
  return quiet ? { state: "quiet", words: quiet, watch: null, stop: null, verb: null } : null;
}

/** Needs you's rows from the activity read: a Fix row a failing kind; a
 * waiting run whose press no other row already offers (``claimed``: the rows' hrefs) */
export interface ActRow {
  key: string;
  title: string;
  meta: string;
  href: string;
  verb: string;
  kind: "incident" | "fix" | "waiting";
  /** an incident the owner may put away (the server 0.6.0.dev15+: POST api/activity/dismiss) */
  dismiss?: string;
}
/** an incident's row: its sentence, the kinds it stops, Renew the key */
export function incidentRow(i: ActivityIncident): ActRow {
  return { key: "incident:" + i.id, title: i.title, meta: i.words || "",
    href: i.href, verb: i.verb || "Renew the key", kind: "incident", dismiss: i.dismiss ? i.id : undefined };
}

/** a prepared item's waiting run ("Prepared: File a Kranto issue"): the item is its own row */
export const isPreparedRun = (w: { kind?: string; title?: string }): boolean => w.kind === "verb" && /^Prepared: /.test(w.title || "");

/** which of the read's rows a page leaves out because it says them otherwise: ``band``, the
 * incidents its band says (the home); ``prepared``, the prepared items' waiting runs (a page
 * that lists the items themselves). One problem, one card. */
export interface Skip {
  band?: boolean;
  prepared?: boolean;
}
export function needsRows(a: Activity | null, claimed: Set<string>, skip: Skip = {}): ActRow[] {
  if (!a) return [];
  const norm = (h: string): string => h.replace(/^#?\/?/, "");
  const taken = new Set([...claimed].map(norm));
  const out: ActRow[] = incidentsOf(a).filter((i) => !(skip.band && isBand(i))).map(incidentRow);
  out.push(...a.failing.map((f): ActRow => ({
    key: "fix:" + f.kind, title: `${f.title} is failing`, meta: f.error || "",   // its one fact; how often and since when are Activity's and the trace's
    href: "#/activity?fix=" + encodeURIComponent(f.kind), verb: f.verb || "Run again", kind: "fix",
  })));
  for (const w of a.waiting) {
    if (skip.prepared && isPreparedRun(w)) continue;
    const h = w.needs?.href ? norm(w.needs.href) : null;
    if (h && taken.has(h)) continue;
    out.push({ key: "wait:" + w.id, title: w.words || w.title, meta: [w.subject?.name, "stopped for you"].filter(Boolean).join(" · "),
      href: h ? "#/" + h : "#/activity", verb: w.needs?.verb || "Open", kind: "waiting" });
  }
  return out;
}

/** the band's one sentence (a bold title, then at most 14 words): what stopped
 * and since when, "Reading your sources and idea cards stopped at 19:02."; the long form (what
 * raised it, the error, what clears it) is kranto_incidents' and its trace's */
export function bandWords(i: Pick<ActivityIncident, "kinds" | "since" | "words">): string {
  const nouns = (i.kinds || []).map((k) => k.noun || k.title).filter(Boolean);
  if (!nouns.length) return String(i.words || "").split(/(?<=[.!?:])\s/)[0] || "";
  const what = nouns.length > 1 ? `${nouns.slice(0, -1).join(", ")} and ${nouns[nouns.length - 1]}` : nouns[0]!;
  const d = i.since ? new Date(i.since) : null;
  const at = d && !isNaN(d.getTime()) ? ` at ${d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}` : "";
  return `${what.charAt(0).toUpperCase()}${what.slice(1)} stopped${at}.`;
}
