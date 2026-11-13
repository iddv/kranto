// Review's state and its flow (LEARNING.md 3.4; WORKSPACE.md 2.10): one item at a time; keys only
// (QUEUE_KEYS in lib/keys.json, queueAction in lib/keys.ts), the pointer works too. A grade moves
// on by itself to the next ungraded item; a chip letter after it attaches to the item just
// graded. The queue is read once per visit and kept (Q, for the list and the pane alike), so
// "7 of 14" holds while grading; a press draws the page again (the old module's render(), which
// marks the current row selected and sets the page's keys again).
import { parse } from "../../lib/router";
import { app } from "../../lib/shell.svelte";
import { queueAction, type QueueAction } from "../../lib/keys";
import { chipsOf, gradeOf, GWORD, noteDialog, postGrade, toggleChip } from "../../ui/grades.svelte";
import { gradable, KINDWORD, REVIEW_API, reviewHref, reviewTitle, reviewWhat, type Queue, type QueueItem } from "./review";

export interface Review {
  /** the queue's path as read */
  path: string | null;
  items: QueueItem[] | null;
  week: string | null;
  /** the current item (items.length: done) */
  at: number;
  /** the item graded just before, for its chips */
  last: number | null;
  grades: number;
  chips: number;
  skips: number;
  /** what was given each item, in words ("useful", "skipped"; null: cleared) */
  given: Record<number, string | null>;
  error: string | null;
}
const fresh = (path: string | null): Review => ({ path, items: null, week: null, at: 0, last: null, grades: 0, chips: 0, skips: 0, given: {}, error: null });
export const Q: Review = $state(fresh(null));

const redraw = (): void => app()?.render();
/** the queue's path (the doors' count reads the same) */
export const pathNow = (): string => REVIEW_API;
export const titleOf = (x: QueueItem): string => reviewTitle(x);
export const hrefOf = (x: QueueItem): string | null => reviewHref(x);
export const whatOf = (x: QueueItem): string => reviewWhat(x);

/** read the queue, once per visit unless its path changed (or force: Read the queue again) */
export function reviewLoad(path: string, force = false): void {
  if (Q.path === path && !force) return;
  Object.assign(Q, fresh(path));
  const L = app();
  if (!L) return;
  (L.api(path) as Promise<Queue>).then((d) => {
    if (Q.path !== path) return;
    Q.items = gradable(d.items);
    Q.week = d.week || null;
    if (parse().path[0] === "review") redraw();
  }).catch((e: Error) => {
    if (Q.path !== path) return;
    Q.error = e.message;
    redraw();
  });
}
/** the next ungraded item, after the current one */
export function reviewAdvance(): void {
  if (!Q.items) return;
  Q.last = Q.at;
  let i = Q.at + 1;
  while (i < Q.items.length && Q.given[i]) i++;
  Q.at = Math.min(Q.items.length, i);
  app()?.afkDropPrefix("/api/review/queue"); // the navigator's count, read again
  redraw();
}
const graded = (x: QueueItem | null | undefined): boolean => !!x && !!gradeOf(x.target, x.id, null);
/** the item a chip goes on: the current one once graded, else the one just graded (its index) */
export function reviewChipTarget(): number | null {
  if (!Q.items) return null;
  if (graded(Q.items[Q.at])) return Q.at;
  return Q.last != null && graded(Q.items[Q.last]) ? Q.last : null;
}
/** a grade given item i, counted and kept in words (the keys, the pane's glyphs and a row's) */
export function reviewGiven(i: number, value: string | null): void {
  Q.grades++;
  Q.given[i] = value ? GWORD[value] ?? value : null;
}
/** carry out one of the queue's actions (queueAction's, or a press) */
export function reviewDo(a: QueueAction | null): void {
  if (!Q.items || !a) return;
  const x = Q.items[Q.at];
  if (a.do === "next") { Q.at = Math.min(Q.items.length, Q.at + 1); redraw(); return; }
  if (a.do === "prev") { Q.at = Math.max(0, Q.at - 1); redraw(); return; }
  if (!x) return;
  const L = app();
  const ctx = { slot: x.slot, position: Q.at + 1 }, what = whatOf(x);
  if (a.do === "grade" && a.value) { reviewGiven(Q.at, a.value); void postGrade(x.target, x.id, a.value, { what, origin: "review", context: ctx }); reviewAdvance(); }
  else if (a.do === "skip") {
    Q.skips++; Q.given[Q.at] = "skipped";
    void postGrade(x.target, x.id, "skip", { what, origin: "review", context: ctx, quiet: true });
    L?.toast(`Skipped ${what}: it comes back next week.`);
    reviewAdvance();
  } else if (a.do === "chip") {
    const ti = reviewChipTarget(), t = ti == null ? null : Q.items[ti], c = t && chipsOf(t.target)[a.at ?? 0];
    if (!t || !c) return;
    Q.chips++;
    void toggleChip(t.target, t.id, c.key, { origin: "review", context: { slot: t.slot } }).then(() => redraw());
  } else if (a.do === "note") {
    const ti = reviewChipTarget(), t = ti != null ? Q.items[ti] : x;
    if (t) noteDialog(t.target, t.id, { origin: "review", what: KINDWORD[t.target] });
  } else if (a.do === "open") {
    const l = hrefOf(x);
    if (l) location.hash = l;
  }
}
/** a key of the queue (QUEUE_KEYS), pressed: what it does here and now */
export function reviewKey(key: string): void {
  if (!Q.items) return;
  const ti = Q.at < Q.items.length ? reviewChipTarget() : null, t = ti == null ? null : Q.items[ti];
  reviewDo(queueAction(key, { chipTarget: !!t, chips: t ? chipsOf(t.target).length : 0, done: Q.at >= Q.items.length }));
}
/** the list's row pressed: that item is the current one */
export function reviewPick(i: number): void {
  Q.last = null;
  Q.at = i;
  redraw();
}
/** Read the queue again (the pane's, when done) */
export function reviewAgain(): void {
  app()?.afkDropPrefix("/api/review/queue");
  reviewLoad(pathNow(), true);
  redraw();
}
