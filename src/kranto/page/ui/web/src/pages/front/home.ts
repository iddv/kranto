// The home (mock D's #home): what Home.svelte draws, worked out from the reads the
// doors already make (the server's status, /api/today, /api/ideas, the review queue) and
// the features' manifests (GET /api/features: each tile resolved, each row read named), under the
// arrangement the person chose (features/shell.ts). Plain data, so the tests read it without a
// page. A row here never acts: its one verb opens the place where the press is, so the home
// holds no copy of a page's buttons.
import type { Activity } from "../../api/types.gen";
import { foldedByIncident, incidentsOf, needsRows, type Skip } from "../../lib/activity";
import { buttonOf, gone, lineOf, type Prepared } from "../../lib/prepared";
export { foldedByIncident };
import type { Today } from "../../api/afk.gen";
import { ago, dt, plural } from "../../lib/format";
import { href } from "../../lib/router";
import { CARD_VERBS } from "../../lib/app/data";
import { cubsOf, featurePath, modeWord, trustWord, type FeatureRow, type Features } from "../../features/index";
import type { AskRef } from "../../features/ask";
import { cubHref } from "../../features/cub";
import { read, type Read } from "../../lib/reads.svelte";
import type { HomeAnswer } from "../../features/home";
import { placeOf, type Arrangement } from "../../features/shell";
import { dispatchWaiting, messageListed, projectProposed, updateOffer, waitingCards, type Host } from "./needs";
import { reviewMinutes } from "../review/review";
import { POST_API, unsendable, type Post } from "../post/post";

/** one row of Needs you or New today */
export interface HomeRow {
  key: string;
  title: string;
  meta: string;
  href: string;
  /** the one verb, a link to where the press is ("Open" on New) */
  verb: string;
  age: string | null;
  /** "core" or a cub's id; a cub's row carries its tags */
  from: string;
  tags: { word: string; tone: string }[];
  glyph: string;
  tone: string;
  /** the state in a word, drawn before the title ("held", "waits";) */
  word?: string;
  /** when it came (seconds), for the one thing's rule (needs.ts nextOf) */
  at?: number | null;
  /** what it asks of the owner, for the one thing: approve, fix or decide (none: not a candidate) */
  want?: "approve" | "fix" | "decision";
  /** an incident the owner may put away: its id (Dismiss) */
  dismiss?: string;
  /** a prepared item: its button opens its dialog, never a link */
  prepared?: Prepared;
  /** what a cub asks (SEND): its button opens the ask's dialog, never a link */
  ask?: AskRef;
}
/** a cub's row as its read answers it (the server's TodayRow contract) */
export interface CubRow {
  id: number | string;
  title: string;
  meta?: string;
  at?: string;
  open?: string;
  ticket?: number | null;
  mode?: string;
  /** the row's verb when it is not Open (a word, never an action) */
  verb?: string;
  /** an ask the core built (the server 0.6.0.dev16+, SEND): its draft offered again, and its line */
  again?: number | null;
  ask?: { line: string; said: string | null; open: boolean };
}

const WORDS = ["Nothing", "One thing", "Two things", "Three things", "Four things", "Five things", "Six things", "Seven things", "Eight things", "Nine things", "Ten things"];


/** the core's rows of Needs you, in its order: an update, the cards waiting, the review
 * queue, sources, messages; every one a link to its place */
