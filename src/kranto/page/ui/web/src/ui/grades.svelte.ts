// Grading: one control, on idea cards and evidence only: ▲ useful, ▼ not useful
// (a wrong reading is a ▼ with its why chip). A second press on the same glyph clears it (a "skip"
// row, so the history stays). It posts to the server's /api/feedback, presses the glyph in place and
// says in a toast what the grade does (the server's taste: cards like it rank higher or lower; the
// source rule: enough downvotes and Kranto asks whether to remove the source), with Undo. It never
// redraws the page, so the list does not move. GRADED keeps what was pressed on this page load
// (reactive: the components follow it; paintGrade presses a control drawn outside them), so the
// five-second redraw does not flip a glyph back before the server's own lists catch up.
import { flushSync, mount, unmount } from "svelte";
import type { FeedbackChip, FeedbackVocabulary } from "../api/afk.gen";
import { read } from "../lib/reads.svelte";
import { app } from "../lib/shell.svelte";
import WhyPop from "./WhyPop.svelte";

/** a grade as this page load knows it */
export interface Given {
  value: string;
  reasons: string[];
}
/** one why chip of the server's vocabulary (/api/feedback/vocabulary, generated) */
export type Chip = FeedbackChip;
/** what a grade's post carries besides the grade: its words for the toast, its origin and context,
 * its reasons and note, quiet (no toast), current (the server's grade) and done (after it posted) */
export interface GradeOpts {
  what?: string;
  origin?: string;
  context?: Record<string, unknown>;
  reasons?: string[];
  note?: string | null;
  quiet?: boolean;
  current?: unknown;
  undone?: boolean;
  done?: ((g: Given | null) => void) | null;
}

export const GLYPHS: [string, string, string, string, string][] = [["useful", "▲", "Useful", "up", "1"], ["not_useful", "▼", "Not useful", "dn", "2"]];
export const GWORD: Record<string, string> = { useful: "useful", not_useful: "not useful", wrong: "wrong", missed: "missed", skip: "cleared" };
export const GNOUN: Record<string, string> = { observation: "the observation", idea: "the card" };
/** "target:id" -> what was pressed on this page load (null: cleared) */
export const GRADED: Record<string, Given | null> = $state({});
/** what a page head drew, by "target:id": a key (a–f) knows the grade's reasons */
export const WHYCUR: Record<string, unknown> = {};
export const gkey = (t: string, id: number | string): string => t + ":" + id;
export const gval = (x: unknown): string | null =>
  x == null ? null : typeof x === "string" ? x : ((x as { value?: string; grade?: string }).value || (x as { grade?: string }).grade || null);
/** the grade shown: what was pressed on this page load, else the server's (current) */
export function gradeOf(target: string, id: number | string, current: unknown): Given | null {
  const k = gkey(target, id);
  if (Object.hasOwn(GRADED, k)) return GRADED[k] ?? null;
  const v = gval(current);
  return v && v !== "skip" ? { value: v, reasons: ((current as { reasons?: string[] } | null)?.reasons) || [] } : null;
}
/** a card's grade as this page load knows it: what was just pressed, else the server's */
export const cardGrade = (number: number | string | null | undefined, server: unknown): string | null => {
  const g = number == null ? null : gradeOf("idea", number, server);
  return g ? g.value : null;
};
/** the latest grades of a list's rows, for lists whose JSON does not carry them (the server's
 * GET /api/feedback?target=&ids=) */
export const gradesPath = (target: string, ids: (number | string)[]): string =>
  `/api/feedback?target=${target}&ids=${ids.map((i) => encodeURIComponent(i)).join(",")}`;

/** What a grade does, in the toast: a card's grade moves the cards like it; an
 * observation's moves the cards near it and counts toward its source's removal */
