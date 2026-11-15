// Settings › Watching › Live search: which backend answers the callers that
// ask what exists, what is new or what is prior art; each caller's switch; how many weeks
// "recent" is. The server's /api/setup/search says it (SearchSetup, generated from its web/types.py);
// POST /api/setup/search tests a choice and keeps it only when the test passes (a key goes into
// the workspace's .env, never a page or your settings); POST /api/setup/search/callers writes the
// switches and the weeks. A key is a password field read once at the press, as KeyField's is.
import type { SearchSetup } from "../../api/afk.gen";
import { SET_ST, type St } from "../../ui/settings";
export type { SearchChoice, SearchSetup } from "../../api/afk.gen";

export const SEARCH_API = "/api/setup/search";
export const CALLERS_API = "/api/setup/search/callers";

/** the callers, in the order the pane lists them, each with what it searches for */
export const CALLERS: readonly [string, string, string][] = [
  ["scout", "The scout", "what to watch for a topic, from dated results"],
  ["cards", "Idea cards", "each card's prior art"],
  ["editor", "The weekly editor", "a second look at what already shipped"],
  ["research", "The research desk", "a question researched on the web"],
  ["resolve", "Resolving sources", "a second look at lines that did not resolve"],
  ["pitch", "The pitch", "whether the name is taken"],
  ["evolve", "Evolve", "a project's world: its dependencies' releases, its neighbours"],
  ["sources", "Sites without a feed", "the Live search source kind"],
];
/** each caller's choices, in the server's words (config.SEARCH_CALLERS) */
export const CALLER_CHOICES: Record<string, [string, string][]> = {
  research: [["agent", "a researcher that searches as it goes"], ["search", "one search, then one answer"], ["off", "off: from model memory"]],
  resolve: [["failed_lines", "on, for lines that did not resolve"], ["off", "off"]],
};
export const choicesOf = (caller: string): [string, string][] => CALLER_CHOICES[caller] || [["on", "on"], ["off", "off: from model memory"]];
export const choiceWord = (caller: string, v: string): string => choicesOf(caller).find(([k]) => k === v)?.[1] || v;
/** the free backends' names (the server's websearch.LABELS) */
export const FREE_WORD: Record<string, string> = { hackernews: "Hacker News", github: "GitHub", arxiv: "arXiv" };
const offWord =(v: string): boolean => v === "off";

/** what the pages keep while the owner changes the form (cleared at Save and on Undo) */
export const SEARCH_FORM = $state<{ provider: string | null; callers: Record<string, string>; weeks: string | null }>({ provider: null, callers: {}, weeks: null });

/** the backend in words: its state and one line */
export function searchWords(s: SearchSetup): { st: St; line: string } {
  if (!s.web) return { st: SET_ST.off, line: `None. Every caller says "${s.no_search}".` };
  const failing = Object.entries(s.failing || {}).filter(([, n]) => n > 0).map(([b]) => b);
  const label = s.web_label || s.web;
  const free = s.free.length ? ` With ${s.free.map((b) => FREE_WORD[b] || b).join(", ")}, always free.` : "";
  if (failing.length) return { st: SET_ST.warn, line: `${label}. Failing lately: ${failing.join(", ")}.${free}` };
  return { st: SET_ST.ok, line: `${label}.${free}` };
}

/** the callers' switches in one line: "all on", or which are off */
export function callersLine(callers: Record<string, string>): string {
  const off = CALLERS.filter(([k]) => offWord(callers[k] || "")).map(([, w]) => w);
  return off.length ? `off: ${off.join(", ")}` : "all on";
}

/** the weeks typed, checked as the server checks them */
export function weeksValue(text: string): number {
  const n = Number(text.trim());
  if (!Number.isInteger(n) || n < 1 || n > 520) throw new Error("Recent is a whole number of weeks from 1 to 520.");
  return n;
}
