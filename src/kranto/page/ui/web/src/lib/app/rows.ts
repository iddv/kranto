// The rows and the pane, for the shell's keys (../keyboard.ts): j/k move over the list's rows (any
// li.row, or an element with data-row) and the pane follows (the selection is the focused row: one
// thing); ⇧j/⇧k jump a group; o puts the cursor in the pane; enter runs the row's primary action,
// else the pane; x ticks; [ and ] step the pane's sections; esc closes the drawer, then the ticks,
// then the selection. And the frame's own clicks: a link in the list opens its object in the pane.
import { href, matchRoute, selCode } from "../router";
import { closeTerm } from "../../term/state.svelte";
import { closePop, menu, menuItem, popNow, pressed } from "../../ui/popover";
import { ideaItems } from "../../pages/ideas/verbs";
import { ideaOf } from "../../pages/ideas/ideas";
import { backHref, linkKey, render, routeNow, selHref, selTarget, tbHeight, type W } from "./route";
import type { MenuItem } from "./types";

const ROWS = "#rows li.row, #rows [data-row]";
let FOCUS: { i: number } | null = null; // the focused row of this list
let STEPPING = false; // j/k is selecting: a pane that takes the cursor when opened (New idea) leaves it
/** j or k is selecting a row: a pane that takes the cursor when opened (New idea) leaves it */
export const stepping = (): boolean => STEPPING;
export const resetFocus = (): void => {
  FOCUS = null;
};

export const rowsNow = (): HTMLElement[] =>
  [...document.querySelectorAll<HTMLElement>(ROWS)].filter((e) => e.offsetParent !== null && !e.classList.contains("empty"));
export function focusRow(i: number, scroll: boolean): HTMLElement | null {
  const rows = rowsNow();
  if (!rows.length) {
    FOCUS = null;
    return null;
  }
  i = Math.max(0, Math.min(rows.length - 1, i));
  for (const e of document.querySelectorAll("#rows .row.focus, #rows [data-row].focus")) e.classList.remove("focus");
  rows[i]!.classList.add("focus");
  FOCUS = { i };
  if (scroll) rows[i]!.scrollIntoView({ block: "nearest" });
  return rows[i]!;
}
export const rowNow = (): HTMLElement | null => (FOCUS ? rowsNow()[FOCUS.i] || null : null);
const rowOpen = (row: Element): HTMLElement | null => row.querySelector("[data-open]") || row.querySelector("a.r-title, .r-title a, a[href]");
const rowPrimary = (row: Element): HTMLElement | null => row.querySelector(".r-act .primary") || row.querySelector(".r-act button, .r-act a.btn");

/** the selected row: the one whose sel key or link is the pane's object (by key, so a redraw keeps
 * it), or the review queue's current item (data-cur) */
export function markSel(w: W): void {
  const want = w.object === "need" || w.object === "sel" ? w.id : w.obj ? selCode(matchRoute(w.obj)!.base) : null, rows = rowsNow();
  for (const x of document.querySelectorAll("#rows .sel")) x.classList.remove("sel");
  const i = want ? rows.findIndex((x) => {
    if (x.dataset.sel) return x.dataset.sel === want;
    const a = rowOpen(x);
    return a && linkKey(a.getAttribute("href")) === want;
  }) : rows.findIndex((x) => x.dataset.cur != null);
  if (i >= 0) {
    rows[i]!.classList.add("sel");
    if (!FOCUS || FOCUS.i !== i) focusRow(i, true);
  }
}
/** a row's object into the pane: j and k replace the history entry, a click or o pushes one */
function selectRow(row: HTMLElement | null, push: boolean): boolean {
  const a = row && rowOpen(row), code = row && row.dataset.sel, R = routeNow();
  // data-go: a row whose selection is a filter of its list (a point on the map, ?p=)
  const to = (a && selTarget(a.getAttribute("href"))) || (code && R && !R.stage ? selHref(code) : null) || (row && row.dataset.go) || null;
  if (!to) return false;
  if (to !== location.hash) {
    if (push) location.hash = to;
    else {
      history.replaceState(null, "", to);
      render();
    }
  }
  return true;
}
/** o: no object has a full page of its own since builds and projects left, so o is the pane, as
 * tab is (the caller falls through to it) */
