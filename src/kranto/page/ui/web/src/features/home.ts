// The home as widgets: what the server's GET /api/home answers, and the
// facts the page draws the grid from. The arrangement itself (which widgets, in which order, at
// which size) comes with GET /api/shell, read before the first draw, so the home never draws one
// order and then another; /api/home carries what the widgets show: each cub widget's answer
// (checked and capped by the server) and the cubs' rows for Needs you and New today, in one read
// where 0.5.10 made one read a cub. A widget is data: the page draws its kind, never its markup.
import { drop, put, read, type Read } from "../lib/reads.svelte";
import { app } from "../lib/shell.svelte";
import { toast } from "../ui/toast.svelte";
import { SHELL_API, type Arrangement } from "./shell";
import type { HomeToday } from "../api/afk.gen";

export const HOME_API = "/api/home";
/** the home was seen (POST): the ordinary home says so as it draws; While you were away only when
 * one of its rows is opened or Show today chosen */
export const VISIT_API = HOME_API + "/visit"; // joined, so no literal reads like a home folder (test_no_internal_refs)
export type Size = "S" | "M" | "L";
export type WidgetKind = "stat" | "rows" | "series" | "table" | "stages" | "note";
export const WIDGET_KINDS: WidgetKind[] = ["stat", "rows", "series", "table", "stages", "note"];
/** the seven parts of 0.5.10's home, in its order: the default whenever shell.widgets is unset */
export const DEFAULT_HOME = ["greeting", "status", "needs", "doors", "new", "cubs", "foot"];
/** columns of six a size takes: S two, M three, L the row */
export const SPAN: Record<Size, number> = { S: 2, M: 3, L: 6 };

/** one place on the home, as the server resolves shell.widgets */
export interface HomeEntry {
  /** its place in the stored list (what a write keeps) */
  n: number;
  id: string;
  /** false: a widget of a feature that is gone; kept in the list, never drawn */
  known: boolean;
  size?: Size;
  phone?: boolean;
  options?: Record<string, unknown>;
  title?: string;
  sizes?: Size[];
  builtin?: boolean;
  feature?: string;
  kind?: WidgetKind;
  every_s?: number;
  open?: string | null;
  empty?: string;
  trust?: string;
}
export type SlotState = "ok" | "loading" | "stale" | "error" | "off";
/** a widget's answer: ok with its data, loading (asked again in a second), stale (the last good
 * answer, as_of), error and off in words */
export interface Slot {
  state: SlotState;
  data?: unknown;
  as_of?: string | null;
  error?: string;
}
export interface LibraryWidget {
  id: string;
  title: string;
  says: string;
  sizes: Size[];
  kind?: WidgetKind;
  many: boolean;
  on_home: boolean;
  options: string[];
}
export interface LibraryGroup {
  id: string;
  title: string;
  trust: string;
  enabled: boolean;
  widgets: LibraryWidget[];
}
/** what GET /api/home answers: the home of open-source wave 2 (the date, the
 * sentence, today's brief, the newest cards, the quiet line, While you were away), absent from an
 * older the server; and, for one wave, the widgets' keys below (a cub's widget, its rows) */
export type HomeAnswer = Partial<HomeToday> & HomeWidgets;
export interface HomeWidgets {
  widgets: HomeEntry[];
  custom: boolean;
  default: string[];
  library: LibraryGroup[];
  /** each cub widget's answer by its place n */
  slots: Record<string, Slot>;
  /** the cubs' rows of Needs you and New today, by feature */
  rows?: Partial<Record<"needs_you" | "new", Record<string, Slot>>>;
  budget_s: number;
}

/** the home's widgets in order: the arrangement's, or the default seven (an older the server) */
export function entriesOf(a: Arrangement | null): HomeEntry[] {
  if (a?.widgets) return a.widgets;
  return DEFAULT_HOME.map((id, n) => ({ n, id, known: true, size: "L", phone: true, options: {}, builtin: true }));
}
/** what draws: the widgets the page knows */
export const drawn = (es: HomeEntry[]): HomeEntry[] => es.filter((e) => e.known);
/** the one read of the home, once a minute (a widget's every_s is a minute at least) */
export const homeRead = (host: boolean, ttl = 60000): Read<HomeAnswer> | null => (host ? read<HomeAnswer>(HOME_API, ttl) : null);
/** one slot asked again (it answered loading: a cub was busy) */
export const slotPath = (n: number): string => `${HOME_API}?slot=${n}`;

// -- Arrange: every change is one write of the whole list (shell.widgets) --------

/** one entry as shell.widgets stores it */
export interface Stored {
  id: string;
  size?: Size;
  phone?: boolean;
  options?: Record<string, unknown>;
}
/** the list as written: every entry kept, the ones the page cannot draw too (a cub removed and
 * added again finds its widgets where they were) */