export function coreNeeds(t: Today | null, host: Host | null, review: number): HomeRow[] {
  const out: HomeRow[] = [];
  const row = (x: Omit<HomeRow, "from" | "tags" | "age"> & { age?: string | null }) => out.push({ from: "core", tags: [], age: null, ...x });
  const upd = host?.update || null, offer = updateOffer(upd);
  if (upd && offer) row({ key: "update", title: offer === "bad" ? (upd.broke && upd.state === "rolled_back" ? `${upd.to} broke on your data and was rolled back` : `Update to ${upd.to} was not finished`) : `Kranto ${upd.available} is ready`,
    meta: offer === "bad" ? "nothing in your data was undone" : "installs when you restart", href: "#/settings/updates", verb: offer === "bad" ? "Open" : "Update", glyph: "↻",
    tone: offer === "bad" ? "red" : "blue", word: offer === "bad" ? "rolled back" : "update" });
  const cards = waitingCards(host).length + dispatchWaiting(host).length;
  if (cards) row({ key: "cards", title: `${plural(cards, "idea card")} wait${cards === 1 ? "s" : ""} for ${CARD_VERBS}`, meta: "", href: href("ideas", { status: "waiting" }), verb: "Open", glyph: "◆", tone: "violet", word: "ideas" });
  if (review) row({ key: "review", title: `${plural(review, "card")} wait${review === 1 ? "s" : ""} for your grade`, meta: `about ${plural(reviewMinutes(review), "minute")}`, href: "#/review", verb: "Review", glyph: "◆", tone: "violet", word: "review" });
  for (const x of t ? t.topics.filter((y) => y.proposed) : []) row({ key: "p" + x.id, title: `${plural(x.proposed, "proposed source")} for ${x.name}`, meta: "from the scout",
    href: href(`topics/${x.id}/sources`), verb: "Review", glyph: "◉", tone: "amber", word: "proposed" });
  // the project topics' proposals wait on you too: one quiet row for all of them (the owner's O-3)
  const pp = projectProposed(t);
  if (pp.n) row({ key: "pproj", title: `${plural(pp.n, "proposed source")} for ${plural(pp.topics, "project topic")}`, meta: "for topics you watch for a project",
    href: href("watch/sources", { status: "proposed" }), verb: "Review", glyph: "◉", tone: "amber", word: "proposed" });
  const failing = t ? (t.sources_failing || []).length : 0;
  if (failing) row({ key: "failing", title: `${plural(failing, "source")} failing run after run`, meta: "fix or remove", href: "#/settings/sources", verb: "Fix", glyph: "✕", tone: "red", word: "failing", want: "fix" });
  // a source your downvotes recommend removing (the source rule): Remove or Keep on Needs you
  for (const r of t ? t.sources_to_remove || [] : []) row({ key: "sr" + r.id, title: `Remove ${r.label}?`, meta: `${r.down} of its ${r.down + r.up} graded posts were not useful`,
    href: "#/needs", verb: "Decide", glyph: "◉", tone: "amber", word: "your grades", want: "decision" });
  const msgs = t ? t.messages.filter(messageListed(null)).length : 0;
  if (msgs) row({ key: "msgs", title: `${plural(msgs, "message")} from Kranto`, meta: "", href: "#/needs", verb: "Read", glyph: "✉", tone: "blue", word: "messages" });
  return out;
}

/** what the activity read adds to Needs you: one Fix row a kind
 * failing twice in a row or for two days (it opens Activity, where its Run again is), and a run
 * that stopped for you whose press no other row offers already (``claimed``: those rows) */
export function activityRows(a: Activity | null, claimed: HomeRow[], skip: Skip = {}): HomeRow[] {
  return needsRows(a, new Set(claimed.map((r) => r.href)), skip).map((x) => {
    const bad = x.kind === "fix" || x.kind === "incident";
    return { key: x.key, title: x.title, meta: x.meta, href: x.href, verb: x.verb, age: null, from: "core", tags: [], glyph: bad ? "✕" : "▣",
      tone: bad ? "red" : "amber", word: bad ? "failing" : "stopped", want: bad ? ("fix" as const) : undefined, dismiss: x.dismiss };
  });
}

/** the open prepared items as rows: who prepared what, its age, the action's own button (its
 * dialog reads it back; ``prepared`` carries the item for it) */
export function preparedRows(items: Prepared[]): HomeRow[] {
  return items.map((p) => ({ key: "prep:" + p.uuid, title: lineOf(p), meta: `prepared ${p.by_words}`, href: p.page || "#/needs",
    verb: buttonOf(p), age: p.created_at ? ago(dt(p.created_at)) : null, from: "core", tags: [], glyph: "✦", tone: "violet", prepared: p,
    word: "prepared", at: dt(p.created_at), want: gone(p) ? undefined : ("approve" as const) }));
}

