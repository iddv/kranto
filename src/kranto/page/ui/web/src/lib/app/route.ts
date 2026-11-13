// Where a route draws, and the draw (WORKSPACE.md 1, 5): the routes are ../router.ts and
// ../nodes.json, every page a component (../../pages, lib/pages.svelte.ts). render() puts the
// route's list page in the list pane and the selected object's page (or what the list is about)
// in the detail pane; a page already there only gets its new props, so the five-second refresh
// never moves a scroll, a selection, a tick or an open fold. Then the frame's chrome (frame()).
import { mount } from "svelte";
import { doorsOf, href, matchRoute, parse, redirectOf, selCode, selPath, type Route } from "../router";
import { dropPage, pageFor, showPage, type PagePart, type Where } from "../pages.svelte";
import { PRODUCT } from "../product";
import { read } from "../reads.svelte";
import { frame, ui } from "../shell.svelte";
import { openTerm, termUi } from "../../term/state.svelte";
import { consoleWaits, openConsole } from "../../term/console.svelte";
import { closeDetails } from "../../ui/details.svelte";
import { gradeKeys } from "../../ui/ticks.svelte";
import { closeDialog, openDialog } from "../../ui/dialog.svelte";
import { popNow } from "../../ui/popover";
import KeySheet from "../../shell/KeySheet.svelte";
import PageHead from "../../shell/PageHead.svelte";
import Unreadables from "../../ui/Unreadables.svelte";
import { drawEnds, drawStarts } from "../unreadable.svelte";
import Missing from "../../pages/Missing.svelte";
import PaneEmpty from "../../pages/PaneEmpty.svelte";
import { toast } from "../../ui/toast.svelte";
import { api, host, shopOff, load, loadHost, loadWho, loaded, say, takeFlash, type Flash } from "./data";
import { ideaOf } from "../../pages/ideas/ideas";
import { markSel, paneHead, resetFocus, rowNow, spy } from "./rows";
import { noteView, startViews } from "../telemetry";
import { noteRecent } from "./commands";
import { frameClassic, frameNew, loadShell, shellDoors } from "../../features/shell";
import { rememberTopic, scopeOf, watchRedirect } from "./watchscope";
import { features } from "../../features/index";

/** where(): the route, the navigator entry it lights, the object in the pane, and its focus
 * section (a build or a project drawn as a full page) */
export interface W extends Where {
  focus: string | null;
}
/* The list views, by the route's first part: the go-to keys' (g l, g t) */
const VIEWS = new Set(["review", "topics", "ideas", "library", "settings", "welcome", "hello", "news", "home", "needs", "activity"]);
// g h goes home while the doors' pages are (in either layout the home is a page); g n while
// the server hosts News
export const hasView = (to: string): boolean => VIEWS.has(to) && (to !== "home" || shellDoors(!!host())) && (to !== "news" || !!host());
export const topicAt = (n: number): { id: number; name: string } | null => host()?.topics[n - 1] || null;

/* Focus: an object with a section segment in its route drawn as a full page, the
   list collapsed. No object has one since builds and projects left; the frame keeps the seam. */
export const FOCUSABLE: Record<string, string[]> = {};
/* the sel= codes of the rows that are not an object's own route: Needs you's (a topic's
   proposals, a message, the review queue), drawn by its pane beside any list */
const NEEDSELS: Record<string, string> = { p: "proposed sources", m: "message", r: "review queue", t: "topic", u: "rollup", e: "setting" };

/** the cubs Post draws: their own pages land on Post */
const POSTING_CUBS = new Set(["newsletter", "toot", "blog", "examplecom"]);
/** the shop's own tabs of Cubs: Post's while the shop is off */
const SHOP_TABS = new Set(["available", "made"]);
/** old Settings pages of what folded in (the cubs' list, the layout): the Overview's, unless the
 *  feature is on (a settings file's by hand) */
const GONE_SETTINGS = new Set(["cubs", "layout"]);
const featureOn = (id: string): boolean => (features(!!host())?.features || []).some((f) => f.id === id);

