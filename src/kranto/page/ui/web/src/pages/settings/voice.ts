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
  take: boolean;
  never: string[];
  keep: string[];
  always: string[];
  samples: { id: string; site: string | null; words: number; start: string }[];
}

/** the four Welcome asks too, then the rest under Advanced */
export const MAIN_SWITCHES = ["length", "register", "opinions", "emoji"] as const;
export const MORE_SWITCHES = ["hashtags", "links", "grade"] as const;
export const SWITCH_LABELS: Record<string, string> = {
  length: "How long", register: "How formal", opinions: "Opinions", emoji: "Emoji",
  hashtags: "Hashtags", links: "Links", grade: "Reading level (school grade)",
};
const CHOICES: Record<string, string> = {
  "opinions:mine": "only mine", "opinions:suggest": "suggest one, marked for me",
  "hashtags:site": "as the site does", "links:post": "in the post", "links:reply": "in the first reply",
};
export const choiceWords = (k: string, v: string): string => CHOICES[`${k}:${v}`] || v;
export const SITE_WORDS: Record<string, string> = {
  blog: "Blog", newsletter: "Newsletter", mastodon: "Mastodon", bluesky: "Bluesky", linkedin: "LinkedIn",
  threads: "Threads", x: "X", substack: "Substack",
};
/** a list as typed, a line each, blank lines and duplicates dropped */
export const linesOf = (text: string): string[] => [...new Set(text.split("\n").map((l) => l.trim()).filter(Boolean))];
/** what to add and remove to go from one list to the other */
export function listDiff(was: string[], now: string[]): { add: string[]; remove: string[] } {
  return { add: now.filter((x) => !was.includes(x)), remove: was.filter((x) => !now.includes(x)) };
}
