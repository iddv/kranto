// Ideas (WORKSPACE.md 1.5, 2.2; W4): the types and the pure helpers of the list, a row, a topic's
// card row and the card's sheet. An idea is a server card; its topics, theme, signals
// and evidence come from the server's /api/ideas (cardIdeas, shared with Needs you and a topic's
// pages).
import type { IdeaRank } from "../../api/afk.gen";

/** a card as the sheet reads it (the server's /api/ideas row) and what a dispatch card adds */
export type IdeaCard = {
  number: number | null;
  score: number | null;
  grade: string | null;
  status: string | null;
  thesis: string | null;
  citations?: unknown[];
  topics?: unknown[];
  evidence: unknown[];
  [key: string]: unknown;
} & {
  origin?: string | null;
  pitch_kind?: string | null;
  pitch_label?: string | null;
  pitch_text?: string | null;
  dispatch?: { dispatch_id?: string; title?: string; date?: string; url?: string } | null;
  prediction?: { statement?: string; by?: string } | null;
  lineages?: { name?: string | null }[];
  who?: string | null;
  pattern?: string | null;
  where_now?: string | null;
  cheapest_test?: string | null;
  risks?: string | null;
  // the card v1 (absent on older cards)
  insight?: string | null;
  existing?: { n?: number; name?: string; covers?: string }[] | null;
  gap?: string | null;
  moment?: string | null;
  mechanism?: string | null;
  // live search's prior art (5; absent on older cards)
  prior_art?: PriorArt | null;
};
/** a card's prior-art search (the server ideate/cards.py): when, with which backends, the dated
 * results, what the card says already exists; `live` false with the "no live search" sentence */
export interface PriorArt {
  live?: boolean;
  searched_at?: string | null;
  query?: string | null;
  backends?: string[];
  note?: string | null;
  results?: number;
  hits?: { label?: string; url?: string; title?: string; date?: string | null }[];
  existing?: { label?: string; url?: string; title?: string; date?: string | null; what?: string | null }[];
}
/** the card's prior-art line: "searched 2026-10-17 with Exa · 10 results", or the sentence */
export function priorArtLine(p: PriorArt | null | undefined): string | null {
  if (!p) return null;
  if (!p.live) return p.note || "no live search: results are from model memory and may be stale";
  const n = p.results || 0;
  return `searched ${(p.searched_at || "").slice(0, 10)} with ${(p.backends || []).join(", ") || "live search"} · ${n} ${n === 1 ? "result" : "results"}`;
}
/** one idea card as the sheet reads it (cardIdea): its number is its id; open while it waits
 * (Waiting or Later), else its state */
export interface Idea {
  id: string;
  status: string;
  state: string | null;
  title: string;
  source: string;
  text: string;
  reason: string | null;
  created: number | null;
  updated: number | null;
  card: IdeaCard | null;
  later_until?: number | null;
  /** the News brief item it came from (brief:<id>:<n>, CON L8) */
  ref?: string | null;
}
/** a cited observation of a card */
export interface Cited {
  observation_id?: number | null;
  claim?: string | null;
  summary?: string | null;
  source?: string | null;
  url?: string | null;
  observed_at?: string | null;
}
/** a signal the server sends with a card */
export interface Signal {
  agrees?: boolean;
  line?: string | null;
  detail?: string | null;
}
/** one of the server's cards as the old module reads /api/ideas (cardIdeas; Topics' TopicCard) */
export interface CardX {
  number: number;
  title: string;
  status?: string | null;
  score?: number | null;
  grade?: unknown;
  topics: { id?: number | null; name: string; share?: number | null }[] | null;
  cited?: number;
  signals?: Record<string, Signal | unknown> | null;
  waiting?: boolean;
  theme?: { name: string } | null;
  /** the card's theme lineage (the server's ``ideas.lineage_id``): what ties it to a theme */
  lineage?: string | null;
  origin?: string | null;
  evidence?: Cited[];
  share?: number;
  /** where it ranks and why (the server's rank, taste, no model): its place among the
   * shown cards, the one line a row shows ("" when none), and the graded items it rests on */
  rank?: IdeaRank | null;
  /** live search's prior art, and the novelty claims removed for want of a dated result */
  prior_art?: PriorArt | null;
  novelty_dropped?: { field: string; sentence: string; reason: string }[];
  /** where it sits on Ideas (the server's ``state``, H1): waiting, later, posted, passed; and
   * when a Later ends (ISO), else null */
  state?: CardState;
  later_until?: string | null;
  /** the card as the server sent it: its text, outcomes and the rest, for the sheet (cardIdea) */
  raw?: Record<string, unknown>;
}
/** where a card sits on Ideas (the server ideas_api.card_state) */
export type CardState = "waiting" | "later" | "posted" | "passed";
/** "ranked up: like 2 cards you upvoted": the card's rank line, null when it has none (or when the
 * owner's own grade says it: the row's ▲ ▼ show that) */
