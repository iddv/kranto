// The scout's proposals (Add topic, a topic's Sources, Today's proposals): approve one from its row,
// or watch what is ticked; a wildcard is watched with no topic. TICKS keeps what is ticked per topic
// (its Sources, Scout more, Today's proposals and the palette's Scout share it).
import { app } from "../../lib/shell.svelte";

/** the proposals ticked, by topic id */
export const TICKS: Record<string, Set<number>> = {};

export interface Proposal {
  id: number;
  label: string;
  role?: string | null;
  review?: string | null;
  pretick?: boolean | null;
  site_name?: unknown;
  why?: unknown;
  replaces?: unknown;
  items_per_day?: number | null;
  validation?: { median_similarity?: number | null; recent?: number | null } | null;
  /** an X source's reads: what one run reads at most at X's prices (the server's Source.spend) */
  spend?: { run_usd: number } | null;
}
/** approve one proposal, from its row or its pane: watched for the topic tid (a wildcard with no
 * topic); the topic's name for the toast */
export function approveSource(btn: HTMLElement | null, p: Pick<Proposal, "id" | "label" | "role">, tid: number | string | null, name?: string): Promise<void> {
  const L = app();
  if (!L) return Promise.resolve();
  return L.act(btn, () => L.api("/api/sources", { id: p.id, status: "approved", topic: p.role === "wildcard" ? null : tid }), () => {
    L.afkStale("/api/today", "/api/sources", "/api/topics"); void L.loadHost(); L.render();
    L.toast(`Watching ${p.label}${p.role === "wildcard" ? " with no topic (a wildcard: every item is judged)" : name ? " for " + name : ""}. Its first fetch is the next ingest run.`);
  });
}
/** Dismiss a proposal (UP #8; the word list's verb beside Approve): not watched, kept as retired so
 * the scout does not propose it again; the toast offers Undo, which proposes it again */
export function dismissSource(btn: HTMLElement | null, p: Pick<Proposal, "id" | "label">, after?: () => void): Promise<void> {
  const L = app();
  if (!L) return Promise.resolve();
  const status = (v: string) => L.api(`/api/sources/${p.id}/status`, { status: v });
  const redraw = (): void => {
    L.afkStale("/api/today", "/api/sources", "/api/topics"); void L.loadHost(); L.render();
  };
  return L.act(btn, () => status("retired"), () => {
    redraw();
    after?.();
    L.toast(`Dismissed ${p.label}: not watched, and not proposed again.`, () => void status("proposed").then(() => {
      redraw();
      L.toast(`${p.label} is proposed again.`);
    }));
  });
}
/** approve what is ticked, in one request (POST /api/sources/approve; a wildcard is watched with
 * no topic, so wildcards are a second); how many were */
export async function watchTicked(tid: number | string, rows: Pick<Proposal, "id" | "review" | "role">[], ticked: Set<number>): Promise<number> {
  const L = app()!;
  const todo = rows.filter((p) => ticked.has(p.id) && p.review !== "approved");
  const core = todo.filter((p) => p.role !== "wildcard").map((p) => p.id), wild = todo.filter((p) => p.role === "wildcard").map((p) => p.id);
  if (core.length) await L.api("/api/sources/approve", { ids: core, topic: Number(tid) });
  if (wild.length) await L.api("/api/sources/approve", { ids: wild, topic: null });
  L.afkDrop();
  return todo.length;
}
/** items a day before filtering, of the rows given */
export const perDay = (rows: Proposal[]): number => rows.reduce((a, s) => a + (s.items_per_day != null ? s.items_per_day : ((s.validation || {}).recent || 0) / 30), 0);
export const about = (n: number): string => (n >= 10 ? String(Math.round(n)) : n.toFixed(1));
