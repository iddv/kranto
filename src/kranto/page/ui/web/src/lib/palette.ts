// The command palette's ranking (⌘K, UI-v4.md 2.4): results grouped Ideas · Evidence · Sources ·
// Topics · Commands, the group with the best match first; with the doors on also
// the last things opened (Recent), Settings by name or key, and Go to.
export const PGROUPS = ["Recent", "Ideas", "Evidence", "Sources", "Topics", "Settings", "Go to", "Commands"] as const;

export interface PalItem {
  g: string;
  title: string;
  detail?: string | null;
  go?: string;
  run?: () => unknown;
  act?: (() => unknown) | null;
  actWord?: string;
  keys?: string | null;
  score: number;
}

/** 5 the title is the query, 4 the title starts with it, 3 a word of it starts with the first
 * word, 2 the title holds the query, 1 every word is somewhere in the fields, 0 no match. "post"
 * then opens Post, not Settings › Posting's first match (B, Codex 21). */
export function palScore(q: string, title: unknown, ...rest: unknown[]): number {
  const s = q.trim().toLowerCase();
  const t = String(title || "").toLowerCase();
  const ws = s.split(/\s+/).filter(Boolean);
  const all = [t, ...rest.map((x) => String(x || "").toLowerCase())].join(" ");
  if (!ws.length || !ws.every((w) => all.includes(w))) return 0;
  const first = ws[0] as string;
  return t === s ? 5 : t.startsWith(s) ? 4 : t.split(/[^a-z0-9]+/).some((w) => w && w.startsWith(first)) ? 3 : t.includes(s) ? 2 : 1;
}

/** [[group, items]], the best group first; at most 6 a group, 8 for evidence, 40 commands with
 * no query. */
export function palGroups(items: PalItem[], q: string): [string, PalItem[]][] {
  const by: Record<string, PalItem[]> = {};
  for (const x of items) (by[x.g] = by[x.g] || []).push(x);
  for (const g in by)
    by[g] = (by[g] as PalItem[]).sort((a, b) => b.score - a.score).slice(0, g === "Evidence" ? 8 : (g === "Commands" || g === "Go to") && !q.trim() ? 40 : 6);
  const top = (g: string) => (by[g] as PalItem[])[0]?.score ?? 0;
  return PGROUPS.filter((g) => by[g])
    .sort((a, b) => top(b) - top(a) || PGROUPS.indexOf(a) - PGROUPS.indexOf(b))
    .map((g) => [g, by[g] as PalItem[]]);
}

export const palKey = (x: Pick<PalItem, "g" | "title">): string => x.g + "\u0000" + x.title;