export function where(r: Route): W {
  const m = matchRoute(r.path);
  if (!m || m.redirect) return { r, node: null, list: r.path, object: null, obj: null, id: null, stage: true, missing: !m, sel: false, focus: null };
  const w: W = { r, node: m.node, list: m.list, object: m.object || null, obj: m.object ? r.path : null, id: m.id, stage: !!m.stage, missing: false, sel: false, focus: null };
  if (m.object && FOCUSABLE[m.object] && r.path.length > m.base.length) w.focus = r.path[m.base.length] || null;
  if (!w.object && !w.stage && !r.sel) r.sel = defaultSel(m, r);
  // a cub's selection is its own (sel=o<id> is its object, not the library's observation:)
  const p = !w.object && !w.stage && w.node !== "cub" && w.node !== "cubs" ? selPath(r.sel) : null, s = p && matchRoute(p);
  if (s && s.object) Object.assign(w, { object: s.object, obj: p, id: s.id, sel: true });
  // a Needs you row that is not an object's own route (a topic's proposals, a message, the queue)
  else if (!w.object && !w.stage && r.sel && Object.hasOwn(NEEDSELS, r.sel[0]!)) Object.assign(w, { object: "need", obj: ["need", r.sel], id: r.sel, sel: true });
  // with the doors on, a selection only the page's own pane knows (a brief, sel=f<id>) is a sheet
  // too: there is no pane beside the list to draw it in otherwise
  else if (!w.object && !w.stage && r.sel && shellDoors(!!host())) Object.assign(w, { object: "sel", obj: ["sel", r.sel], id: r.sel, sel: true });
  return w;
}
/* the row a route selects when it names none (WORKSPACE.md 9, risk 4): a settings page's main
   group (NODES' sel: the key, the first role, the house rules, the theme), so its form is one look
   away; Health's ?message= and Add source's ?preset= and ?review= (the links that already exist)
   select their row. Not on a phone, where a selection would cover the list. */
function defaultSel(m: NonNullable<ReturnType<typeof matchRoute>>, r: Route): string | null {
  if (m.node === "settings/system" && r.q.message) return "emsg:" + r.q.message; // System › Health's message
  if (r.path.join("/") === "settings/sources/new" && (r.q.preset || r.q.review)) return r.q.review ? "ereview:" + r.q.review : "epreset:" + r.q.preset;
  // the new frame opens a sheet only when a row is chosen: never on arrival; the
  // classic frame fills its pane, as 0.4.10's did
  if (!m.sel || matchMedia("(max-width: 759px)").matches || frameNew(!!host())) return null;
  if (m.node === "settings/watching" && !host()) return null; // the provider and its key are the server's
  return m.sel;
}

let ROUTE: W | null = null; // where(parse()), as last drawn
export const routeNow = (): W | null => ROUTE;
const LISTQ: Record<string, Record<string, string>> = {}; // a list's filters, by node: kept while one of its rows is open in the pane
const SCROLLS: Record<string, number> = {}; // a list's scroll, by its route, for coming back
/* the list scrolls in #rows, not the document, so the browser's own restore does nothing on a
   reload (QA B19): its scroll is kept in this history entry's state (stored nowhere by the page)
   once it settles, and put back once the rows are there */
let RESTORE: { k: string; top: number; tries: number } | null = null;
export function keepScroll(): void {
  const rows = document.getElementById("rows");
  if (!rows || !PANE.list) return;
  history.replaceState({ ...((history.state as object | null) || {}), rows: { k: PANE.list, top: rows.scrollTop } }, "");
}
const PANE: { list: string | null; detail: string | null } = { list: null, detail: null }; // what each pane last drew
let PAGE: { keys: Record<string, () => void> } = { keys: {} }; // the page's own verbs, by keys.json name ("b", "1", "⇧a"): set by the pages, reset on every draw

/** a page's own key (keys.json names: "⇧a"), set again on each draw (every draw clears them) */
export const pageKey = (k: string, f: () => void): void => {
  PAGE.keys[k] = f;
};
export const pageKeys = (): string[] => Object.keys(PAGE.keys);
export const pageHas = (k: string): (() => void) | null => PAGE.keys[k] || null;
export const runPageKey = (k: string): void => PAGE.keys[k]!();

/* a link in the list pane opens its object in the pane: at the object's home the route itself,
   elsewhere the list's route with sel=. Links with a section or filters go where they say. */
