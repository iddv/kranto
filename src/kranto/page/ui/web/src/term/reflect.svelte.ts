// Reflection: what an assistant did shows on the page. The server keeps each verb an
// assistant ran or prepared in <data>/verbs.json; the live feed says "verb" when it changes, and
// this reads GET /api/verbs/recent?since=, marks the rows the verbs touched for a while ("✦ Add
// topic, by Claude Code") and has the page read the server's data again.
export interface VerbLine {
  seq: number;
  /** a prepared item's end, approved or dismissed (the server 0.6.0.dev15+); null while it waits */
  resolved?: string | null;
  verb: string;
  title: string;
  subject: { kind: string; id: string | number | null } | null;
  page: string | null;
  mark: string;
  by: string | null;
  by_words: string;
  prepared: string | null;
  run: string | null;
  at: string;
}

export const MARK_MS = 8000;
/** the rows marked now: a row's data-sel → its words and until when */
export const touched: { rows: Record<string, { words: string; until: number }>; seq: number } = $state({ rows: {}, seq: -1 });

/** the data-sel keys a verb's mark may have on a page: topic:14 → t14 (Watch's rows), … */
export function selsFor(mark: string): string[] {
  const m = /^([a-z]+):(.+)$/.exec(mark || "");
  if (!m) return [];
  const [, kind, id] = m as unknown as [string, string, string];
  return [...new Set([kind[0] + id, `${kind}:${id}`, id])];
}

/** the words a marked row says */
export function markWords(x: Pick<VerbLine, "title" | "by_words" | "prepared">): string {
  return x.prepared ? `✦ ${x.title}: prepared ${x.by_words}, waits for you` : `✦ ${x.title}, ${x.by_words}`;
}

export function mark(lines: VerbLine[], now = Date.now()): void {
  const rows = { ...touched.rows };
  for (const x of lines) for (const s of selsFor(x.mark)) rows[s] = { words: markWords(x), until: now + MARK_MS };
  for (const [k, v] of Object.entries(rows)) if (v.until < now) delete rows[k];
  touched.rows = rows;
}

/** the words of the row with this data-sel, while it is marked */
export function rowMark(sel: string | null | undefined, now = Date.now()): string | null {
  if (!sel) return null;
  const v = touched.rows[sel];
  return v && v.until >= now ? v.words : null;
}

/** On the feed's "verb": the new lines, marked; true when there were any (the page reads again).
 * The first call only learns where the lines are (nothing before this page was opened is marked). */
export async function reflect(get: (path: string) => Promise<Response> = (p) => fetch(p, { cache: "no-store" }),
  onLines?: (lines: VerbLine[]) => void): Promise<boolean> {
  let body: { seq?: number; recent?: VerbLine[] } | null = null;
  try {
    const r = await get(`/api/verbs/recent?since=${Math.max(0, touched.seq)}`);
    body = r.ok ? await r.json() : null;
  } catch {
    body = null;
  }
  if (!body || typeof body.seq !== "number") return false;
  const first = touched.seq < 0;
  touched.seq = body.seq;
  if (first) return false;
  const lines = (body.recent || []).filter((x) => x && typeof x.seq === "number");
  if (!lines.length) return false;
  onLines?.(lines);
  mark(lines);
  setTimeout(() => mark([]), MARK_MS + 50);
  return true;
}

/** an assistant's door in a run's trigger, in words: "by Claude Code", "by Codex (outside)" */
export function byWords(by: string | null | undefined): string | null {
  const s = String(by || "");
  const [door, who] = [s.split(":")[0], s.split(":").slice(1).join(":")];
  const NAMES: Record<string, string> = { claude: "Claude Code", "claude-code": "Claude Code", codex: "Codex" };
  const name = NAMES[who] || who;
  if (door === "console") return `by ${name || "the console"}`;
  if (door === "mcp") return name ? `by ${name} (outside)` : "by your own assistant";
  if (door === "agent") return `by agent ${who}`;
  return null;
}
