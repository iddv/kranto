// Settings › Posting › How you write: the prose profile as the server answers it (GET /api/prose,
// docs/prose.md) and the page's own words for its switches.
export const PROSE = "/api/prose";

export interface Prose {
  voice: string;
  switches: Record<string, string | number>;
  switch_choices: Record<string, (string | number)[]>;
  switch_words: Record<string, string>;
  strictness: string;
  rules: { id: string; group: string; words: string; fix: string; on: boolean }[];
  guides: { name: string; title: string; from: string; always: boolean }[];
  sites: { site: string; guides: string[]; default: boolean; limits: Record<string, number>; disclosure: string }[];
  disclosure_line: string;
  /** what a short post ends with where its disclosure is on and no words are set */
  disclosure_default?: string;
  /** the model each writer writes with: null is Kranto's own writing model (none is chosen) */
  writer_models?: Record<string, { provider: string; model: string } | null>;
  writer_providers?: string[];
  /** whether an OpenAI key for a writer's own model is kept: never the key */
  writer_key?: { set: boolean };
  take: boolean;
  never: string[];
  keep: string[];
  always: string[];
  samples: { id: string; site: string | null; words: number; start: string }[];
}

/** the four Welcome asks too, then the rest under Advanced */
export const MAIN_SWITCHES = ["length", "register", "opinions", "emoji"] as const;
export const MORE_SWITCHES = ["hashtags", "links", "grade", "salt", "salt_thin"] as const;
export const SWITCH_LABELS: Record<string, string> = {
  length: "How long", register: "How formal", opinions: "Opinions", emoji: "Emoji",
  hashtags: "Hashtags", links: "Links", grade: "Reading level (school grade)",
  salt: "Salt", salt_thin: "More salt on thin items",
};
const CHOICES: Record<string, string> = {
  "opinions:mine": "only mine", "opinions:suggest": "suggest one, marked for me",
  "hashtags:site": "as the site does", "links:post": "in the post", "links:reply": "in the first reply",
  "salt:wry": "wry (understatement)", "salt:salty": "salty (a jab at the thing, never at a person)",
};
export const choiceWords = (k: string, v: string): string => CHOICES[`${k}:${v}`] || v;
export const SITE_WORDS: Record<string, string> = {
  blog: "Blog", newsletter: "Newsletter", mastodon: "Mastodon", bluesky: "Bluesky", linkedin: "LinkedIn",
  threads: "Threads", x: "X", substack: "Substack",
};
/** Kranto's writers, in the page's order, and the words for each */
export const WRITERS: [string, string][] = [["social", "Short posts"], ["blog", "Blog posts"], ["newsletter", "The newsletter"], ["toot", "The Mastodon post on a card"]];
/** where a writer's own model runs, in words; "" is Kranto's own writing model */
export const PROVIDER_WORDS: Record<string, string> = {
  "": "Kranto's writing model", openai: "OpenAI, with your key", anthropic: "Anthropic, with your key",
  openrouter: "OpenRouter, with your key", openai_compat: "Your OpenAI-compatible server", claude_code: "Claude Code, your login",
};
/** the sites a disclosure line can end: the short-post sites, then the long ones */
export const DISCLOSE_SITES = ["bluesky", "mastodon", "threads", "linkedin", "x", "blog", "newsletter"] as const;
/** a writer-model change as prose.voice takes it: null back to Kranto's own, else the pair */
export function writerChange(provider: string, model: string): { provider: string; model: string } | null {
  return provider ? { provider, model: model.trim() } : null;
}
/** a list as typed, a line each, blank lines and duplicates dropped */
export const linesOf = (text: string): string[] => [...new Set(text.split("\n").map((l) => l.trim()).filter(Boolean))];
/** what to add and remove to go from one list to the other */
export function listDiff(was: string[], now: string[]): { add: string[]; remove: string[] } {
  return { add: now.filter((x) => !was.includes(x)), remove: was.filter((x) => !now.includes(x)) };
}
