// Add source › Describe what to add (4.4; the server #213): a pasted list or description
// goes to the server's POST /api/sources/from-text, which resolves it in the background (one model
// call, then a test fetch of each source; the page polls the job), and comes back as one batch of
// lines in the order the text named them. The batch is drawn as one group in five sections, the
// ready ones ticked; Approve the ticked approves them in one request (POST /api/sources/approve).
// Nothing is watched until then. The text, the topic, the batch and the ticks are kept here across
// draws, so a failed call keeps what was pasted.
import type { FromTextBatch, FromTextLine } from "../../api/afk.gen";
import { afkJob } from "../../lib/job";
import { go, href } from "../../lib/router";
import { app } from "../../lib/shell.svelte";
import { FORM } from "./sources.svelte";
export type { FromTextBatch, FromTextLine } from "../../api/afk.gen";

export const FROMTEXT_API = "/api/sources/from-text";
export const APPROVE_API = "/api/sources/approve";
/** a batch again by its id (the number in fromtext:<n>) */
export const batchApi = (n: number | string): string => `${FROMTEXT_API}/${n}`;

/* the group's sections, in the issue's order: [its id, its heading, the statuses it holds] */
export const SECTIONS: [string, string, FromTextLine["status"][]][] = [
  ["ready", "Ready to approve", ["valid", "unverified"]],
  ["failed", "Could not be fetched", ["invalid"]],
  ["notfound", "Not found or not offered", ["not_found", "refused"]],
  ["account", "Needs an account", ["connect_first"]],
  ["already", "Already watching or proposed", ["already_watching", "already_proposed"]],
];
/* the sixth: what a Find these with Claude Code session sent back, its own batches' lines */
export const FOUND: [string, string] = ["found", "Found by Claude Code"];
/** the sections whose lines a session may look into */
export const FINDABLE = ["failed", "notfound"];

export interface Describe {
  text: string;
  topic: string;
  batch: FromTextBatch | null;
  /** the source ids ticked in the batch */
  ticked: number[];
  /** "Resolving 22 lines… (12 s)" while the job runs */
  waiting: string | null;
  error: string | null;
}
export const DESCRIBE = $state<Describe>({ text: "", topic: "", batch: null, ticked: [], waiting: null, error: null });

/** the lines of a section, in the text's order */
export const sectionLines = (b: FromTextBatch, id: string): FromTextLine[] => {
  const s = SECTIONS.find((x) => x[0] === id);
  return s ? b.lines.filter((l) => s[2].includes(l.status)) : [];
};
/** what is ticked when a batch arrives: every source that fetched with items, except one X bills
 * for (a person ticks those) */
export const preticked = (b: Pick<FromTextBatch, "lines">): number[] =>
  [...new Set(b.lines.filter((l) => l.status === "valid" && l.source_id != null && !l.cost).map((l) => l.source_id as number))];
/** a line's state, as a glyph: [name, colour, word] */
export function lineMark(l: FromTextLine): [string, string, string] {
  switch (l.status) {
    case "valid": return ["check", "green", "Fetched"];
    case "unverified": return ["open", "amber", "Not fetched now"];
    case "invalid": return ["x", "red", "Could not be fetched"];
    case "refused": return ["closed", "grey", "Not offered"];
    case "not_found": return ["open", "grey", "Not found"];
    case "connect_first": return ["open", "blue", "Needs an account"];
    case "already_watching": return ["check", "green", "Active"];
    default: return ["dot", "blue", "Proposed"];
  }
}
/** a line's title: the source's label, else the preset tried, else the line itself */
export const lineTitle = (l: FromTextLine): string => l.label || (l.row ? l.row.label : null) || l.from;
/** what a line says under its title: the line it came from, then why it is not ready (first, so a
 * narrow pane keeps it), the site, what the fetch found, how it was resolved */