export function rankLine(x: Pick<CardX, "rank"> | null | undefined): string | null {
  const l = x?.rank?.line || "";
  return l && !l.startsWith("you graded") ? l : null;
}
/** the date a part was graded, as the owner reads it: "11 Oct" */
const graded = (iso: string): string => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
/** the sheet's sentence for a card's rank: "Ranked up: like #111 Persistent
 * project memory and #112, which you upvoted on 11 Oct." Each side names its strongest three. */
export function rankWhy(x: Pick<CardX, "rank" | "number"> | null | undefined): string | null {
  const r = x?.rank;
  if (!r) return null;
  if (r.line.startsWith("you graded")) return r.line[0]!.toUpperCase() + r.line.slice(1) + ".";
  if (!r.line) return null;
  const side = (up: boolean): string | null => {
    const ps = r.parts.filter((p) => (p.weight > 0) === up).slice(0, 3);
    if (!ps.length) return null;
    const names = ps.map((p, i) => (p.target === "idea" ? "#" : "observation #") + p.target_id + (i === 0 && p.title ? " " + p.title : ""));
    const list = names.length > 1 ? names.slice(0, -1).join(", ") + " and " + names.at(-1) : names[0]!;
    const days = [...new Set(ps.map((p) => graded(p.graded_at)))];
    return `${ps.every((p) => p.target === "observation") ? "near" : "like"} ${list}, which you ${up ? "upvoted" : "downvoted"} on ${days.join(" and ")}`;
  };
  const bits = r.taste > 0 ? [side(true), side(false)] : [side(false), side(true)];
  return `Ranked ${r.taste > 0 ? "up" : "down"}: ` + bits.filter(Boolean).join("; ") + ".";
}
export interface CardIdeas {
  from: "api";
  list: CardX[];
}

/** the words for a card's state; [word, icon, colour] */
export const ST: Record<string, [string, string, string]> = {
  open: ["Open", "open", "grey"], waiting: ["Waiting", "waiting", "grey"], passed: ["Passed", "closed", "grey"], closed: ["Closed", "closed", "grey"],
  later: ["Later", "waiting", "grey"], posted: ["Posted", "check", "green"],
};
export const stOf = (k: string | null | undefined): [string, string, string] => ST[k || ""] || (ST.open as [string, string, string]);
/** where an idea came from */
export const SRC: Record<string, string> = { kranto: "Kranto", brief: "a News brief" };
export const srcWord = (s: string): string => SRC[s] || s;
/** the owner's Parallax dispatches' three pitches */
export const PITCH_KIND: Record<string, string> = { oss: "OSS", commercial: "commercial", founder: "founder" };