function openFull(): boolean {
  return false;
}
/** tab: the focused row's object in the pane (a phone shows the pane), the cursor there */
function openPane(): boolean {
  const row = rowNow();
  if (row && !row.classList.contains("sel") && !selectRow(row, true)) {
    const a = rowOpen(row);
    if (a) a.click();
    return !!a;
  }
  const w = routeNow();
  if (!w || !w.object) return !!row;
  document.getElementById("dscroll")!.focus({ preventScroll: true });
  return true;
}
/** ⇧j ⇧k: the first row of the next group, or of this one, then the one before */
function groupStep(dir: number): boolean {
  const rows = rowsNow();
  if (!rows.length) return false;
  const at = FOCUS ? Math.min(FOCUS.i, rows.length - 1) : -1, g = (n: number) => rows[n]!.parentElement;
  let i: number;
  if (dir > 0) i = rows.findIndex((x, n) => n > at && (at < 0 || g(n) !== g(at)));
  else {
    let s = Math.max(at, 0);
    while (s > 0 && g(s - 1) === g(s)) s--;
    if (s < at || s === 0) i = s;
    else {
      i = s - 1;
      while (i > 0 && g(i - 1) === g(s - 1)) i--;
    }
  }
  if (i < 0) return true;
  selectRow(focusRow(i, true), false);
  return true;
}
/** the pane's sections, for [ and ] and the outline's scroll-spy: a page's .sec (a build's
 * .b-sect), else its top-level boxes */
