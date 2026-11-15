// The pages: every route's page is components, drawn in the list and detail panes.
// The app's renderList and renderDetail (lib/app/route.ts) ask pageFor(node, "list" | "pane") and
// show the page in #rows or #dscroll (showPage); a later draw of the same page only updates its
// props, so the component keeps its state (a half-typed field, an open fold). Another page
// unmounts it (dropPage).
//
// Pages register themselves by their route's node (pages/index.ts): "settings/access" draws the
// list and the pane of #/settings/access and of its selected rows. A page is loaded the first
// time its route is opened (lazy(): its own chunk, so the page's first load stays small); until
// it has arrived the pane says Loading…, and its arrival draws the page again (onPageLoaded).
// A stage route (nodes.json's stage: #/hello, #/welcome) registers its page as its list: the
// stage is the list pane at full width (body.stage), and renderDetail draws no pane there.
import { flushSync, mount, unmount, type Component } from "svelte";
import type { Route } from "./router";

/** the app's where(): the route, the navigator entry it lights, the object in the pane */
export interface Where {
  r: Route;
  node: string | null;
  list: string[];
  object: string | null;
  obj: string[] | null;
  id: string | null;
  sel: boolean;
  stage: boolean;
  missing: boolean;
}
/** what a page's components get: the route, "‹ Back to the list"'s address when an object is
 * open, and a count of the draws (a read since then may be stale) */
export interface View {
  w: Where;
  back: string | null;
  tick: number;
}
/** the list pane, the detail pane (the doors' sheet), and with the doors on the pane drawn in the
 * column (an inline pane: what a page is about, with nothing chosen) */
export type Which = "list" | "pane" | "inline";
export type PageComponent = Component<{ view: View }>;
/** a component loaded when first needed */
export interface Lazy {
  load: () => Promise<{ default: PageComponent }>;
  comp: PageComponent | null;
  loading: Promise<void> | null;
}
export const lazy = (load: Lazy["load"]): Lazy => ({ load, comp: null, loading: null });
export type PagePart = PageComponent | Lazy;
export interface Page {
  list?: PagePart;
  pane?: PagePart;
}

export const PAGES: Record<string, Page> = {};
export function register(node: string, page: Page): void {
  PAGES[node] = page;
}
/** The page drawn at a node: registered under the node itself, else under its route's node, whose
 * ":x" stands for one segment ("topics/5/evidence" is "topics/:id/evidence"; "topics/new", being
 * registered itself, is never "topics/:id") */
export function pageFor(node: string | null | undefined, which: "list" | "pane"): PagePart | null {
  if (!node) return null;
  if (PAGES[node]) return PAGES[node][which] || null;
  const parts = node.split("/");
  for (const [k, p] of Object.entries(PAGES)) {
    const ks = k.split("/");
    if (k.includes(":") && ks.length === parts.length && ks.every((s, i) => s[0] === ":" || s === parts[i])) return p[which] || null;
  }
  return null;
}
const isLazy = (p: PagePart): p is Lazy => typeof p === "object" && p !== null && "load" in p;

let loaded: () => void = () => {};
/** what a page's arrival sets off: the page is drawn again (main.ts) */
export function onPageLoaded(f: () => void): void {
  loaded = f;
}

interface Mounted {
  comp: PageComponent;
  box: HTMLElement;
  view: View;
  app: Record<string, unknown>;
}
const MOUNTED: Record<Which, Mounted | null> = { list: null, pane: null, inline: null };

/** draw a moved page into its pane: mount it, or update the one already there */
export function showPage(which: Which, box: HTMLElement, part: PagePart, w: Where, back: string | null = null): void {
  let comp: PageComponent | null = part as PageComponent;
  if (isLazy(part)) {
    comp = part.comp;
    if (!comp) {
      part.loading ||= part.load().then((m) => {
        part.comp = m.default;
        loaded();
      }, () => {
        part.loading = null; // a later draw tries again
      });
      dropPage(which);
      const p = document.createElement("p");
      p.className = "empty";
      p.textContent = "Loading…";
      box.replaceChildren(p);
      return;
    }
  }
  const m = MOUNTED[which];
  if (m && m.comp === comp && m.box === box && box.isConnected) {
    m.view.w = w;
    m.view.back = back;
    m.view.tick += 1;
    flushSync(); // drawn now: the app marks the selection and the hints from the DOM next
    return;
  }
  dropPage(which);
  box.replaceChildren();
  const view = $state<View>({ w, back, tick: 0 });
  MOUNTED[which] = { comp, box, view, app: mount(comp, { target: box, props: { view } }) };
  flushSync();
}
/** the pane's page goes */
export function dropPage(which: Which): void {
  const m = MOUNTED[which];
  if (!m) return;
  MOUNTED[which] = null;
  void unmount(m.app);
}
export const shownPage = (which: Which): PageComponent | null => MOUNTED[which]?.comp || null;
