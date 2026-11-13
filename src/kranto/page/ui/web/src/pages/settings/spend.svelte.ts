// Settings › Spend: the one page with dollars (the owner's ruling, 2026-10-09). Where it went
// first, as rows: by topic (watching's model calls this month); then the caps. With nothing
// selected the pane is Totals and caps: the table, every cap field and Save, so seeing spend is
// one click (S11). All of it is the server's.
export const TOPICS = "/api/spend/topics";
export const WATCH = "/api/settings/spend";
/** the server's Settings › Watching › Reading (UP #3): how often sources are read, deep dives on */
export const READING = "/api/settings/reading";
export interface Reading {
  every_hours: number;
  deep_dive: { enabled: boolean; daily_usd: number | null };
  every_hours_effect: string;
  deep_dive_effect: string;
  config: string;
}

export const usd = (v: number | null | undefined): string => (v ? "$" + Number(v).toFixed(2) : "$0.00");
export const cents = (n: number | null | undefined): string => "$" + Number(n || 0).toFixed(2);
/** Spend's own: a sum, or "–" for none */
export const money = (n: number | null | undefined): string => (n ? "$" + Number(n).toFixed(2) : "–");
export const capWord = (v: number | null | undefined): string => (v == null ? "no cap" : `$${Number(v).toFixed(2)}`);
export const capText = (v: number | null | undefined): string => (v == null ? "" : String(v));

export const SPEND_PURPOSE: Record<string, string> = {
  card: "Idea cards", verify: "Checking cards' evidence", name: "Naming themes", explain: "Explanations", scout: "The scout",
  rollup: "Compaction summaries", judge: "Judging (no source)", screen: "Screening (no source)",
  news_brief: "News briefs",
};
/** the spend lines of features that left Kranto (their old rows stay in the ledger): one row, never
 * their raw names */
const RETIRED_PURPOSE = /^(invest|radar)(_|$)/;
/** Spend's other purposes as the page words them: a known one by its words, the retired ones as
 * one row, any other by its name in plain words (an older or newer the server's) */
export function otherRows(xs: TopicSpend["other"]): { purpose: string; word: string; usd: number; calls: number }[] {
  const out: { purpose: string; word: string; usd: number; calls: number }[] = [];
  let gone: { purpose: string; word: string; usd: number; calls: number } | null = null;
  for (const x of xs || []) {
    const p = String(x.purpose || "");
    if (RETIRED_PURPOSE.test(p)) {
      if (!gone) out.push((gone = { purpose: "retired", word: "Features that left Kranto", usd: 0, calls: 0 }));
      gone.usd += Number(x.usd) || 0;
      gone.calls += Number(x.calls) || 0;
    } else {
      const w = SPEND_PURPOSE[p] || p.replace(/[._]+/g, " ").trim();
      out.push({ purpose: p, word: w ? w.charAt(0).toUpperCase() + w.slice(1) : "Other", usd: x.usd, calls: x.calls });
    }
  }
  return out;
}

/** what is typed in a cap field, by its id, kept until Save (across redraws and groups) */
export const CAPS = $state<Record<string, string>>({});
/** a cap field's value: dollars above 0, or null for no cap */
export function capValue(id: string, current: number | null | undefined): number | null {
  const t = (id in CAPS ? (CAPS[id] as string) : capText(current)).trim();
  if (!t) return null;
  const n = Number(t);
  if (!(n > 0)) throw new Error("A cap is a number of dollars above 0, or empty for no cap.");
  return n;
}

export interface TopicSpend {
  total_usd: number;
  budget_usd: number | null;
  topics: { id: number | string; name: string; usd: number; calls: number }[];
  broad: { usd: number; calls: number };
  other: { purpose: string; usd: number; calls: number }[];
  compacted_usd: number;
}
export interface WatchCaps {
  spent_usd: number;
  monthly_usd: number | null;
  alarm?: boolean;
  alarm_fraction: number;
  config: string;
  deep_dive: { daily_usd: number | null; enabled: boolean };
  /** the watcher's provider, and its calls billed to a plan this month (Claude Code's login) */
  provider?: string;
  plan?: { calls: number; equiv_usd: number; last_limit_at: string | null } | null;
  /** X's reads this month: an estimate at X's list price, not model spend (the server) */
  x?: { monthly_usd: number | null; spent_usd: number; reads: number; requests: number; capped: boolean; connected: boolean; prices_as_of: string };
  /** live search this month (the server): a line per backend used, the free ones at 0 */
  search?: { monthly_usd: number | null; spent_usd: number; capped: boolean; prices_as_of: string;
    lines: { backend: string; label: string; searches: number; usd: number; free: boolean }[] };
}
/** Spend's live search line, or null before any search this month */
export function searchLine(s: WatchCaps["search"]): string | null {
  if (!s || !s.lines.length) return null;
  const each = s.lines.map((l) => `${l.label} ${l.searches} search${l.searches === 1 ? "" : "es"}, ${l.free ? "free" : usd(l.usd)}`).join(" · ");
  const paid = `Paid search ${usd(s.spent_usd)} this month`;
  return s.capped ? `${each}. ${paid}: the cap of ${capWord(s.monthly_usd)} is reached, so paid search waits until the first of next month.`
    : `${each}. ${paid}, ${s.monthly_usd == null ? "no cap" : "cap " + capWord(s.monthly_usd)}.`;
}
/** the plan-billed line (MP D10): calls billed to the Claude plan cost no dollars here */
export function planWords(p: NonNullable<WatchCaps["plan"]>): string {
  return `Your Claude plan is billed by usage, not dollars: this month ${p.calls.toLocaleString("en-GB")} calls through Claude Code, about $${p.equiv_usd.toFixed(2)} at API list prices, included in your plan.`
    + (p.last_limit_at ? ` A usage window last closed ${p.last_limit_at.replace("T", " ").slice(0, 16)} UTC; watching paused until it reopened.` : "")
    + " The monthly cap counts dollars only.";
}
/** Spend's X line, or null when X is neither connected nor read this month */
export function xLine(x: WatchCaps["x"]): string | null {
  if (!x || (!x.connected && !x.requests)) return null;
  const est = `${usd(x.spent_usd)} this month (${x.reads} read${x.reads === 1 ? "" : "s"}; an estimate at X's list price of ${x.prices_as_of}, the Developer Console is the bill)`;
  return x.capped ? `${est}. The cap of ${capWord(x.monthly_usd)} is reached: X sources wait until the first of next month.` : `${est}, ${x.monthly_usd == null ? "no cap" : "cap " + capWord(x.monthly_usd)}.`;
}