function paneSections(): HTMLElement[] {
  const d = document.getElementById("dscroll")!;
  let xs = [...d.querySelectorAll<HTMLElement>(".sec, .b-sect")];
  if (!xs.length) xs = [...d.querySelectorAll<HTMLElement>("section.box")].filter((x) => !x.parentElement!.closest("section.box"));
  return xs.filter((x) => x.offsetParent !== null);
}
export const sectionsNow = (): number => paneSections().length;
export const paneHead = (): number => {
  const x = document.querySelector("#dscroll .dh") as HTMLElement | null;
  return x && getComputedStyle(x).position === "sticky" ? x.offsetHeight : 0;
};
/** a section to the top of the pane, under its sticky header */
export function spyJump(el: Element): void {
  const d = document.getElementById("dscroll")!;
  d.scrollTop += el.getBoundingClientRect().top - d.getBoundingClientRect().top - paneHead() - 4;
}
function sectionStep(dir: number): boolean {
  const d = document.getElementById("dscroll")!, xs = paneSections();
  if (!xs.length) return false;
  const top = d.getBoundingClientRect().top + paneHead() + 8, at = xs.map((x) => x.getBoundingClientRect().top - top);
  // a section spyJump put at the top sits at -4: it is the current one, neither next nor previous
  const i = dir > 0 ? at.findIndex((y) => y > 2) : at.map((y, n) => (y < -8 ? n : -1)).filter((n) => n >= 0).pop();
  if (i == null || i < 0) d.scrollTop = dir > 0 ? d.scrollHeight : 0;
  else spyJump(xs[i]!);
  return true;
}
/** the scroll-spy: the outline's current section follows the scroll */
export function spy(): void {
  const d = document.getElementById("dscroll");
  if (!d) return;
  const links = d.querySelectorAll(".toc a");
  if (!links.length) return;
  const top = d.getBoundingClientRect().top + paneHead() + 12;
  let cur: HTMLElement | null = null;
  for (const x of paneSections()) if (x.getBoundingClientRect().top <= top) cur = x;
  const id = cur ? cur.id.replace(/^[bs]-/, "") : null;
  for (const a of links) {
    const k = (a.getAttribute("href") || "").split("?")[0]!.split("/").pop()!.replace(/^#s-/, "");
    if (k === id) a.setAttribute("aria-current", "true");
    else a.removeAttribute("aria-current");
  }
}

/* a row's menu: Open in new tab first on a row with a link (the browser's own menu is kept on every
   other element), then the row's object's verbs, the ones its pane draws */
function rowItems(row: HTMLElement): MenuItem[] {
  const a = rowOpen(row), link = a && a.getAttribute("href"), code = row.dataset.sel || (link ? linkKey(link) : null), out: MenuItem[] = [];
  if (link) out.push({ label: "Open in new tab", group: "open", run: () => window.open(new URL(link, location.href).href, "_blank", "noopener") });
  const i = code && code[0] === "i" ? ideaOf(code.slice(1)) : null;
  if (i) return [...out, ...ideaItems(i)];
  return [...out, ...[...row.querySelectorAll<HTMLElement>(".r-act button, .r-act a.btn, button.mute")].map(menuItem)];
}
function rowMenu(row: HTMLElement, at?: { x: number; y: number }): boolean {
  const items = rowItems(row);
  if (!items.some((x) => x.group !== "open")) return false; // nothing but a link: the browser's own menu
  menu(row, items, "Row actions", at);
  return true;
}

/** a shell verb on the rows or the pane (keys.json's "run"), true when it acted */
export function rowKey(run: string): boolean {
  const row = rowNow();
  switch (run) {
    case "menu": { // . : the focused row's menu, else the pane's ⋯
      if (row && rowMenu(row)) return true;
      const more = document.querySelector("#dscroll .dh .btn.more") as HTMLElement | null;
      if (more) {
        more.click();
        return true;
      }
      return false;
    }
    case "next":
    case "prev": {
      const x = focusRow(FOCUS ? FOCUS.i + (run === "next" ? 1 : -1) : 0, true);
      STEPPING = true;
      try {
        if (x) selectRow(x, false);
      } finally {
        STEPPING = false; // walking past a form row leaves the cursor here
      }
      return !!x;
    }
    case "nextGroup":
    case "prevGroup":
      return groupStep(run === "nextGroup" ? 1 : -1);
    case "nextSection":
    case "prevSection":
      return sectionStep(run === "nextSection" ? 1 : -1);
    case "open":
      return openFull() || openPane();
    case "pane":
      return openPane();
    case "primary": {
      const p = row && rowPrimary(row);
      if (p) {
        p.click();
        return true;
      }
      return openPane();
    }
  }
  return false;
}
/** esc: the terminal's panel, then the navigator's drawer (the shell's), then the selection, then
 * the focused row */
export function closeKey(navOpen: boolean, closeNav: () => void): boolean {
  if (closeTerm()) return true; // the terminal's panel (its session keeps running)
  if (navOpen) {
    closeNav();
    return true;
  }
  const R = routeNow();
  // a stage page's sheet (a cub's: sel=), then the cub page itself goes home
  if (R && R.stage && R.r.sel) {
    location.hash = href(R.r.path.map(encodeURIComponent).join("/"), R.r.q);
    return true;
  }
  if (R && R.stage && R.node === "home" && R.r.q.arrange) {
    location.hash = "#/home"; // Arrange: esc is Done
    return true;
  }
  if (R && R.stage && R.node === "cub") {
    location.hash = "#/home";
    return true;
  }
  // the full page goes back to the list with the item still selected (glance)
  if (R && R.focus) {
    location.hash = href(matchRoute(R.obj!)!.base.map(encodeURIComponent).join("/"));
    return true;
  }
  if (R && R.object) {
    location.hash = backHref(R);
    return true;
  }
  if (!FOCUS) return false;
  for (const e of document.querySelectorAll("#rows .focus")) e.classList.remove("focus");
  FOCUS = null;
  return true;
}
/** the keys the page takes before the key map: esc closes a popover; a–f pick a why chip while one
 * is open (before the page's own b, c…). "prevent": taken; "stop": the key goes no further; null:
 * the map's. */
export function keyFirst(key: string): "prevent" | "stop" | null {
  const P = popNow();
  if (key === "esc" && P) {
    closePop(P.el.contains(document.activeElement));
    return "prevent";
  }
  if (P && P.why && /^[a-f]$/.test(key) && !P.el.contains(document.activeElement)) {
    const c = P.why.querySelectorAll<HTMLElement>("button.chip")["abcdef".indexOf(key)];
    if (c) {
      c.click();
      return "prevent";
    }
    return "stop";
  }
  return null;
}

/** the frame's own clicks, wired once the shell has drawn the frame: a link in the list opens its
 * object in the pane (selTarget); a row's menu on a right-click or a long press (500 ms) */
let PRESS: { at: { x: number; y: number }; timer: ReturnType<typeof setTimeout>; fired?: boolean } | null = null;
const endPress = (): void => {
  PRESS = null;
  pressed(false);
};
export function initFrame(): void {
  const rows = document.getElementById("rows")!, pane = document.getElementById("dscroll")!;
  addEventListener("resize", tbHeight);
  rows.addEventListener("click", (e) => {
    if (e.defaultPrevented || e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const t = e.target as HTMLElement, a = t.closest("a[href]") as HTMLElement | null, link = a && a.getAttribute("href"), to = link && selTarget(link);
    // a click on a list row, not on one of its buttons or links, selects it
    const row = !a && (t.closest("li.row.lr") as HTMLElement | null);
    if (row && !t.closest("button, input, select, textarea, label") && !row.classList.contains("sel")) {
      selectRow(row, true);
      return;
    }
    if (!to || to === link || (a && a.dataset.home != null)) return; // data-home: the object's own page (N5)
    e.preventDefault();
    location.hash = to;
  });
  rows.addEventListener("contextmenu", (e) => {
    const t = e.target as HTMLElement, row = t.closest("li.row") as HTMLElement | null;
    if (!row || t.closest("input, textarea, select")) return;
    if (rowMenu(row, { x: e.clientX, y: e.clientY })) e.preventDefault();
  });
  rows.addEventListener("pointerdown", (e) => {
    const row = e.pointerType !== "mouse" && ((e.target as HTMLElement).closest("li.row") as HTMLElement | null);
    if (!row) return;
    const at = { x: e.clientX, y: e.clientY };
    PRESS = { at, timer: setTimeout(() => {
      if (rowMenu(row, at) && PRESS) {
        PRESS.fired = true;
        pressed(true);
      }
    }, 500) };
  });
  for (const ev of ["pointerup", "pointermove"] as const) rows.addEventListener(ev, (e) => { // not pointercancel: a touch's press cancels its pointer
    if (!PRESS) return;
    if (ev === "pointermove" && Math.hypot(e.clientX - PRESS.at.x, e.clientY - PRESS.at.y) < 10) return;
    clearTimeout(PRESS.timer);
    if (!PRESS.fired) endPress();
  }, { passive: true });
  rows.addEventListener("click", (e) => {
    if (PRESS && PRESS.fired) {
      e.preventDefault();
      e.stopPropagation();
      endPress();
    }
  }, true);
  pane.addEventListener("click", (e) => {
    // a link in the pane to another object opens it in the pane, the list staying (a neighbour, a
    // member of a theme, the idea that cites it)
    const l = !e.defaultPrevented && !e.button && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey && (e.target as HTMLElement).closest("a[href^='#/']");
    const link = l ? l.getAttribute("href") : null, to = link && selTarget(link);
    if (to && to !== link) {
      e.preventDefault();
      location.hash = to;
    }
  });
  pane.addEventListener("scroll", spy, { passive: true });
}