/** a row that says what is broken: a refused key (an incident) or a kind failing (a Fix row) */
export const isFix = (r: HomeRow): boolean => r.key.startsWith("incident:") || r.key.startsWith("fix:");

/** the Needs you rows in the order the owner reads them: what is broken first (the
 * incidents, then the Fix rows), then an update, the cubs' asks, the runs that stopped for you,
 * the rest. */
export function orderNeeds(core: HomeRow[], acts: HomeRow[], cubs: HomeRow[]): HomeRow[] {
  const first = core.filter((r) => r.key === "update");
  const fixes = acts.filter(isFix);
  return uniqueRows([...fixes, ...first, ...cubs, ...acts.filter((r) => !fixes.includes(r)), ...core.filter((r) => !first.includes(r))]);
}

/** the rows with keys that are unique, whatever the reads hold: a second row of the same key is
 * keyed by its place (a project with two asks, a cub that answers one id twice). A duplicate key
 * would stop the page from drawing at all. */
export function uniqueRows(rows: HomeRow[]): HomeRow[] {
  const seen = new Set<string>();
  return rows.map((r, i) => {
    const key = seen.has(r.key) ? `${r.key}~${i}` : r.key;
    seen.add(key);
    return key === r.key ? r : { ...r, key };
  });
}

/** a cub's row's cub, by name: its tag's first part ("Newsletter · yours"; an older "cub · …") */
export const cubOf = (r: HomeRow): string => String(r.tags[0]?.word || "").replace(/^cub · /, "").split(" · ")[0] || r.from;

/** a cub's rows of one group, from its read, under its allowance and tagged with its trust and mode */
export function cubRows(f: FeatureRow, rows: CubRow[], group: "needs_you" | "new"): HomeRow[] {
  const decl = (f.manifest.ui.today_rows || []).find((r) => r.group === group);
  if (!decl) return [];
  const confirm = decl.primary !== "open" && decl.primary !== "" && (decl.primary === "confirm" || (f.manifest.requests || []).includes(decl.primary));
  // a row without its own link opens its object's sheet on the cub's page (sel=o<id>), where its
  // Confirm is: a cub's id alone is no route (#/newsletter was "There is no page")
  const post = group === "needs_you" && rows.some((r) => r.ask) ? read<Post>(POST_API, 60000).data : null;
  return rows.map((r) => {
    // a draft with no account connected cannot be sent: its row opens the draft's page
    const nope = group === "needs_you" && r.ask ? unsendable(post, r.ticket) : null;
    if (nope) {
      return { key: `${f.id}:${r.id}`, title: r.title, meta: r.meta || "", href: href(`post/d/${nope.id}`), from: f.id, verb: "Open",
        age: r.at ? ago(dt(r.at)) : null, at: dt(r.at), word: "waits", want: "approve" as const, tags: [{ word: f.title, tone: f.trust }], glyph: "", tone: "violet" };
    }
    // what the cub asks, as the server's core built it (SEND): one line, its title and where it
    // stands, and the action's own button, which opens its dialog
    const ask = group === "needs_you" && r.ask ? { cub: f.id, ticket: r.ticket ?? null, again: r.again ?? null } : undefined;
    return {
      key: `${f.id}:${r.id}`, title: r.title, meta: r.meta || "", href: r.open ? "#/" + r.open : cubHref(f.id, { sel: "o" + String(r.id) }), from: f.id,
      // a row may name its verb ("Review", UIBUGS B28); an ask its own ("Send")
      verb: group === "new" ? "Open" : ask ? r.verb || "Approve" : confirm ? "Confirm" : r.verb || "Open", age: r.at ? ago(dt(r.at)) : null, at: dt(r.at), word: group === "new" ? "new" : "waits",
      want: group === "needs_you" ? ("approve" as const) : undefined,
      tags: ask ? [{ word: f.title, tone: f.trust }] : [{ word: `${f.title} · ${trustWord(f.trust)}`, tone: f.trust }, ...(f.mode && f.mode !== "live" ? [{ word: modeWord(r.mode || f.mode), tone: "mode" }] : [])],
      glyph: "", tone: "violet", ...(ask ? { ask } : {}),
    };
  });
}