export function selTarget(link: string | null): string | null {
  const w = ROUTE;
  if (!w || w.stage || !/^#\//.test(link || "")) return null;
  const [p = "", qs] = link!.slice(2).split("?"), path = p.split("/").filter(Boolean).map(decodeURIComponent), m = matchRoute(path);
  if (!m || !m.object || qs || m.base.length !== path.length) return null;
  if (m.node === w.node) return link;
  const code = selCode(path);
  if (!code) return null;
  return href(w.r.path.map(encodeURIComponent).join("/"), { ...w.r.q, sel: code });
}
export const linkKey = (link: string | null): string | null => {
  if (!/^#\//.test(link || "")) return null;
  const m = matchRoute(link!.slice(2).split("?")[0]!.split("/").filter(Boolean).map(decodeURIComponent));
  return m && m.object ? selCode(m.base) : null;
};
export const backHref = (w: W): string =>
  w.sel ? href(w.r.path.map(encodeURIComponent).join("/"), w.r.q) : href(w.list.map(encodeURIComponent).join("/"), (w.node && LISTQ[w.node]) || {});
/** a row's pane when it is not an object's own route: the list's route with sel= (WORKSPACE.md 5) */
export const selHref = (code: string): string => {
  const r = ROUTE ? ROUTE.r : parse();
  return href(r.path.map(encodeURIComponent).join("/"), { ...r.q, sel: code });
};
/** a link in a pane to a Today-style pane (an issue: sel=g…): beside the list the pane belongs to */
export const paneSelHref = (code: string): string =>
  ROUTE && ROUTE.object && !ROUTE.sel ? href(ROUTE.list.map(encodeURIComponent).join("/"), { ...((ROUTE.node && LISTQ[ROUTE.node]) || {}), sel: code }) : selHref(code);

/** c and Open in Claude Code: the terminal's panel on the subject; while it is off, the one line
 * that says how to turn it on (api/term's why) */
export function openClaude(kind: string, id: string, title?: string): void {
  if (termUi.enabled) return openTerm(kind as never, id, title || "");
  say(termUi.why || "Open in Claude Code is off: turn term.enabled on under Settings › Assistant.");
}
/** the ? sheet (shell/KeySheet.svelte): the page's own verbs are greyed where this page has none */
export function keySheet(): void {
  openDialog(KeySheet, { has: Object.keys(PAGE.keys), hasView }, { wide: true });
}

// a ticked row's checkbox keeps the focus after a click, but it is not a field: the keys still act
export const typing = (): boolean => {
  const a = document.activeElement as HTMLInputElement | null;
  // a terminal's input (the console, Open in Claude Code) is no field of the page: a redraw leaves
  // it be, so the page stays live while the owner talks to an assistant (#490: what the
  // console prepared showed only after a reload)
  if (a && typeof a.closest === "function" && a.closest(".xterm")) return !!(document.getElementById("dlg") as HTMLDialogElement | null)?.open || !!popNow();
  return (/^(INPUT|TEXTAREA|SELECT)$/.test((a || ({} as HTMLElement)).tagName || "") && !/^(checkbox|radio)$/.test((a && a.type) || ""))
    || !!(document.getElementById("dlg") as HTMLDialogElement | null)?.open || !!(document.getElementById("pal") as HTMLDialogElement | null)?.open || !!popNow();
};
/** a read that arrives redraws the page (not under a field being typed in) */
export function redraw(): void {
  if (!typing()) render();
}

/* the flash at the list's top: it stays for 8 s from when it was first drawn, through any
   redraws, then goes: redraws never restart its clock (that kept "Resumed"/"Queued" blinking for
   as long as reads arrived). One with an Undo (Stop round, Cancel) stays while its
   Undo is offered. A the server form redirected here says its notice (?msg=). */
let SHOWN: (Flash & { at: number; on: string }) | null = null;
function headFlash(r: Route) {
  let f = takeFlash();
  if (!f && r.q.msg && !(SHOWN && SHOWN.on === location.hash)) f = { text: r.q.msg };
  if (f) SHOWN = { ...f, at: Date.now(), on: location.hash };
  const offered = (x: Flash) => (x.undo && Date.now() < x.undo.until ? x.undo : null);
  const fl = f || (SHOWN && SHOWN.on === location.hash && (Date.now() - SHOWN.at < 8000 || offered(SHOWN)) ? SHOWN : null);
  const u = fl && offered(fl); // "Stopped round 4 · Undo"
  if (u && !u.timer) u.timer = setTimeout(redraw, u.until - Date.now() + 50); // the offer ends: drawn without it
  return fl ? { text: fl.text, kind: fl.kind || "blue", undo: u || null } : null;
}
let FLASHED: ReturnType<typeof headFlash> = null;
export const flashNow = () => FLASHED;

/** Where an address lands: a redirect, then (the doors' pages, in either layout) the route's
 * place in the doors; a redirect's target may have moved too (library/clusters/3 →
 * watch/map?sel=c3), and Watch is topic-first (WT): an old ?topic= form is the topic's page, and
 * the Watch door lands on the last topic looked at. The page goes there (render); a prepared
 * press's page is matched by where it lands (PAR: #/ideas/12 lands on #/ideas?sel=i12, and its
 * card never showed). */
export function landOf(hash: string, doors: boolean = shellDoors(!!host())): string {
  let at = hash, r = parse(at), m = matchRoute(r.path);
  for (let n = 0; m && n < 4; n++) {
    // what left: with the shop off its pages land on Post (#/cubs/available drew the
    // whole Cubs page); Settings of a page that is gone or off lands on the Overview, never on
    // "There is no feature or cub called …"
    if (doors && r.path[0] === "cubs" && r.path.length === 2 && SHOP_TABS.has(r.path[1]!) && shopOff()) {
      at = href("post");
      break;
    }
    if (doors && r.path[0] === "settings" && r.path.length === 2 && GONE_SETTINGS.has(r.path[1]!) && !featureOn(r.path[1]!)) {
      at = href("settings");
      break;
    }
    // the short posts' old settings (the toot cub, folded into Kranto's own short posts) are
    // Posting's, unless that cub is still installed
    if (r.path[0] === "settings" && r.path.length === 2 && r.path[1] === "toot" && !featureOn("toot")) {
      at = href("settings/posting");
      break;
    }
    // a posting cub's page is Post once a draft has its own sheet there
    // (#/post/d/<id>); a selection on the cub's page (its object) or one of its own lists (its
    // issues, its log: ?list=) still opens there
    if (doors && r.path[0] === "cub" && r.path.length === 2 && POSTING_CUBS.has(r.path[1]!) && !r.sel && !r.q.list && matchRoute(["post", "d", "1"])) {
      at = href("post");
      break;
    }
    const moved = !m.redirect && doors ? doorsOf(m, r.path, r.q, r.sel) : null;
    const scoped = !m.redirect && doors ? watchRedirect(r) : null;
    if (scoped) at = href(scoped.path, { ...scoped.q, sel: r.sel });
    else if (m.redirect) {
      // a selection is kept too, and picks the page it moved to; a page that left drops both
      const to = redirectOf(m, m.gone ? null : r.sel);
      at = href(to.path, m.gone ? {} : { ...r.q, sel: to.sel });
    } else if (moved) at = href(moved.path, { ...moved.q, sel: moved.sel });
    else break;
    r = parse(at);
    m = matchRoute(r.path);
  }
  return at;
}

export function render(): void {
  if (!loaded()) return;
  let r = parse();
  // #/ is the home
  if (!r.path.length) {
    history.replaceState(null, "", href("home", r.q));
    r = parse();
  }
  const doors = shellDoors(!!host()), fresh = frameNew(!!host());
  // a cub's Settings and About sheets are its Settings page now: the old
  // addresses land there, About on its words (one release of redirects, then gone)
  // a brief's side sheet is its page now: Earlier's old sel=f<id>
  if (doors && r.path.join("/") === "news/earlier" && r.sel && /^f\d+$/.test(r.sel)) {
    history.replaceState(null, "", href("news/b/" + r.sel.slice(1)));
    r = parse();
  }
  if (doors && r.path[0] === "cub" && r.path.length === 2 && (r.sel === "settings" || r.sel === "about")) {
    history.replaceState(null, "", href("settings/" + r.path[1], { sel: r.sel === "about" ? "eabout" : null }));
    r = parse();
  }
  // #/console opens the console beside the home (3: it said "There is no page at #/console")
  if (r.path[0] === "console" && r.path.length === 1) {
    openConsole();
    history.replaceState(null, "", href("home"));
    r = parse();
  }
  const landed = landOf(location.hash, doors);
  if (landed !== location.hash) {
    // an address of a page that left says so where it lands
    const said = matchRoute(r.path)?.said;
    if (said) toast(said);
    history.replaceState(null, "", landed);
    r = parse();
  }
  const w = where(r);
  ROUTE = w;
  const scope = doors ? scopeOf(r.path) : null;
  if (scope?.topic && w.node && !w.missing) rememberTopic(scope.topic); // where Watch comes back to
  document.body.classList.toggle("focus", !!w.focus);
  PAGE = { keys: {} };
  document.body.classList.toggle("stage", w.stage);
  document.body.classList.toggle("shell-home", doors); // the phone's header (base.css)
  document.body.classList.toggle("doors", doors); // the doors' pages: the row diet, the type (base.css)
  document.body.classList.toggle("classic", frameClassic(!!host())); // the navigator's frame (base.css)
  document.body.classList.toggle("bare", ["hello", "welcome"].includes(r.path[0] || "")); // first run: no navigator
  document.body.classList.toggle("show-detail", !!w.object);
  FLASHED = headFlash(r);
  // the page's one head: the shell draws it on the doors' pages, either layout;
  // first run (the splash and setup's steps) has none
  ui.headOn = doors && !document.body.classList.contains("bare");
  drawStarts(); // the reads this draw asks for are the page's (their unreadable rows: below)
  const list = renderList(w), detail = renderDetail(w);
  renderInline(w);
  renderHead();
  renderUnreadable();
  drawEnds();
  // c: Open in Claude Code on the idea the pane shows, unless the pane's page set its own c; set
  // before the Grade keys, whose a–f why chips would take c on a card's graded head
  const shownIdea = !PAGE.keys.c && w.id && w.object === "idea" ? ideaOf(w.id) : null;
  if (shownIdea) {
    const id = w.id!, title = shownIdea.title || "";
    PAGE.keys.c = () => openClaude("idea", id, title);
  }
  gradeKeys(document.getElementById("app")!, PAGE.keys, rowNow);
  markSel(w);
  frame(r); // the shell's parts, once the page has drawn: a page's own counts (a topic's) are known then
  const titled = (detail && (detail as HTMLElement).dataset.title) || (list && (list as HTMLElement).dataset.title);
  // the new frame's one sheet: the detail pane over the dimmed column while an object is chosen
  ui.sheet = fresh && !!w.object && !w.focus;
  ui.sheetTitle = (detail && (detail as HTMLElement).dataset.title) || "";
  if (doors && w.object && titled) noteRecent(titled, location.hash); // ⌘K's Recent
  document.title = (titled ? titled + " · " : "") + PRODUCT;
}
/* the list pane: the route's list page (an object's home list, with the filters it had); a route
   the app does not have says so */
function renderList(w: W): Element | null {
  const r = w.r, lr: Route = w.object && !w.sel ? { path: w.list, q: (w.node && LISTQ[w.node]) || {}, sel: null } : r;
  if (!w.object && !w.stage && w.node) LISTQ[w.node] = r.q;
  const rows = document.getElementById("rows")!;
  const part: PagePart = (!w.missing && pageFor(w.node, "list")) || (Missing as PagePart);
  const k = "page:" + lr.path.join("/") + "?" + new URLSearchParams(lr.q), fresh = PANE.list !== k;
  // another list (other filters, another page) starts where it was left, else at the top
  if (fresh) {
    resetFocus();
    if (PANE.list) SCROLLS[PANE.list] = rows.scrollTop;
  }
  showPage("list", rows, part, w);
  if (fresh) {
    const kept = (history.state as { rows?: { k: string; top: number } } | null)?.rows;
    const top = SCROLLS[k] ?? (kept && kept.k === k ? kept.top : 0);
    rows.scrollTop = top;
    RESTORE = rows.scrollTop < top - 1 ? { k, top, tries: 0 } : null;
  } else if (RESTORE && RESTORE.k === k) {
    // the rows came after the first draw (a reload): scroll as they arrive, a few draws at most
    rows.scrollTop = RESTORE.top;
    if (rows.scrollTop >= RESTORE.top - 1 || ++RESTORE.tries > 20) RESTORE = null;
  }
  PANE.list = k;
  tbHeight();
  return rows.querySelector(":scope > :not(#page-head-box):not(#unreadable-box):not(#inpane)");
}
/* the page's head (shell/PageHead.svelte): mounted once, kept the first child of the column, so it
   scrolls with the page above the list's sticky toolbar; it draws nothing where no page declares a
   head and no door is open (the home, first run) */
let HEADBOX: HTMLElement | null = null;
function renderHead(): void {
  const rows = document.getElementById("rows")!;
  if (!ui.headOn) {
    HEADBOX?.remove();
    return;
  }
  if (!HEADBOX) {
    HEADBOX = document.createElement("div");
    HEADBOX.id = "page-head-box";
    mount(PageHead, { target: HEADBOX });
  }
  if (rows.firstElementChild !== HEADBOX) rows.prepend(HEADBOX);
}
/* the rows this page's lists could not read (RCA A3, ui/Unreadables.svelte): mounted once, kept
   right under the page's head (or first, where there is none), in every layout and on a phone; it
   draws nothing while every row was read */
let UNREADBOX: HTMLElement | null = null;
function renderUnreadable(): void {
  const rows = document.getElementById("rows")!;
  if (!UNREADBOX) {
    UNREADBOX = document.createElement("div");
    UNREADBOX.id = "unreadable-box";
    mount(Unreadables, { target: UNREADBOX });
  }
  const head = rows.firstElementChild?.id === "page-head-box" ? rows.firstElementChild : null;
  if (head ? head.nextElementSibling !== UNREADBOX : rows.firstElementChild !== UNREADBOX) {
    if (head) head.after(UNREADBOX);
    else rows.prepend(UNREADBOX);
  }
}
/** the shell's head goes with the frame (a test's frame is new each time) */
export function dropHead(): void {
  HEADBOX?.remove();
  HEADBOX = null;
  UNREADBOX?.remove();
  UNREADBOX = null;
}
/** the list's toolbar may wrap (its filters): the group heads stick under it, or at the top of a
 * list that has none (most Settings pages) */
export function tbHeight(): void {
  const tb = document.querySelector("#rows > .wl > .tb") as HTMLElement | null;
  document.getElementById("rows")!.style.setProperty("--tbh", (tb ? tb.offsetHeight : 0) + "px");
}
/* the objects whose moved pane draws them away from their home too (sel=s<id> on a topic's page,
   sel=n<key>, sel=o<id>, sel=c<n> and sel=i<id> on Today or a topic's page) */
const AWAY = ["source", "connection", "observation", "theme", "idea"];
/* the detail pane: a page's pane (its own object, a selected setting group, compacted week, watch,
   Add watch or Topics row, or what the page is about); an object shown away from its home (sel=: a
   topic from Spend) is its home's; a build, a project, a source, an observation or a theme shown
   away from home (a Today row, a topic's Builds or Sources) is drawn by its home's pane (UXI,
   FE-8); a Today row that is not an object's own route (an issue, the proposals, a message, the
   queue) is Today's pane's, beside any list. With none of those: nothing selected. */
function renderDetail(w: W): Element | null {
  const box = document.getElementById("dscroll")!;
  if (w.stage || (!w.object && !w.focus && frameNew(!!host()))) {
    dropPage("pane");
    box.replaceChildren();
    PANE.detail = null;
    return null;
  }
  const own = !w.object || w.object === "sel" || (w.object === "need" ? /^[eut]/.test(w.id || "") : !w.sel);
  const home = own || !w.obj ? null : FOCUSABLE[w.object!] || AWAY.includes(w.object!) ? (matchRoute(w.obj) || { node: null }).node : w.object === "need" ? "needs" : null;
  const part: PagePart = (own ? pageFor(w.node, "pane") : (home && pageFor(home, "pane"))) || (PaneEmpty as PagePart);
  const k = "page:" + (w.object ? w.obj!.join("/") : "none:" + w.node), fresh = PANE.detail !== k;
  showPage("pane", box, part, w, w.object ? backHref(w) : null);
  PANE.detail = k;
  if (fresh) box.scrollTop = 0;
  box.style.setProperty("--dhh", paneHead() + "px");
  spy();
  return w.object ? box.querySelector(".pane-in") : null;
}

/* In the new frame there is no pane beside a list, so a page whose pane says what the page is about
   with nothing chosen draws it in the column, above or below its list: the
   map over its themes, a topic's facts and verbs over its sections, Health's runs (and Run ingest
   now) under Settings › System. ":x" is one segment, as in pageFor. (Review draws its card itself.) */
export const INLINE: Record<string, "top" | "bottom"> = {
  "watch/map": "top", "library/map": "top", "topics/:id/map": "top", "settings/system": "bottom",
};
export function inlineOf(node: string | null): "top" | "bottom" | null {
  if (!node) return null;
  if (INLINE[node]) return INLINE[node]!;
  const parts = node.split("/");
  for (const [k, at] of Object.entries(INLINE)) {
    const ks = k.split("/");
    if (k.includes(":") && ks.length === parts.length && ks.every((s, i) => s[0] === ":" || s === parts[i])) return at;
  }
  return null;
}
function renderInline(w: W): void {
  const rows = document.getElementById("rows")!;
  let box = document.getElementById("inpane");
  const at = frameNew(!!host()) && !w.stage && !w.focus ? inlineOf(w.node) : null;
  const part = at ? pageFor(w.node, "pane") : null;
  if (!at || !part) {
    dropPage("inline");
    box?.remove();
    return;
  }
  if (!box || box.parentElement !== rows) {
    box = document.createElement("div");
    box.id = "inpane";
    box.className = "inpane";
  }
  // on top: under the page's head, when the shell draws one, and its "Couldn't read" lines
  let head = rows.firstElementChild?.id === "page-head-box" ? rows.firstElementChild : null;
  const after = head ? head.nextElementSibling : rows.firstElementChild;
  if (after && after.id === "unreadable-box") head = after;
  if (at === "top" ? (head ? head.nextElementSibling : rows.firstElementChild) !== box : rows.lastElementChild !== box) {
    if (at === "top" && head) head.after(box);
    else if (at === "top") rows.prepend(box);
    else rows.append(box);
  }
  // what the page is about: its route without the chosen object (that one is in the sheet)
  showPage("inline", box, part, { ...w, r: { ...w.r, sel: null }, object: null, obj: null, id: null, sel: false });
}

/** the sheet's Close, its scrim and esc: back to the list, the row still chosen */
export function closeSheet(): void {
  const R = ROUTE;
  if (R && R.object && !R.focus) location.hash = backHref(R);
}

/** a new route (the shell's hashchange): draw it. A dialog and the Details drawer belong to the
 * page they opened on: another page closes them (14, Gemini 12: Write a post's question
 * stayed open over Ideas after Back, and Details over Settings) */
let lastPath: string | null = null;
export function onHash(): void {
  const t0 = performance.now();
  const path = parse().path.join("/");
  if (lastPath !== null && path !== lastPath) {
    closeDialog();
    closeDetails();
  }
  lastPath = path;
  render();
  noteView(parse().path, performance.now() - t0);
}
/** the live feed reported a change (or 5 s passed while it is down): read again and draw */
export async function refresh(): Promise<void> {
  if (document.hidden) return;
  try {
    await load();
  } catch {
    return;
  }
  const r = parse(), w = where(r);
  if (r.path[0] === "library") {
    frame(r); // drawn from the server's JSON: redrawn when it arrives
    return;
  }
  // the key field is never kept across a redraw: while it holds something, leave the page be
  const key = document.getElementById("model-key") as HTMLInputElement | null;
  if (!typing() && !(key && key.value)) render();
  else frame(r);
}
/** start: the server's status and who this browser is, the first run's landing, the first draw (the
 * shell calls it once it has drawn the frame) */
export async function boot(): Promise<boolean> {
  // kept a moment after the list stops scrolling (a state written as the page unloads is lost)
  let quiet: ReturnType<typeof setTimeout> | null = null;
  document.getElementById("rows")?.addEventListener("scroll", () => {
    if (quiet) clearTimeout(quiet);
    quiet = setTimeout(keepScroll, 250);
  }, { passive: true });
  await Promise.all([loadHost(), loadWho()]);
  if (host()) {
    await loadShell(api); // which shell draws, before the first draw (shell.home)
    // first run: a fresh install lands on #/welcome (an older the server has no /api/setup)
    let setup: { needs_setup?: boolean; done?: boolean } | null = null;
    try {
      setup = (await api("/api/setup")) as { needs_setup?: boolean; done?: boolean };
    } catch {
      setup = null;
    }
    // before setup is done the console waits on its rail
    consoleWaits(!!setup && setup.done === false);
    if (setup && setup.needs_setup && ["", "overview", "today", "home"].includes(parse().path[0] || "")) history.replaceState(null, "", "#/hello");
  } else consoleWaits(false);
  await load();
  render();
  // usage counters: hosted only, and only when Settings › Privacy & access is not off
  if (host() && (await startViews())) noteView(parse().path, performance.now());
  return true;
}
