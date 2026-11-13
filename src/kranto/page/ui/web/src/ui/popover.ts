// The one popover (Pass, Reject, a theme's Watch, a ? tip, ⋯'s menu): anchored to a button,
// one at a time; esc, a click elsewhere or a route change closes it. While it is open the page is
// not redrawn (typing()).
//
// ⋯ and the row's menu: one menu for the verbs past a pane's primary row
// (⋯, or .) and for a row's (right-click, a long press, or . on the selected row). Its items are
// the verbs the pane or the row draws (from the registry for a build), so a verb is in the menu,
// on its key and in ⌘K at once, never in one place only. Arrow keys move, Home and End, enter
// runs, esc closes and the focus goes back. A verb that is not on now is greyed, with its why.
import { flushSync, mount, unmount } from "svelte";
import Menu from "./Menu.svelte";
import type { MenuItem } from "../lib/app/types";

interface Pop {
  el: HTMLElement;
  anchor: HTMLElement;
  away: (e: MouseEvent) => void;
  /** a grade's why chips: a–f press them while it is open */
  why: HTMLElement | null;
  onclose: (() => void) | null;
}
let POP: Pop | null = null;
/** a long press on a row opened its menu: its own mousedown must not close it */
let PRESSED = false;
export const pressed = (on: boolean): void => {
  PRESSED = on;
};
/** the menu's anchor while one of its items runs: a popover it opens sits there */
let MENUREF: HTMLElement | null = null;

export const popNow = (): Pop | null => POP;

/** the popover closed (refocus: its anchor takes the focus back) */
export function closePop(refocus?: boolean): void {
  if (!POP) return;
  const P = POP;
  POP = null;
  P.el.remove();
  document.removeEventListener("mousedown", P.away, true);
  if (P.onclose) P.onclose();
  if (refocus !== false && P.anchor && P.anchor.isConnected) P.anchor.focus();
}
/** under its anchor (else under the menu it came from, else the pane's ⋯), inside the window */
function place(el: HTMLElement, anchor: HTMLElement): void {
  const ref = anchor.isConnected ? anchor : MENUREF && MENUREF.isConnected ? MENUREF
    : (document.querySelector("#dscroll .dh .btn.more") as HTMLElement | null) || (document.getElementById("dscroll") as HTMLElement);
  const r = ref.getBoundingClientRect(), w = Math.min(el.offsetWidth || 320, innerWidth - 16);
  el.style.top = scrollY + r.bottom + 6 + "px";
  el.style.left = Math.max(8, Math.min(scrollX + r.left, scrollX + innerWidth - w - 8)) + "px";
}
/** the one popover under anchor: o.why marks a grade's why chips, o.onclose runs when it closes */
export function popover(anchor: HTMLElement, label: string, kids: Node[], o?: { why?: boolean; onclose?: () => void }): HTMLElement {
  closePop(false);
  const el = document.createElement("div");
  el.className = "pop";
  el.setAttribute("role", "dialog");
  el.setAttribute("aria-label", label);
  el.append(...kids);
  const away = (e: MouseEvent) => {
    if (PRESSED) return; // a long press's own mousedown keeps its menu
    if (!el.contains(e.target as Node) && e.target !== anchor) closePop();
  };
  el.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      closePop();
    }
  });
  document.body.append(el);
  place(el, anchor);
  document.addEventListener("mousedown", away, true);
  POP = { el, anchor, away, why: o && o.why ? el : null, onclose: (o && o.onclose) || null };
  return el;
}
if (typeof addEventListener === "function") addEventListener("hashchange", () => closePop());

/** what a button says, less its key and its icon */
export const actLabel = (el: Element): string =>
  [...el.childNodes].filter((n) => !(n.nodeType === 1 && ((n as Element).tagName === "KBD" || (n as Element).tagName.toLowerCase() === "svg"))).map((n) => n.textContent).join("").trim();
function actRun(el: HTMLElement): () => void {
  if (el.tagName === "A") return () => {
    const a = el as HTMLAnchorElement, u = a.getAttribute("href") || "";
    if (a.target === "_blank") window.open(u, "_blank", "noopener");
    else if (u.startsWith("#")) location.hash = u;
    else location.href = u;
  };
  return () => el.click();
}
/** a button or a link drawn on a row, as a menu's item */
export const menuItem = (el: HTMLElement): MenuItem => {
  const off = el.hidden || (el as HTMLButtonElement).disabled;
  return { label: actLabel(el) || el.getAttribute("aria-label") || el.title || "?", key: (el.querySelector("kbd") || {}).textContent || null, group: el.dataset.group || "",
    why: off ? el.title || "Not now" : null, title: off ? null : el.title || null, run: actRun(el), id: el.id || null };
};

/** ⋯'s menu under anchor (or at a point: a right-click, a long press) */
export function menu(anchor: HTMLElement, items: MenuItem[], label?: string, at?: { x: number; y: number }): HTMLElement {
  let app: Record<string, unknown> | null = null;
  const el = popover(anchor, label || "More actions", [], { onclose: () => { if (app) void unmount(app); app = null; } });
  const press = (x: MenuItem) => {
    if (x.why) return;
    closePop(false);
    MENUREF = anchor;
    try {
      x.run(anchor);
    } finally {
      MENUREF = null;
    }
  };
  app = mount(Menu, { target: el, props: { items, press } });
  flushSync();
  el.classList.add("menu");
  el.setAttribute("role", "menu");
  place(el, anchor); // its width is known now
  if (at) {
    el.style.top = scrollY + at.y + 2 + "px";
    el.style.left = Math.max(8, Math.min(scrollX + at.x, scrollX + innerWidth - el.offsetWidth - 8)) + "px";
  }
  const bs = () => [...el.querySelectorAll<HTMLElement>("button[role=menuitem]")];
  el.addEventListener("keydown", (e) => {
    const xs = bs(), i = xs.indexOf(document.activeElement as HTMLElement);
    const to = (n: number) => {
      e.preventDefault();
      xs[(n + xs.length) % xs.length]!.focus();
    };
    if (e.key === "ArrowDown") to(i + 1);
    else if (e.key === "ArrowUp") to(i - 1);
    else if (e.key === "Home") to(0);
    else if (e.key === "End") to(xs.length - 1);
    else if (e.key === "Tab") {
      e.preventDefault();
      closePop();
    }
  });
  (bs().find((b) => !b.getAttribute("aria-disabled")) || bs()[0])?.focus();
  return el;
}
