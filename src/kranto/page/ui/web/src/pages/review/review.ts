// Review, the weekly queue (LEARNING.md 3.4, #/review): the types and the pure helpers of the list
// and the pane. the server's GET /api/review/queue builds the queue: only what a grade is read for
//, this week's cards in the order of what they stand on, themes and observations. The
// doors' count and Needs you's row read the same path (reviewCount, QueuePane). The queue's shapes
// are generated from the server's web/types.py (api/afk.gen.ts).
import type { QueueItem } from "../../api/afk.gen";
import { href } from "../../lib/router";
export type { QueueItem, ReviewQueue as Queue } from "../../api/afk.gen";

/** an item's kind, in words */
export const KINDWORD: Record<string, string> = { idea: "card", cluster: "theme", observation: "observation" };
/** the queue (nothing you kicked off is graded here) */
export const REVIEW_API = "/api/review/queue";
/** about 20 s an item */
export const reviewMinutes = (n: number): number => Math.max(1, Math.round(n * 20 / 60));
/** the items the page grades: an older the server's build items are left out (never graded:) */
export const gradable = (xs: readonly QueueItem[]): QueueItem[] => xs.filter((x) => x.target !== "build");

/** an item's title: the queue's */
export const reviewTitle = (x: QueueItem): string => x.title || `${x.target} ${x.id}`;
/** an item's own page (enter opens it): a card's (#/ideas/<n>: the card itself, H1) */
export function reviewHref(x: QueueItem): string | null {
  if (x.target === "idea") return href("ideas/" + x.id);
  return null;
}
/** an item in a toast and the grade's words: "card #117" */
export const reviewWhat = (x: QueueItem): string => `${KINDWORD[x.target] || x.target} #${x.id}`;