export const isDispatch = (i: Idea | null | undefined): boolean => !!(i && i.card && i.card.origin === "dispatch");
export const ideaNo = (i: Idea): string => (i.card && i.card.number ? "#" + i.card.number : i.id.slice(0, 9));
/** An idea keeps its own title everywhere (the card's, else the words it was added with) */
export const ideaTitle = (i: Idea): string => i.title || i.id;
const day = (ts: number, o: Intl.DateTimeFormatOptions): string => new Date(ts * 1000).toLocaleDateString("en-GB", o);
export const laterText = (i: Idea): string | null => (i.later_until ? "later: until " + day(i.later_until, { day: "numeric", month: "short" }) : null);
export const laterUntil = (i: Idea): string => (i.later_until ? day(i.later_until, { weekday: "long", day: "numeric", month: "short" }) : "");
/** The decision on an open card, the same everywhere: Pass, Later */
export const canDecide = (i: Idea | null | undefined): boolean => !!i && i.status === "open";
export const GRADE: Record<string, string> = { useful: "useful", not_useful: "not useful", wrong: "wrong" };
/** an old link's id of the build loop's ledger (i…): still finds the card it took in (cardFor) */
export const isLoopId = (id: string): boolean => /^i[0-9a-f]{8}/.test(id);

/** Unfiltered, the cards are grouped Waiting · Later · Posted · Passed (H1: the server's own
 * state; a filter or a search makes them one group) */
export const IDEA_GROUPS: [CardState, string][] = [["waiting", "Waiting"], ["later", "Later"], ["posted", "Posted"], ["passed", "Passed"]];
/** Waiting's order: the ideas with a card in the server's rank order (what you
 * graded and what resembles it first), then those without a card (typed, from a brief) as they
 * came, newest change first */
export function rankOrder<T>(xs: T[], posOf: (x: T) => number | null | undefined): T[] {
  const ranked = xs.filter((x) => posOf(x) != null).sort((a, b) => (posOf(a) as number) - (posOf(b) as number));
  return [...ranked, ...xs.filter((x) => posOf(x) == null)];
}
/** Ideas' ``?since=<iso>`` (the home's "Everything since 2 November",): one group
 * "Since 2 November" of the cards written after it, newest first; null for no or a bad date */
export function sinceGroup<T extends { raw?: Record<string, unknown> | null }>(xs: T[], since: string | null | undefined): { w: string; xs: T[] } | null {
  const t = since ? Date.parse(since) : NaN;
  if (!Number.isFinite(t)) return null;
  const d = new Date(t);
  const w = `Since ${d.getDate()} ${d.toLocaleString("en-GB", { month: "long" })}`;
  return { w, xs: xs.filter((x) => Date.parse(String(x.raw?.created_at || "")) > t) };
}
/** a card as the sheet (Idea.svelte) reads an idea (H1: Ideas is cards alone): its number
 * is its id; waiting and later are open (Pass and Later on it), posted and passed are not */
export function cardIdea(x: CardX): Idea {
  const raw = (x.raw || {}) as Record<string, unknown>;
  const at = Date.parse(String(raw.created_at || "")) / 1000 || 0;
  const state = x.state || "waiting";
  return {
    id: String(x.number), status: state === "waiting" || state === "later" ? "open" : state, state, title: x.title, source: "kranto",
    text: String(raw.one_liner || ""), reason: null, created: at, updated: at,
    card: { ...raw, number: x.number, title: x.title, status: x.status, score: x.score, grade: x.grade, evidence: x.evidence || [] } as unknown as IdeaCard,
    later_until: x.later_until ? Date.parse(x.later_until) / 1000 : null,
  };
}
/** the card a link names (cards.ts registers it: the cards are read there): its number, card:N, or
 * the build loop's i… id of a card it took in (old links, H1) */