export function storedOf(es: HomeEntry[]): Stored[] {
  return es.map((e) => {
    const out: Stored = { id: e.id };
    if (e.known && e.size) out.size = e.size;
    if (e.phone === false) out.phone = false;
    if (e.options && Object.keys(e.options).length) out.options = { ...e.options };
    return out;
  });
}
/** the list with entry n moved one drawn place up (-1) or down (+1), past what is not drawn */
export function movedBy(es: HomeEntry[], n: number, step: -1 | 1): Stored[] {
  const s = storedOf(es), shown = es.filter((e) => e.known).map((e) => e.n), at = shown.indexOf(n);
  const to = shown[at + step];
  if (at < 0 || to === undefined) return s;
  const i = es.findIndex((e) => e.n === n), j = es.findIndex((e) => e.n === to);
  [s[i], s[j]] = [s[j]!, s[i]!];
  return s;
}
/** the list with entry n dropped where entry `to` is (drag): it takes that place, the rest follow */
export function movedTo(es: HomeEntry[], n: number, to: number): Stored[] {
  const s = storedOf(es), i = es.findIndex((e) => e.n === n), j = es.findIndex((e) => e.n === to);
  if (i < 0 || j < 0 || i === j) return s;
  const [x] = s.splice(i, 1);
  s.splice(j, 0, x!);
  return s;
}
/** the list with one entry changed (its size, its phone flag, its options) */
export function changed(es: HomeEntry[], n: number, o: Partial<Stored>): Stored[] {
  return storedOf(es).map((x, i) => {
    if (es[i]!.n !== n) return x;
    const y: Stored = { ...x, ...o };
    if (y.phone !== false) delete y.phone;
    if (y.options && !Object.keys(y.options).length) delete y.options;
    return y;
  });
}
/** the list without entry n */
export const without = (es: HomeEntry[], n: number): Stored[] => storedOf(es).filter((_, i) => es[i]!.n !== n);
/** the list with a widget added at the end, at its first size */
export const added = (es: HomeEntry[], id: string, size: Size, options?: Record<string, unknown>): Stored[] =>
  [...storedOf(es), { id, size, ...(options && Object.keys(options).length ? { options } : {}) }];
/** what Undo writes back: the list as it was, or null when it was the default */
export const before = (a: Arrangement | null): Stored[] | null => (a?.custom && a.widgets ? storedOf(a.widgets) : null);
/** the library's widgets that may be added now: what is not on the home (A topic: always) */
export const addable = (w: LibraryWidget): boolean => w.many || !w.on_home;
/** a widget's one line of sizes, as the library marks them */
export const sizesWord = (ss: Size[]): string => ss.join(" ");

/** one write of the list through the one writer, its answer drawn at once and the home read
 * again; `said` with `undo` is a toast whose Undo writes that list back (9 s) */
export function setWidgets(list: Stored[] | null, btn: HTMLElement | null = null, said?: string, undo?: Stored[] | null): Promise<void> {
  const L = app();
  if (!L) return Promise.resolve();
  return L.act(btn, async () => put(SHELL_API, await L.api(SHELL_API, { key: "shell.widgets", value: list })), () => {
    drop(HOME_API);
    if (said) toast(said, undo !== undefined ? () => void setWidgets(undo, null, "Undone: the home is as it was.") : null);
    L.render();
  });
}
/** every key Reset to default changes, as they are now: what its Undo writes back in one write */
export function arrangementValues(a: Arrangement): Record<string, unknown> {
  const out: Record<string, unknown> = { "shell.widgets": before(a), "shell.pins": a.pins, "shell.hidden": a.hidden,
    "shell.needs_cap": a.needs_cap, "shell.new_cap": a.new_cap };
  for (const c of a.cubs) {
    out[`shell.needs_you.${c.id}`] = c.needs_you;
    out[`shell.new.${c.id}`] = c.new;
  }
  return out;
}
/** Reset to default: asks nothing; the toast's Undo puts the whole arrangement
 * back in one write */
export function resetHome(a: Arrangement, btn: HTMLElement | null = null): Promise<void> {
  const L = app();
  if (!L) return Promise.resolve();
  const was = arrangementValues(a);
  return L.act(btn, async () => put(SHELL_API, await L.api(SHELL_API, { reset: true })), () => {
    drop(HOME_API);
    toast("The home is back to its default.", () => {
      void L.act(null, async () => put(SHELL_API, await L.api(SHELL_API, { values: was })), () => {
        drop(HOME_API);
        toast("Undone: the home is as it was.");
        L.render();
      });
    });
    L.render();
  });
}