export function lineMeta(l: FromTextLine): string {
  const from = l.label || l.row ? `from «${l.from}»` : null;
  const ok = l.status === "valid";
  const items = l.row && ok ? `${l.row.validation.items ?? 0} items, ${l.row.validation.recent ?? 0} in 30 days` : null;
  const ticking = l.status === "unverified" ? "ticking it watches it anyway; the next run checks it" : null;
  return [from, ok ? null : l.why, l.row?.site_name || null, items, costWords(l), ok ? l.why : null, ticking].filter(Boolean).join(" · ");
}
const usd = (n: number): string => "$" + n.toFixed(2);
/** an X line's cost before it is approved: a run, a month at the configured
 * runs, and what checking it read; null for a line X does not bill */
export function costWords(l: FromTextLine): string | null {
  const c = l.cost;
  if (!c) return null;
  return `X bills about ${usd(c.run)} a run, up to about ${usd(c.month)} a month`
    + (c.check ? `; the check read 10 posts (${usd(c.check)})` : "; not read before you approve it");
}
/** the catalog kind to correct a line with (Try as): its preset and the fields tried */
export const canTry = (l: FromTextLine): boolean => !!l.preset && ["invalid", "unverified"].includes(l.status);

/** Resolve: the text to the server; the batch replaces the last one, its ready lines ticked */
export function resolveText(btn: HTMLElement | null): Promise<void> {
  const L = app();
  const text = DESCRIBE.text.trim();
  if (!L || !text) return Promise.resolve();
  const lines = text.split("\n").filter((x) => x.trim()).length;
  const say = (s: number) => (DESCRIBE.waiting = `Resolving ${lines} ${lines === 1 ? "line" : "lines"}… each source is fetched before you see it, about a minute (${s} s)`);
  DESCRIBE.error = null;
  say(0);
  return L.act(btn, async () => {
    try {
      const r = await afkJob(await L.api(FROMTEXT_API, { text, topic: DESCRIBE.topic ? Number(DESCRIBE.topic) : null }), FROMTEXT_API, say);
      L.afkDrop();
      return r;
    } catch (e) {
      DESCRIBE.error = (e as Error).message;
      throw e;
    }
  }, (r) => {
    const b = r as FromTextBatch;
    DESCRIBE.batch = b;
    DESCRIBE.ticked = preticked(b);
    DESCRIBE.text = "";
    go("settings/sources/new", { ...(b.topic != null ? { topic: String(b.topic) } : {}), batch: String(b.call_id) });
    L.say(b.message);
  }).finally(() => (DESCRIBE.waiting = null));
}

/** Approve the ticked: one request; then the topic's Sources (or Settings › Sources). found: the
 * lines Claude Code sent back for this batch, ticked with the rest */
export function approveTicked(btn: HTMLElement | null, b: FromTextBatch, topicName: string | null, found: FromTextLine[] = []): Promise<void> {
  const L = app();
  const ids = DESCRIBE.ticked.filter((id) => [...b.lines, ...found].some((l) => l.source_id === id));
  if (!L || !ids.length) return Promise.resolve();
  return L.act(btn, async () => {
    const r = await L.api(APPROVE_API, { ids, topic: b.topic });
    L.afkStale("/api/today", "/api/sources", "/api/topics");
    L.afkDrop();
    return r;
  }, (r) => {
    const res = r as { approved: number[]; skipped: { id: number; why: string }[] };
    const n = res.approved.length;
    DESCRIBE.batch = null;
    DESCRIBE.ticked = [];
    go(b.topic != null ? `topics/${b.topic}/sources` : "settings");
    L.toast(`Watching ${n} ${n === 1 ? "source" : "sources"}${topicName ? " for " + topicName : ""}. Their first fetch is the next ingest run.`
      + (res.skipped.length ? ` ${res.skipped.length} could not be approved: ${res.skipped[0]!.why}.` : ""));
  });
}

/** Try as: the catalog's form for the line's kind (its address), with the fields tried (tryAs,
 * on the press), to correct one */
export const tryHref = (l: FromTextLine, topic: number | null): string => href("settings/sources/new", { topic, sel: "epreset:" + l.preset });
export function tryAs(l: FromTextLine, topic: number | null): void {
  FORM.f = { key: "preset:" + l.preset, fields: { ...l.fields }, topic: topic != null ? String(topic) : "", preview: null, error: null };
}
