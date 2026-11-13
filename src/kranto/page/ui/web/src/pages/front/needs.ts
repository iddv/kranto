// Needs you, the inbox as one list (WORKSPACE.md 8, W2;): the types and the helpers
// of the list and its pane. A row and its one press for each of: a release on offer, what an
// assistant's session proposes, idea cards waiting, dispatches, sources failing run after run, the
// scout's proposed sources, messages since the last visit, the review queue. Backed by the server's
// /api/today and /api/ideas; opening it never moves the last-visit marker (Mark all seen does).
import type { Message, Status, Today, TodayTopic, UpdateSummary } from "../../api/afk.gen";
import { dt } from "../../lib/format";
import { peek, read } from "../../lib/reads.svelte";
import { ACT_PATH, foldedByIncident, needsRows } from "../../lib/activity";
import type { Activity } from "../../api/types.gen";
import { href } from "../../lib/router";
import { app } from "../../lib/shell.svelte";
import { cardIdea, type Idea } from "../ideas/ideas";
import { cardIdeas } from "../ideas/cards";
import { REVIEW_API, type Queue } from "../review/review";
import { UPD_BUSY } from "../settings/updates";
import { TODAY_API } from "../topics/topics";
import { candidateRead, promoteRow } from "./promote";
import type { Listing, Session } from "../../term/api";

export { TODAY_API };
export type { Message, Today, TodayTopic };

/** the top N of a busy topic's new rows (CLICKS-v4.md, S03): read less on a heavy day */
export const TOP_NEW = 20;
/** a topic's new rows on its Evidence, by signal since the last visit */
export const newHref = (x: Pick<TodayTopic, "id">, q: Record<string, string | number> = {}): string =>
  href(`topics/${x.id}/evidence`, { since: "last", sort: "signal", ...q });

/** the idea cards waiting for you, the newest first (Later puts one off): the cards Ideas lists as
 * Waiting (the server's own state: one count on both pages); none without the server */
export const waitingCards = (host: unknown = app()?.host()): Idea[] => {
  const ci = host ? cardIdeas() : null;
  return ci ? ci.list.filter((x) => (x.state || "waiting") === "waiting").map(cardIdea).sort((a, b) => (b.created || 0) - (a.created || 0)) : [];
};
/** the owner's Parallax dispatches waiting (one card per pitch, the pitch verbatim): their own
 * read, as Ideas' ?source=dispatch */
export const DISPATCH_API = "/api/ideas?origin=dispatch&embedding=ref";
export function dispatchWaiting(host: unknown): Idea[] {
  if (!host) return [];
  const raw = read<{ ideas?: Record<string, unknown>[] }>(DISPATCH_API, 60000).data?.ideas || [];
  return raw.filter((x) => (String(x.state || "waiting")) === "waiting")
    .map((x) => ({ id: String(x.number ?? x.id), title: String(x.title || ""), created: Date.parse(String(x.created_at || "")) / 1000 || 0 }) as Idea);
}
/** the waiting dispatch cards, when any arrived since the last visit: one row, not a row each */
export function dispatchNew(host: unknown, t: Pick<Today, "since"> | null): Idea[] {
  const xs = dispatchWaiting(host), since = t && t.since ? dt(t.since) || 0 : 0;
  return xs.some((i) => (i.created || 0) > since) ? xs : [];
}

/** the console's and Open in Claude Code's sessions (api/term), read at most every 15 s */
export const TERM_API = "api/term";
export const termRead = () => read<Listing>(TERM_API, 15000);
/** D7: a session whose proposals wait for your Confirm, one Needs you row each (the cards
 * themselves are in its panel, above the terminal) */
export interface TermWait { s: Session; n: number; first: string }
export function termWaits(l: Listing | null | undefined): TermWait[] {
  return (l?.sessions || []).map((s) => {
    const ps = (s.proposals || []).filter((p) => p.status === "proposed");
    return { s, n: ps.length, first: ps[0]?.title || "" };
  }).filter((x) => x.n > 0);
}

/** Updates' Needs you row: an update was rolled back (or not finished), or one is on offer */
export function updateOffer(u: UpdateSummary | null | undefined): "bad" | "offer" | null {
  if (!u || UPD_BUSY[u.state]) return null;
  if (u.state === "rolled_back" || u.state === "failed") return "bad";
  return u.available ? "offer" : null;
}

/** a message's mark: an alarm red, a strike blue, a heartbeat grey */
export const msgMark = (m: Pick<Message, "kind">): [string, string, string] =>
  m.kind === "alarm" ? ["warn", "red", "Alarm"] : m.kind === "strike" ? ["check", "blue", "Strike"] : ["dot", "grey", m.kind[0]!.toUpperCase() + m.kind.slice(1)];