// a var, hoisted: cards.ts registers it while this module may still be loading (they import each
// other's neighbours), and a let would not exist yet then
// eslint-disable-next-line no-var
var cardFor: ((id: string) => CardX | null) | null;
export function setCardLookup(f: (id: string) => CardX | null): void {
  cardFor = f;
}
/** a card's number from a link's id: 143, card:143; null for anything else */
export function cardNo(id: string | null | undefined): number | null {
  const m = /^(?:card:)?(\d+)$/.exec(id || "");
  return m ? Number(m[1]) : null;
}
/** an idea by its id: the card it names, read from the server's cards; null without them
 * (no the server, or not read yet) */
export function ideaOf(id: string | null | undefined): Idea | null {
  const card = id && typeof cardFor === "function" ? cardFor(id) : null;
  return card ? cardIdea(card) : null;
}
export const match = (q: string | undefined, ...fields: (string | null | undefined)[]): boolean => !q || fields.join(" ").toLowerCase().includes(q.trim().toLowerCase());

/** Ideas' toolbar filters: the search, then Status (a card's state), Source and Kind (what the
 * idea would be; "Pitch" named a step that left with builds, B) folded into Filter ▾ */
export const IDEA_SELECTS: [string, string, [string, string][]][] = [
  ["status", "Status", [["", ""], ["waiting", "waiting"], ["later", "later"], ["posted", "posted"], ["passed", "passed"]]],
  ["source", "Source", [["", ""], ["dispatch", "imported dispatches"]]],
  ["kind", "Kind", [["", ""], ...Object.entries(PITCH_KIND)]],
];

/** when the first cards come, as the server's /api/ideas says while there are none */
export interface IdeasFirst {
  words: string;
  at: string | null;
  observations: number;
  needed: number;
}
/** a time ahead in the owner's words: "tonight at 22:00", "at 14:00", "tomorrow at 07:00",
 * "on 14 Nov at 07:00" */
export function nextAt(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "";
  const t = new Date(iso);
  if (Number.isNaN(t.getTime())) return "";
  const hm = t.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  const day = (d: Date): string => d.toDateString();
  const tomorrow = new Date(now.getTime() + 86400000);
  if (t.getTime() <= now.getTime()) return "now";
  if (day(t) === day(now)) return (t.getHours() >= 18 ? "tonight at " : "at ") + hm;
  if (day(t) === day(tomorrow)) return "tomorrow at " + hm;
  return `on ${t.toLocaleDateString("en-GB", { day: "numeric", month: "short" })} at ${hm}`;
}
/** Ideas' empty page: "No ideas yet. The first come after the map, once 30 items are
 * kept. So far: 12." or, with enough kept, "… after tonight's map at 22:00." */
export function firstWords(f: IdeasFirst, now: Date = new Date()): string {
  const at = nextAt(f.at, now);
  if (f.observations < f.needed) {
    // the hour and the threshold both: "after tonight's map at 22:00, once 30 items…"
    const when = at && at !== "now" ? (at.startsWith("tonight") ? `tonight's map ${at.slice(8)}` : `the map ${at}`) : "the map";
    return `No ideas yet. The first come after ${when}, once ${f.needed} items are kept. So far: ${f.observations}.`;
  }
  if (!at || at === "now") return "No ideas yet. The first come after the next map, which runs now.";
  return at.startsWith("tonight") ? `No ideas yet. The first come after tonight's map ${at.slice(8)}.` : `No ideas yet. The first come after the next map, ${at}.`;
}

/** a signal's own line, when the server sends signals */
export function signalRows(sig: CardX["signals"]): [boolean, string, string][] {
  const out: [boolean, string, string][] = [];
  for (const [k, v] of Object.entries(sig || {})) {
    if (v && typeof v === "object" && "agrees" in v) {
      const s = v as Signal;
      out.push([!!s.agrees, k.replace(/_/g, " "), s.line || s.detail || (s.agrees ? "agrees" : "not yet")]);
    }
  }
  return out;
}
export function signalsText(sig: CardX["signals"]): string | null {
  const xs = signalRows(sig);
  return xs.length ? `${xs.filter((x) => x[0]).length} of ${xs.length} agree` : null;
}
