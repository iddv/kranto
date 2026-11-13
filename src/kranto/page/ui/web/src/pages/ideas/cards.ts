// the server's idea cards, through one read. GET /api/ideas (the server web/ideas_api.py):
// each card with its number, title, status, score, grade, topics [{id, name, share}] from its
// lineage's latest cluster, citations and signals; embeddings come back as references only. A
// card's state on Ideas is the server's own (``state``: waiting, later, posted, passed; H1); a
// link to it is its number (card:N and an old i… id still find it: ideaOf).
import { read } from "../../lib/reads.svelte";
import { app } from "../../lib/shell.svelte";
import { cardNo, IDEA_GROUPS, isLoopId, setCardLookup, type CardIdeas, type CardState, type CardX, type Cited } from "./ideas";

export const IDEAS_API = "/api/ideas?embedding=ref";

type Raw = Record<string, unknown> & { number?: number; id?: number; title: string; status?: string; score?: number; grade?: unknown; verdict?: unknown;
  topics?: { id: number | string; name: string; share?: number }[]; citations?: Cited[]; evidence?: Cited[]; signals?: unknown; waiting?: boolean; theme?: unknown; origin?: string };
/** one topic's cards, filtered by the server (``?topic=``, in SQL: CON L2) */
export const topicCardsApi = (tid: number | string): string => `/api/ideas?topic=${encodeURIComponent(String(tid))}&embedding=ref`;
type Answer = Raw[] | { ideas?: Raw[]; results?: Raw[] };
/** the cards, read (30 s) and kept; null until they are read */
export function cardIdeas(): CardIdeas | null {
  const c = read<Answer>(IDEAS_API, 30000);
  return c.data ? { from: "api", list: parsed(c.data) } : null;
}
/** a topic's cards: the server's filtered answer, read for that topic alone (the topic's
 * pages and Ideas with ?topic= read every card and filtered here); a the server that refuses the
 * filter gives every card and topicIdeas filters them; null until read */
export function topicCards(tid: number | string): CardIdeas | null {
  const c = read<Answer>(topicCardsApi(tid), 30000);
  if (c.data) return { from: "api", list: parsed(c.data) };
  return c.error ? cardIdeas() : null;
}
/** one card as /api/ideas/<n> answers it, in the list's shape (a dispatch card is not in the
 * default list: its sheet reads it alone) */
export const cardX = (raw: unknown): CardX | null => (raw && typeof raw === "object" ? parsed({ ideas: [raw] } as Answer)[0] || null : null);
function parsed(data: Answer): CardX[] {
  const raw = Array.isArray(data) ? data : data.ideas || data.results || [];
  return raw.map((x) => ({ number: Number(x.number != null ? x.number : x.id), title: x.title, status: x.status, score: x.score,
      grade: x.grade || x.verdict || null, topics: (x.topics || []).map((t) => ({ id: Number(t.id), name: t.name, share: t.share })),
      cited: (x.citations || x.evidence || []).length, signals: (x.signals as CardX["signals"]) || null, waiting: x.status === "waiting" || !!x.waiting,
      // a theme compacted or renamed since the card was written comes back without a name: no
      // theme then, never "theme null" (QA B7)
      theme: (x.theme as CardX["theme"])?.name ? (x.theme as CardX["theme"]) : null, lineage: (x.lineage_id as string) || null, origin: x.origin || null, evidence: x.evidence || [], citations: x.citations || [],
      rank: (x.rank as CardX["rank"]) || null, prior_art: (x.prior_art as CardX["prior_art"]) || null,
      novelty_dropped: (x.novelty_dropped as CardX["novelty_dropped"]) || [],
      state: (x.state as CardState) || "waiting", later_until: (x.later_until as string) || null, raw: x } as CardX));
}
/** the card a link names: its number or card:N (a dispatch card, not in the list, by its own read),
 * or an old link's i… id of a card (its intake outcome names it); null until read */
export function cardFor(id: string): CardX | null {
  const ci = app()?.host() ? cardIdeas() : null;
  if (!ci) return null;
  const n = cardNo(id);
  if (n != null) {
    const hit = ci.list.find((x) => x.number === n);
    if (hit) return hit;
    const one = read<Record<string, unknown>>(`/api/ideas/${n}?embedding=ref`, 60000).data;
    return one && one.id != null ? cardX(one) : null;
  }
  if (!isLoopId(id)) return null;
  return ci.list.find((x) => ((x.raw?.outcomes as Record<string, { detail?: { idea?: string } }> | undefined)?.intake?.detail?.idea) === id) || null;
}
setCardLookup(cardFor);
/** the cards that cite an observation: those the server names (``cited_by.ideas`` of
 * /api/observations/<id>, its ``idea_citations``: CON L2), else the cards whose citations and
 * evidence name it (an older the server); null until the cards are read */
export function citedBy(oid: number | string, ids?: number[] | null): CardX[] | null {
  const ci = app()?.host() ? cardIdeas() : null;
  if (!ci) return null;
  if (ids) { const want = new Set(ids); return ci.list.filter((x) => want.has(x.number)); }
  return ci.list.filter((x) => [...((x as { citations?: Cited[] }).citations || []), ...(x.evidence || [])].some((e) => e && String(e.observation_id) === String(oid)));
}
/** a theme's cards: those on its lineage, never by its cluster number (a number means another
 * theme in each map) or its topics; null until the cards are read */
export function themeIdeas(lineage: string): CardX[] | null {
  const ci = app()?.host() ? cardIdeas() : null;
  if (!ci) return null;
  return ci.list.filter((x) => x.lineage === lineage);
}
/** a card's state on Ideas: the server's */
export function ideaStatus(x: CardX): string {
  return x.state || "waiting";
}
/** a topic's cards (with the part of each from the topic), from the server's topics; null until the
 * cards are read */
export function topicIdeas(tid: number, ci: CardIdeas | null): CardX[] | null {
  if (!ci) return null;
  return ci.list.filter((x) => (x.topics || []).some((t) => t.id === tid)).map((x) => ({ ...x, share: (x.topics || []).find((t) => t.id === tid)!.share ?? undefined }));
}
/** a topic's ideas, for its moved pages: its cards, Ideas' groups with each card's, and a card's
 * state */
export function topicWork(t: { id: number }) {
  const ideas = topicIdeas(t.id, topicCards(t.id));
  return { ideas, groups: IDEA_GROUPS, group: (x: CardX): string => x.state || "waiting", status: ideaStatus };
}
export type TopicWork = ReturnType<typeof topicWork>;