/** the server's status (/api/status) as Needs you reads it: its topics, its sources, its
 * observations, its runs and the update on offer */
export type Host = Pick<Status, "topics" | "sources" | "observations" | "runs" | "update"> & Partial<Pick<Status, "ingest_progress">>;
/** /api/today, read once a minute (the doors' counts and the status bar read it too) */
export const todayRead = (host: unknown) => (host ? read<Today>(TODAY_API, 60000) : null);
/** the review queue's size: the doors' count and Needs you's row */
export function reviewCount(host: unknown): number {
  if (!host) return 0;
  // never a build: a build is not graded, whatever an older the server sends
  return read<Queue>(REVIEW_API, 60000).data?.items.filter((x) => x.target !== "build").length || 0;
}
/** the rows of Needs you, the idea cards each counted */
export function todayCount(host: Host | null): number {
  const t = todayRead(host)?.data || null;
  return waitingCards(host).length + termWaits(termRead().data).length
    + (dispatchNew(host, t).length ? 1 : 0)
    + (updateOffer(host?.update) ? 1 : 0) + (promoteRow(candidateRead(host))?.counts ? 1 : 0)
    + (t ? t.topics.filter((x) => x.proposed).length + messagesShown(t) + (t.sources_failing || []).length + (t.sources_to_remove || []).length : 0) + (reviewCount(host) ? 1 : 0)
    + (projectProposed(t).n ? 1 : 0);
}
/** the messages Needs you lists: those an incident folds are not, nor a refused
 * key's alarm (auth:…), which its incident says while it lasts */
export const messageListed = (act: Activity | null) => (m: Today["messages"][number]): boolean =>
  !foldedByIncident(act, m.title) && !String(m.dedup_key || "").startsWith("auth:");
export function messagesShown(t: Today | null, act: Activity | null = peek<Activity>(ACT_PATH)?.data ?? null): number {
  return t ? t.messages.filter(messageListed(act)).length : 0;
}
/** the rows the activity read adds to Needs you: incidents, Fix rows, runs stopped for you whose
 * press no cub row offers (``claimed``: those rows' hrefs) */
export function actCount(act: Activity | null, claimed: string[] = []): number {
  // Kranto's own incident is the band, not a thing that waits (one card per problem)
  return needsRows(act, new Set(claimed), { band: true }).length;
}
/** the project topics' proposals (the owner's O-3): one row of Needs you for all of them */
export function projectProposed(t: Today | null): { n: number; topics: number } {
  const xs = t ? (t.project_topics || []).filter((x) => x.proposed) : [];
  return { n: xs.reduce((a, x) => a + (x.proposed || 0), 0), topics: xs.length };
}
/** the idea cards waiting are one row of Needs you ("5 idea cards wait for Later or Pass": a
 * card's verbs are the Ideas page's) */
export const cardsRow = (n: number): number => (n ? 1 : 0);
/** Needs you's count: the rows it draws (todayCount's, with the idea cards as one row, and the
 * cubs' asks). The one number the home's sentence, its "N of M" and "and K more", Needs you's
 * head and its groups all say (the home said 36, Needs you 61) */
export function needsCount(host: Host | null, cubs: number, claimed: string[] = [],
  act: Activity | null = peek<Activity>(ACT_PATH)?.data ?? null): number {
  const cards = waitingCards(host).length;
  return todayCount(host) - cards + cardsRow(cards) + cubs + actCount(act, claimed);
}

/** what a row asks of the owner, for the one thing */
export type Want = "approve" | "fix" | "decision";
/** a row that may be the one thing: what it asks and when it came (seconds; null: unknown) */
export interface NextCand { want: Want; at: number | null; key: string }

/** The one thing on Needs you and the home (the owner's D-1), by rule, never by
 * a model: the newest of Approve (an assistant's prepared item, a cub's ask: one click finishes
 * it), else the oldest of Fix, else the first of Decide, else nothing. Kranto's own trouble is the
 * band, never a candidate: the caller leaves it out. On a tie the first listed wins; a row of
 * unknown age is the oldest Approve and the newest Fix. */
export function nextOf<T extends NextCand>(xs: readonly T[]): T | null {
  const of = (a: Want) => xs.filter((x) => x.want === a);
  const approve = of("approve");
  if (approve.length) return approve.reduce((m, x) => ((x.at ?? -Infinity) > (m.at ?? -Infinity) ? x : m));
  const fix = of("fix");
  if (fix.length) return fix.reduce((m, x) => ((x.at ?? Infinity) < (m.at ?? Infinity) ? x : m));
  return of("decision")[0] || null;
}
