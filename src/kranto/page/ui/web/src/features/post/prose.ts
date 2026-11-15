// PROSE's flags on a draft (the server docs/prose.md): the checker's spans, each
// with its plain fix, and one line ("Reads natural", "2 things read like AI: fix them"); Fix them
// is revise, which rewrites only those spans and stores nothing (the page saves through the
// draft's edit). The check is local and deterministic on the server: no model call.
import { app } from "../../lib/shell.svelte";

export interface ProseFlag {
  start: number; end: number; text: string; rule: string; words: string; fix: string;
  group?: string; strength?: string; scope?: "span" | "text" | string;
}
export interface ProseCheck {
  score: number; verdict: string; flags: ProseFlag[]; counts?: Record<string, number>;
  grade?: number | null; words?: number; strictness?: string; site?: string | null;
}
export interface ProseRevised { text: string; flags: ProseFlag[]; score: number; verdict: string; rounds: number; say?: string }

/** the prose profile's site for a draft's kind (the writers' own: blog, newsletter, mastodon) */
export const siteOf = (kind: string): string => (kind === "mastodon" || kind === "newsletter" || kind === "blog" ? kind : kind || "blog");

async function post<T>(path: string, body: unknown): Promise<T | null> {
  const L = app();
  if (!L) return null;
  try {
    return (await L.api(path, body)) as T;
  } catch {
    return null;
  }
}
/** prose.check (a read): the flags and the line, or null when there is no answer */
export const checkProse = async (text: string, site: string, sources: string | null = null): Promise<ProseCheck | null> => {
  if (!text.trim()) return null;
  // sources: what a short post was written from; a name it uses that they lack is flagged
  const got = await post<ProseCheck>("/api/prose/check", sources ? { text, site, sources } : { text, site });
  return got && Array.isArray(got.flags) && typeof got.verdict === "string" ? got : null;
};
/** Fix them: revise the flagged spans only (one model call, at most two rounds); stores nothing */
export const reviseProse = async (text: string, site: string, flags: ProseFlag[]): Promise<ProseRevised | null> => {
  const got = await post<ProseRevised>("/api/prose/revise", { text, site, flags });
  return got && typeof got.text === "string" && Array.isArray(got.flags) ? got : null;
};
/** learn from an edit: the original's words and the owner's, for proposals shown on Post (nothing changes without a yes) */
export function learnFrom(draft: string, sent: string): void {
  if (!draft.trim() || !sent.trim() || draft === sent) return;
  void post("/api/prose/learn", { draft, sent });
}

/** the text cut into plain runs and flagged spans, for the underline (spans in order, never overlapping) */
export function spans(text: string, flags: ProseFlag[]): { t: string; f: ProseFlag | null }[] {
  const marks = flags.filter((f) => f.scope !== "text" && f.end > f.start && f.end <= text.length).sort((a, b) => a.start - b.start);
  const out: { t: string; f: ProseFlag | null }[] = [];
  let at = 0;
  for (const f of marks) {
    if (f.start < at) continue;
    if (f.start > at) out.push({ t: text.slice(at, f.start), f: null });
    out.push({ t: text.slice(f.start, f.end), f });
    at = f.end;
  }
  if (at < text.length) out.push({ t: text.slice(at), f: null });
  return out;
}
/** "2 things read like AI" or "Reads natural", from the server's line without its ": fix them" */
export const lineOf = (c: ProseCheck): string => (c.flags.length ? c.verdict.replace(/:\s*fix them$/i, "") : "Reads natural");