/** a cub's rows of a group, read from its own read (its manifest names it) */
export function cubReadRows(x: FeatureRow, group: "needs_you" | "new"): HomeRow[] {
  const decl = (x.manifest.ui.today_rows || []).find((r) => r.group === group);
  if (!decl) return [];
  const c = read<{ rows: CubRow[] }>(featurePath(x.id, decl.read), 60000).data;
  return c && Array.isArray(c.rows) ? cubRows(x, c.rows, group) : [];
}

/** a cub's rows of a group from the home's one read (GET /api/home,); while it is
 * on its way, none; when the server has no such read (an older one), the cub's own read as before */
export function homeRows(h: Read<HomeAnswer> | null, x: FeatureRow, group: "needs_you" | "new"): HomeRow[] {
  if (!(x.manifest.ui.today_rows || []).some((r) => r.group === group)) return [];
  if (h?.data) {
    const s = h.data.rows?.[group]?.[x.id];
    return s && Array.isArray(s.data) ? cubRows(x, s.data as CubRow[], group) : [];
  }
  return h?.error ? cubReadRows(x, group) : [];
}

/** which cubs may add rows to a group: on, not hidden, allowed (Needs you by trust, D6) */
export function rowCubs(f: Features | null, a: Arrangement | null, group: "needs_you" | "new"): FeatureRow[] {
  return cubsOf(f).filter((x) => {
    if (!x.enabled) return false;
    const p = placeOf(a, x.id, x.trust);
    return !p.hidden && (group === "needs_you" ? p.needs_you : p.new) && (x.manifest.ui.today_rows || []).some((r) => r.group === group);
  });
}

/** the sentence from counts (counts, never a list) */
export function sentence(needs: number, cubNeeds: number, newKept: number, briefs: number): string {
  const lead = needs ? `${needs <= 10 ? WORDS[needs] : `${needs} things`} need${needs === 1 ? "s" : ""} you.` : "Nothing needs you.";
  const parts = [briefs ? `${briefs === 1 ? "A brief is" : plural(briefs, "brief") + " are"} ready` : null,
    cubNeeds ? `${cubNeeds === 1 ? "a cub" : plural(cubNeeds, "cub")} asked for you` : null,
    newKept ? `Kranto kept ${newKept.toLocaleString("en-GB")} new since your last visit` : null].filter(Boolean) as string[];
  if (!parts.length) return lead;
  const tail = parts.length > 1 ? parts.slice(0, -1).join(", ") + " and " + parts[parts.length - 1] : parts[0]!;
  return `${lead} ${tail[0]!.toUpperCase()}${tail.slice(1)}.`;
}

/** "Sunday 19 October" */
/** the one thing's muted line (after "Next ·"): what it is and who raised it, and when */
export function nextLine(r: HomeRow): string {
  const when = r.age ? (r.age === "now" ? ", just now" : `, ${r.age} ago`) : "";
  if (r.prepared) return `prepared ${r.prepared.by_words || "by an assistant"}${when}`;
  if (r.from !== "core") return `${cubOf(r)} asks${when}`;
  if (r.want === "decision") return `it asks you${when}`;
  return (r.word || "it waits") + when;
}

export const dayTitle = (now: Date = new Date()): string => now.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });

// -- the home of open-source wave 2: its words, from GET /api/home --------------

const dayMonth = (d: Date): string => d.toLocaleDateString("en-GB", { day: "numeric", month: "long" });
const hhmm = (d: Date): string => d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
const sameDay = (a: Date, b: Date): boolean => a.toDateString() === b.toDateString();

