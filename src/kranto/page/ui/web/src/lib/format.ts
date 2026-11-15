// Small words the shell writes, as the old page wrote them.

/** "under 1 min", "12 min", "1 h 5 min"; "–" without a duration */
export function dur(s: number | null | undefined): string {
  if (!s) return "–";
  const m = Math.round(s / 60);
  if (m < 1) return "under 1 min";
  return m < 60 ? m + " min" : Math.floor(m / 60) + " h " + (m % 60) + " min";
}

/** when the server reads the sources next: "18:00", "now", or "Fri 09:00" past today */
export function nextRead(at: string | number, now: Date = new Date()): string {
  const t = new Date(at);
  if (t.getTime() - now.getTime() < 60000) return "now";
  const hm = t.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  return t.toDateString() === now.toDateString() ? hm : t.toLocaleDateString("en-GB", { weekday: "short" }) + " " + hm;
}

export const longTime = (at: string | number): string =>
  new Date(at).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });

/** "just now", "12 min ago", "3 h ago", "yesterday", "4 d ago", from a time in seconds */
export function rel(ts: number | null | undefined, now: number = Date.now()): string {
  if (!ts) return "";
  const ago = (now / 1000 - ts) / 3600;
  const m = Math.round(ago * 60);
  return m < 1 ? "just now" : m < 60 ? m + " min ago" : ago < 24 ? Math.round(ago) + " h ago" : ago < 48 ? "yesterday" : Math.round(ago / 24) + " d ago";
}

/** a list row's age: "now", "12 min", "3 h", "4 d", from a time in seconds */
export function ago(ts: number | null | undefined, now: number = Date.now()): string {
  if (!ts) return "";
  const m = Math.round((now / 1000 - ts) / 60);
  return m < 1 ? "now" : m < 60 ? m + " min" : m < 1440 ? Math.round(m / 60) + " h" : Math.round(m / 1440) + " d";
}

/** money, always with two places: "$1.00"; none is "$0.00" */
export const usd = (v: number | null | undefined): string => "$" + Number(v || 0).toFixed(2);
/** a cap: "$40.00", or "no cap" for none (never "none", "null" or "–") */
export const capUsd = (v: number | null | undefined): string => (v == null ? "no cap" : usd(v));

/** one time, the house's way: under a minute "now", under a day "7 min" or "3 h"
 * ("7 min ago" in a sentence), else "17 Oct 08:44"; from seconds, milliseconds' Date or ISO */
export function when(at: number | string | null | undefined, o: { inSentence?: boolean; now?: number } = {}): string {
  if (at == null || at === "") return "";
  const t = typeof at === "number" ? (at < 1e11 ? at * 1000 : at) : Date.parse(at);
  if (Number.isNaN(t)) return "";
  const m = Math.round(((o.now ?? Date.now()) - t) / 60000);
  if (m >= 0 && m < 1440) {
    const w = m < 1 ? "now" : m < 60 ? m + " min" : Math.round(m / 60) + " h";
    return o.inSentence && w !== "now" ? w + " ago" : w;
  }
  const d = new Date(t);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" }) + " " + d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

/** "1 action", "3 actions" */
export const plural = (n: number, w: string, ws?: string): string => `${n} ${n === 1 ? w : ws || w + "s"}`;

/* Tokens, not dollars, for what one thing used (the owner's ruling, 2026-10-09: a price is a
   point-in-time fact about one model and harness). A pair is {in, out}: shown as "1.2M tokens",
   read and written in the tooltip; a record with no counts shows nothing, never dollars. */
export interface Tok {
  in?: number;
  out?: number;
}
export const kTok = (n: number): string => n >= 999500 ? (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M" : n >= 10000 ? Math.round(n / 1000) + "k"
  : n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, "") + "k" : String(n);
export const tokText = (t: Tok | null | undefined): string => (t ? kTok((t.in || 0) + (t.out || 0)) + " tokens" : "");
export const tokTitle = (t: Tok | null | undefined): string | null => (t ? `${(t.in || 0).toLocaleString("en-GB")} in · ${(t.out || 0).toLocaleString("en-GB")} out` : null);

/** a score to three places; "–" without one */
export const n3 = (v: number | null | undefined): string => (v == null ? "–" : Number(v).toFixed(3));
export const pct = (v: number | null | undefined, d = 0): string => (v == null ? "–" : (v * 100).toFixed(d) + "%");
/** words cut to n characters, an ellipsis last */
export const cut = (s: string | null | undefined, n: number): string => (!s ? "" : s.length > n ? s.slice(0, n - 1) + "…" : s);
/** the first sentence of a text of at least 24 characters, else the whole text on one line */
export const firstSentence = (s: string | null | undefined): string => {
  const t = String(s || "").replace(/\s+/g, " ").trim(), m = t.match(/^(.{24,}?[.!?])(\s|$)/);
  return m ? (m[1] as string) : t;
};
/** an ISO time, in seconds */
export const dt = (s: string | null | undefined): number | null => (s ? Date.parse(s) / 1000 : null);
/** an ISO time as "2026-10-15 07:58" */
/** a provider's pause (the server's watch_paused: a spend limit at the provider, a plan's usage
 * window) in words: "Watching paused until 2026-10-01 00:00 (spend limit set in the Claude
 * Console reached)"; the reason up to its first colon */
export const watchPaused = (p: { until: string; reason: string }): string =>
  `Watching paused until ${stamp(p.until)}` + (p.reason ? ` (${p.reason.split(":")[0]})` : "");
export const stamp = (s: string | null | undefined): string => (s || "").replace("T", " ").replace(/(:\d\d)(\.\d+)?Z$/, "$1").slice(0, 16);
/** a running ingest's progress (the server's ``ingest_progress``) in words: "source 3 of 8, inkandswitch.com:
 * 12 of 40 items · 5 kept so far" (MEM, S2: a first read ran 39 minutes with nothing said) */
export const readingWords = (p: { sources: number; source_index: number; source: string | null; items: number | null; item: number; kept: number }): string =>
  [`source ${p.source_index} of ${p.sources}` + (p.source ? `, ${cut(p.source, 40)}` : ""),
    p.items == null ? "fetching" : p.items ? `${p.item} of ${plural(p.items, "item")}` : "nothing new", plural(p.kept, "kept so far", "kept so far")].join(" · ");
/** the server's memory (``/api/health`` ``memory``) in a line: "1.0 GB of 3.0 GB (the high mark; 4.0 GB at most)" */
export const memoryWords = (m: { used_mb: number | null; high_mb: number | null; max_mb: number | null }): string => {
  const gb = (mb: number): string => (mb >= 1024 ? (mb / 1024).toFixed(1) + " GB" : mb + " MB");
  const used = m.used_mb == null ? "unknown" : gb(m.used_mb);
  if (m.high_mb == null && m.max_mb == null) return `${used} · no cap set`;
  return m.high_mb != null ? `${used} of ${gb(m.high_mb)} (the high mark` + (m.max_mb != null ? `; ${gb(m.max_mb)} at most)` : ")") : `${used} of ${gb(m.max_mb!)} at most`;
};
