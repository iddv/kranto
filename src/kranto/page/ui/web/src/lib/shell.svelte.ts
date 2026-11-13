// The shell's state: what the frame draws, as one reactive object. The app
// (./app) works out the facts the chrome shows (chromeFacts); frame() asks it for them after every
// draw, and the header, the navigator, the status bar and the list's head redraw from ui.facts.
// The app imports this module; this one imports only its types, and main.ts connects the two at
// run time (the tests connect a stub: pages/testing.svelte.ts).
import type { App, Facts } from "./app";
import type { HeadDecl } from "./app/heads";
import { parse, type Route } from "./router";

/** theme.js's kranto.layout: the splitters' widths, kept per browser. */
export interface LayoutState {
  nav?: number;
  detail?: number;
  icons?: boolean;
}
export interface Layout {
  read(): LayoutState;
  save(x: LayoutState): void;
  apply(x?: LayoutState): { nav: number; det: number | null; icons: boolean; wide: boolean; mid: boolean };
  NAV: { min: number; max: number; icons: number; def: number };
  DET: { min: number };
  LIST: number;
  SPLIT: number;
}
declare global {
  interface Window {
    krantoLayout?: Layout;
  }
}
// theme.js runs first in <head>; without it (a component test) the widths are kranto.css's
const NO_LAYOUT: Layout = {
  read: () => ({}),
  save: () => {},
  apply: () => ({ nav: 224, det: null, icons: false, wide: true, mid: false }),
  NAV: { min: 168, max: 400, icons: 56, def: 224 },
  DET: { min: 360 },
  LIST: 320,
  SPLIT: 6,
};
export const LAYOUT: Layout = {
  read: () => (window.krantoLayout || NO_LAYOUT).read(),
  save: (x) => (window.krantoLayout || NO_LAYOUT).save(x),
  apply: (x) => (window.krantoLayout || NO_LAYOUT).apply(x),
  get NAV() { return (window.krantoLayout || NO_LAYOUT).NAV; },
  get DET() { return (window.krantoLayout || NO_LAYOUT).DET; },
  get LIST() { return (window.krantoLayout || NO_LAYOUT).LIST; },
  get SPLIT() { return (window.krantoLayout || NO_LAYOUT).SPLIT; },
};

class Shell {
  /** what the chrome shows, from the app after each draw */
  facts = $state.raw<Facts | null>(null);
  /** one more on every draw */
  drawn = $state(0);
  /** the navigator as a drawer under 1180 px (☰) */
  navOpen = $state(false);
  /** the first key of a chord ("g"), for 1.5 s */
  chord = $state<string | null>(null);
  /** the palette while it is open (a new object each time it opens), else null */
  palette = $state<{ text: string } | null>(null);
  /** the splitter that has the focus (its keys show in the status bar) */
  split = $state<string | null>(null);
  /** the navigator as 56 px icons */
  icons = $state(false);
  /** the doors' one sheet is open: the detail pane over a dimmed page, a dialog;
   * its title for the dialog's label */
  sheet = $state(false);
  sheetTitle = $state("");
  /** the area drawn (the route's first part: "settings", "builds"…): Settings says every
   * glyph's word beside it (UP #10) */
  area = $state("");
  /** the page's head: headOn while the shell draws it (the doors' pages, either
   * layout), so a page declares its title instead of drawing it; head is the declaration */
  headOn = $state(false);
  head = $state.raw<(HeadDecl & { n: number }) | null>(null);
  /** each splitter's bounds and width, for its aria-value* */
  aria = $state<Record<string, { min: number; max: number; now: number }>>({
    nav: { min: 0, max: 0, now: 0 },
    detail: { min: 0, max: 0, now: 0 },
  });
}
export const ui = new Shell();

let L: App | null = null;
/** main.ts hands the app over before the frame mounts */
export function connect(a: App | null): void {
  L = a;
}
export const app = (): App | null => L;

/** the chrome again, from the app's state (it calls this after every draw) */
export function frame(r: Route = parse()): void {
  ui.icons = iconsNow();
  ui.area = r.path[0] || "";
  if (L) ui.facts = L.chromeFacts(r);
  ui.drawn++;
}

/** twists opened or closed by hand, for this page load: "t<id>" a topic, "lib" the library,
 * "ptop" the project topics; "-" marks one closed by hand (the page stores nothing but the
 * theme and the widths) */
export const NAVOPEN_T = new Set<string>();
export function navToggle(k: string, open: boolean): void {
  NAVOPEN_T.delete(open ? k : "-" + k);
  NAVOPEN_T.add(open ? "-" + k : k);
  frame();
}
export function navDrawer(open: boolean): void {
  ui.navOpen = open;
}
export const iconsNow = (): boolean => document.documentElement.classList.contains("nav-icons");

/** the navigator as icons, kept in kranto.layout; ignored where the
 * navigator is the drawer */
export function navIcons(on: boolean): void {
  const l = LAYOUT.read();
  if (on) {
    l.icons = true;
    delete l.nav;
  } else delete l.icons;
  LAYOUT.save(l);
  LAYOUT.apply(l);
  splitAria();
  frame();
}
/** ⌘K and the ? sheet: every width back to its default */
export function layoutReset(): void {
  LAYOUT.save({});
  LAYOUT.apply({});
  splitAria();
  frame();
}

/** ⌘K: the palette, unless it is open. Pressed again right after esc, the old palette's close
 * event has not arrived yet: this one opens anyway, and that close must not clear it
 * (Palette.svelte's closed()). */
export function openPalette(text = ""): void {
  if ((document.getElementById("pal") as HTMLDialogElement | null)?.open) return;
  ui.palette = { text };
}

const colNow = (col: string): number =>
  document.getElementById(col === "nav" ? "nav" : "detail")?.getBoundingClientRect().width || 0;
/** a column's least and most width in this window */
export function splitBounds(col: string): [number, number] {
  const W = innerWidth;
  if (col === "nav") return [LAYOUT.NAV.min, LAYOUT.NAV.max];
  const max = Math.max(
    LAYOUT.DET.min,
    Math.min(W * (W >= 1180 ? 0.7 : 0.6), W - (W >= 1180 ? colNow("nav") + 2 * LAYOUT.SPLIT : LAYOUT.SPLIT) - LAYOUT.LIST),
  );
  return [LAYOUT.DET.min, Math.round(max)];
}
export function splitAria(): void {
  for (const col of ["nav", "detail"]) {
    const [min, max] = splitBounds(col);
    ui.aria[col] = { min, max, now: Math.round(colNow(col)) };
  }
}
/** one column to a width: clamped by theme.js's apply; kept when save */
export function splitTo(col: string, px: number, save: boolean): LayoutState {
  const l = LAYOUT.read();
  const [lo, hi] = splitBounds(col);
  l[col as "nav" | "detail"] = Math.round(Math.max(lo, Math.min(hi, px)));
  if (col === "nav") delete l.icons;
  LAYOUT.apply(l);
  if (save) LAYOUT.save(l);
  splitAria();
  return l;
}
/** a double-click: that column's default again */
export function splitReset(col: string): void {
  const l = LAYOUT.read();
  delete l[col as "nav" | "detail"];
  if (col === "nav") delete l.icons;
  LAYOUT.save(l);
  LAYOUT.apply(l);
  splitAria();
  if (col === "nav") frame();
}
export { colNow };
