// The one vocabulary (the glossary): every state says what it means for you, every
// verb what will happen. A user reasons only from what is on the screen, so the same thing has the
// same word everywhere. Pure functions: the components draw what these return, and words.test.ts
// pins each sentence.

/** what one thing used, in tokens (a trace's, a run's) */
export interface Tokens {
  in: number;
  out: number;
}

/** a colour and an icon for a state: the page's tones (kranto.css c-*) and lib/icons names */
export interface Tone {
  tone: "red" | "amber" | "green" | "blue" | "grey" | "violet";
  icon: string;
}

/** tokens, never dollars, for what one thing used (the owner's ruling, 2026-10-09) */
export function kTok(n: number): string {
  if (n >= 999500) return (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
  if (n >= 10000) return Math.round(n / 1000) + "k";
  if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, "") + "k";
  return String(n);
}
export const tokText = (t: Tokens | null | undefined): string => (t ? kTok((t.in || 0) + (t.out || 0)) + " tokens" : "");
export const tokShort = (t: Tokens | null | undefined): string => (t ? kTok((t.in || 0) + (t.out || 0)) : "–");
export function tokSum(ts: (Tokens | null | undefined)[]): Tokens | null {
  const xs = ts.filter((t): t is Tokens => !!t);
  return xs.length ? { in: xs.reduce((a, t) => a + (t.in || 0), 0), out: xs.reduce((a, t) => a + (t.out || 0), 0) } : null;
}

export function cut(s: string, n: number): string {
  const t = String(s || "").split("\n")[0] || "";
  return t.length > n ? t.slice(0, n - 1).trimEnd() + "…" : t;
}

/** a clock time, and a short date and time, in the page's locale */
export const clock = (ts: number): string => new Date(ts * 1000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
export const day = (ts: number): string => {
  const d = new Date(ts * 1000);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" }) + " " + clock(ts);
};
export function ago(ts: number | null | undefined, now: number = Date.now() / 1000): string {
  if (!ts) return "";
  const h = (now - ts) / 3600, m = Math.round(h * 60);
  return m < 1 ? "now" : m < 60 ? m + " min" : h < 24 ? Math.round(h) + " h" : Math.round(h / 24) + " d";
}

// -- Settings' words (the glossary): one name per concept ------------------------

/** the names Settings, Welcome and the toasts use; words.test.ts pins them, and a page that
 * needs a new word adds it here with a test */
export const SETTING_WORDS = {
  watching: "Watching", // the server's half; never "monitoring"
  provider: "provider", // where model calls go: Claude API · OpenRouter · Another endpoint · Claude Code
  key: "key",
  login: "login",
  account: "account",
  cap: "cap", // never "budget" or "limit"
  noCap: "no cap",
  needsYou: "Needs you",
  judge: "Judge",
  reasoner: "Reasoner",
  usageReports: "Usage reports",
  yourSettings: "your settings", // never a file name in a sentence
} as const;

/** when a change takes effect: every Save and every toast ends with one */
export const EFFECT = {
  now: "Applies at once.",
  check: "From the next check.",
  run: "From the next run.",
  restart: "After a restart (kranto down, kranto up).",
} as const;
export type Effect = keyof typeof EFFECT;

/** a Save's toast: "Saved: <what>. <Effect>" */
export const saidSaved = (what: string, effect: Effect): string => `Saved: ${what.replace(/\.$/, "")}. ${EFFECT[effect]}`;