/** "2 hours ago", "12 minutes ago", "just now", "yesterday", "3 days ago" */
export function agoWords(at: string | null | undefined, now: number = Date.now()): string {
  const t = at ? Date.parse(at) : NaN;
  if (Number.isNaN(t)) return "";
  const m = Math.round((now - t) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return plural(m, "minute") + " ago";
  if (m < 1440) return plural(Math.round(m / 60), "hour") + " ago";
  return m < 2880 ? "yesterday" : plural(Math.round(m / 1440), "day") + " ago";
}

/** when a next run comes, in a sentence: "tonight at 22:00", "today at 09:00", "tomorrow at
 * 07:00", "on Friday at 07:00", "on 20 November at 07:00" */
export function nextWords(at: string, now: Date = new Date()): string {
  const d = new Date(at);
  if (Number.isNaN(d.getTime())) return "";
  if (sameDay(d, now)) return `${d.getHours() >= 18 ? "tonight" : "today"} at ${hhmm(d)}`;
  const tomorrow = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
  if (sameDay(d, tomorrow)) return `tomorrow at ${hhmm(d)}`;
  const week = (d.getTime() - now.getTime()) / 86400000 < 6;
  return `on ${week ? d.toLocaleDateString("en-GB", { weekday: "long" }) : dayMonth(d)} at ${hhmm(d)}`;
}

/** the quiet line: "5 topics and 153 sources, read 2 hours ago. Next: ideas tonight at 22:00." */
export function quietLine(q: { topics?: number; sources?: number; read_at?: string | null; next?: { words: string; at: string } | null }, now: Date = new Date()): string {
  if (q.topics == null || q.sources == null) return "";
  const read = q.read_at ? `, read ${agoWords(q.read_at, now.getTime())}` : ", not read yet";
  const head = `${plural(q.topics, "topic")} and ${plural(q.sources, "source")}${read}.`;
  return q.next ? `${head} Next: ${q.next.words} ${nextWords(q.next.at, now)}.` : head;
}

/** where "new" counts from, in words: "since Monday" this week, "since 2 November" before, and
 * "in the last day" when it is the last 24 hours (no visit yet) */
export function sinceWords(since: string | null | undefined, now: Date = new Date()): string {
  const d = since ? new Date(since) : null;
  if (!d || Number.isNaN(d.getTime())) return "in the last day";
  if (sameDay(d, now)) return "since this morning";
  const days = (now.getTime() - d.getTime()) / 86400000;
  return days < 6 ? `since ${d.toLocaleDateString("en-GB", { weekday: "long" })}` : `since ${dayMonth(d)}`;
}

/** the absence's span: "2 to 11 November", "28 October to 11 November" */
export function awaySpan(since: string, now: Date = new Date()): string {
  const d = new Date(since);
  if (Number.isNaN(d.getTime())) return "";
  return d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear() ? `${d.getDate()} to ${dayMonth(now)}` : `${dayMonth(d)} to ${dayMonth(now)}`;
}

/** under the five, as links: "Everything since 2 November: " then "10 ideas" (Ideas since then)
 * and "9 briefs" (News › Earlier): one link said both and opened Ideas alone */
export function everythingParts(a: { since: string; ideas: number; briefs: number }): { head: string; ideas: string | null; briefs: string | null } {
  const d = new Date(a.since);
  const ideas = a.ideas ? plural(a.ideas, "idea") : null, briefs = a.briefs ? plural(a.briefs, "brief") : null;
  return { head: `Everything since ${Number.isNaN(d.getTime()) ? "you left" : dayMonth(d)}${ideas || briefs ? ": " : ""}`, ideas, briefs };
}
/** under the five: "Everything since 2 November: 10 ideas and 9 briefs" */
export function everythingLine(a: { since: string; ideas: number; briefs: number }): string {
  const parts = [a.ideas ? plural(a.ideas, "idea") : null, a.briefs ? plural(a.briefs, "brief") : null].filter(Boolean);
  const d = new Date(a.since);
  return `Everything since ${Number.isNaN(d.getTime()) ? "you left" : dayMonth(d)}${parts.length ? ": " + parts.join(" and ") : ""}`;
}

/** a card's sheet on Ideas, and a brief's item's page on News */
export const cardHref = (id: number): string => href("ideas/card:" + id);
export const itemHref = (brief: number, n: number): string => href(`news/i/${brief}/${n}`);

/** "Robotics, written at 07:36" (today's brief's fact) */
export const briefFact = (topic: string, at: string): string => {
  const d = new Date(at);
  return Number.isNaN(d.getTime()) ? topic : `${topic}, written at ${hhmm(d)}`;
};