export function gradeEffect(target: string, value: string, what: string): string {
  if (value === "skip") return `Cleared the grade on ${what}.`;
  const up = value === "useful";
  const said = `Graded ${what} ${GWORD[value] || value}.`;
  if (target === "idea") return `${said} Cards like it rank ${up ? "higher" : "lower"} from now.`;
  if (target === "observation") return `${said} Cards near it rank ${up ? "higher" : "lower"}` + (up ? "." : "; enough downvotes on one source and Kranto asks whether to remove it.");
  return `${said} Kept with ${GNOUN[target] || "it"}.`;
}
/** a grade's controls on the page, pressed in place (the components follow GRADED too) */
export function paintGrade(k: string, g: Given | null): void {
  for (const w of document.querySelectorAll<HTMLElement>(`[data-grade="${CSS.escape(k)}"]`)) {
    w.dataset.value = g ? g.value : "";
    for (const b of w.querySelectorAll<HTMLElement>("button")) b.setAttribute("aria-pressed", g && b.dataset.v === (g.value === "wrong" ? "not_useful" : g.value) ? "true" : "false");
  }
  for (const c of document.querySelectorAll(`[data-chips="${CSS.escape(k)}"]`)) {
    for (const b of c.querySelectorAll<HTMLButtonElement>("button[data-chip]")) { b.disabled = !g; b.setAttribute("aria-pressed", g && (g.reasons || []).includes(b.dataset.chip || "") ? "true" : "false"); }
  }
}
const toast = (text: string, undo?: (() => void) | null, kind?: string): void => app()?.toast(text, undo, kind);
/** post one grade row */
export async function postGrade(target: string, id: number | string, value: string, o: GradeOpts = {}): Promise<boolean> {
  const L = app();
  if (!L) return false;
  const k = gkey(target, id), before = Object.hasOwn(GRADED, k) ? GRADED[k] ?? null : gradeOf(target, id, o.current);
  const after = value === "skip" ? null : { value, reasons: o.reasons || [] };
  GRADED[k] = after; paintGrade(k, after);
  try {
    await L.api("/api/feedback", { target, target_id: String(id), value, reasons: o.reasons || [], note: o.note || undefined, origin: o.origin || "ui",
      context: { route: location.hash.slice(1, 120), ...(o.context || {}) } });
  } catch (e) {
    GRADED[k] = before; paintGrade(k, before);
    toast("Not graded: " + (e as Error).message, null, "red");
    return false;
  }
  if (!o.quiet) toast(o.note ? `Note kept with ${o.what || GNOUN[target]}.` : gradeEffect(target, value, o.what || GNOUN[target] || target),
    () => void postGrade(target, id, before ? before.value : "skip", { ...o, reasons: before ? before.reasons : [], note: null, quiet: false, undone: true, done: null }));
  if (o.done) o.done(after);
  return true;
}
/** the "why" chips, from the server's vocabulary: they attach to the grade, so
 * they wait for one; a second press takes a chip off */
export function chipsOf(target: string): Chip[] {
  if (!app()?.host()) return [];
  return read<FeedbackVocabulary>("/api/feedback/vocabulary", 3600000).data?.chips[target] || [];
}
export function toggleChip(target: string, id: number | string, chip: string, o: GradeOpts = {}): Promise<void> {
  const g = gradeOf(target, id, o.current); if (!g) return Promise.resolve();
  const rs = (g.reasons || []).includes(chip) ? g.reasons.filter((x) => x !== chip) : [...(g.reasons || []), chip];
  return postGrade(target, id, g.value, { ...o, reasons: rs, quiet: true }).then((ok) => { if (ok) toast(`Kept "${chip.replace(/_/g, " ")}" with the grade.`); });
}
/** + note: a few words kept with the grade (read by people, never parsed) */
export function noteDialog(target: string, id: number | string, o: GradeOpts = {}): void {
  const ta = document.createElement("textarea");
  ta.id = "grade-note"; ta.setAttribute("aria-label", "Note");
  ta.placeholder = "Anything worth remembering about this. Kept with the grade; read by people, never parsed.";
  const g = gradeOf(target, id, o.current);
  app()?.dialog("A note on " + (o.what || GNOUN[target] || target), [ta], "Keep note", async (btn, close) => {
    if (!ta.value.trim()) { ta.focus(); return; }
    (btn as HTMLButtonElement).disabled = true;
    if (await postGrade(target, id, g ? g.value : "skip", { ...o, reasons: g ? g.reasons : [], note: ta.value.trim() })) close(); else (btn as HTMLButtonElement).disabled = false;
  });
}
/** the why chips of one grade, in the popover (WhyPop): each press keeps or takes off its chip;
 * + note. Opened by a grade (auto), the keys stay where they were; on why ▾, the first chip
 * takes the focus. While it is open, a–f are its chips. */
export function whyPop(anchor: HTMLElement, target: string, id: number | string, o: GradeOpts = {}, auto = false): void {
  const L = app();
  if (!L) return;
  const k = gkey(target, id);
  if (!gradeOf(target, id, WHYCUR[k])) { toast("Grade it first (▲ or ▼), then say why."); return; }
  const box = document.createElement("div");
  const inst = mount(WhyPop, { target: box, props: { target, id, o } });
  flushSync();
  const el = L.popover(anchor, "Why?", [...box.childNodes], { why: true, onclose: () => void unmount(inst) });
  el.addEventListener("keydown", (e) => { const b = el.querySelectorAll<HTMLElement>("button.chip")["abcdef".indexOf(e.key)]; if (b && e.key.length === 1) { e.preventDefault(); b.click(); } });
  if (!auto) el.querySelector<HTMLElement>("button.chip")?.focus();
}
