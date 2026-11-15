// The console (src/kranto/page/term/console.py): your own Claude Code or Codex, docked on the
// right of every page and mounted once (App.svelte), so moving between pages never touches it.
// Its routes are api/term/console*; its place (open · rail · minimized) is kept per browser
// ("kranto.console"); the first visit takes Settings › Assistant's "open when Kranto opens".
import { ApiError } from "../api/client";
import type { Session } from "./api";

export interface Harness {
  id: "claude" | "codex";
  name: string;
  installed: boolean;
  models: { id: string; name: string }[];
  extras: boolean;
}

export interface ConsoleSettings {
  open: boolean;
  harness: "claude" | "codex" | null;
  model: Record<string, string>;
  permission: "auto" | "ask" | "accept-edits";
  config: "own" | "kranto";
  daily_usd: number | null;
}

export interface ConsoleState {
  settings: ConsoleSettings;
  harness: "claude" | "codex" | null;
  harnesses: Harness[];
  /** each harness's conversation; ``previous``: the ones End this session set aside */
  conversations: Record<string, (Session & { previous?: PreviousSession[] }) | null>;
  plugin: boolean;
  head: { harness: string; model: string | null; mode: string; extras: boolean; note: string | null } | null;
  why: string | null;
  restart?: boolean;
  /** with your own configuration, the MCP servers it loads besides Kranto's (names only) */
  outside?: string[];
  /** whether this server serves terminals (Kranto itself does; `brb ui` alone does not) */
  socket?: boolean;
}

/** a conversation End this session set aside: ⋯ › Previous sessions resumes it */
export interface PreviousSession {
  session: string;
  ended: number | null;
  started: number | null;
  usd: number | null;
}

export type Place = "open" | "rail" | "min";
const KEY = "kranto.console";

async function answer<T>(r: Response): Promise<T> {
  let body: unknown = null;
  try {
    body = await r.json();
  } catch {
    body = null;
  }
  if (!r.ok) {
    const b = body as { error?: unknown } | null;
    throw new ApiError(r.status, typeof b?.error === "string" ? b.error : `HTTP ${r.status}`);
  }
  return body as T;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  return answer(
    await fetch(`api/term/console${path}`, {
      method: "POST",
      cache: "no-store",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

export const state = async (): Promise<ConsoleState> =>
  answer(await fetch("api/term/console", { cache: "no-store" }));
export const open = (harness: string | null, cols: number, rows: number) =>
  post<Session & { ticket: string; harness: string }>("/open", { harness, cols, rows });
export const fresh = (harness: string) => post<Session>("/new", { harness });
/** fresh: End this session (the next start is a new conversation; this one joins previous) */
export const end = (harness: string, fresh = false) => post<Session>("/end", fresh ? { harness, fresh } : { harness });
export const resume = (harness: string, session: string) => post<Session>("/resume", { harness, session });
export const here = (route: string, title: string) => post<{ ok: boolean }>("/here", { route, title });
export const save = (body: Partial<ConsoleSettings>) => post<ConsoleState>("/settings", body);
/** what it last said (the phone's sheet,): its newest reply's first lines and Kranto
 * page it linked, read from its own transcript; said null with why when there is none */
export interface LastSaid {
  harness: string | null;
  said: string | null;
  more?: boolean;
  at?: string | null;
  page?: string | null;
  why?: string;
}
export const last = async (): Promise<LastSaid> => answer(await fetch("api/term/console/last", { cache: "no-store" }));

/** The panel's place in this browser, and whether it was ever set here. */
export const consoleUi: { place: Place; known: boolean; harness: string | null; focusN: number; served: boolean; restart: { n: number; harness: string | null }; chip: string | null } = $state({
  place: "open",
  /** the assistant's name while the panel can be minimized (the top bar draws the chip in its
   * own row: it was fixed over Feedback, ⚙ and ◐); null: no chip */
  chip: null,
  known: false,
  harness: null,
  focusN: 0,
  /** Restart the console now (Settings › Assistant, the owner's Q2): the panel ends its session
   * and starts it again, resumed, with the settings saved (``harness``: another assistant) */
  restart: { n: 0, harness: null },
  /** this server runs consoles (Kranto itself; not `brb ui` alone): only then is the page's place told */
  served: false,
});

/* ---------- the docked panel's width (the owner's 07:38): a drag handle on its left
   edge, kept per browser, double-click resets, arrow keys on the handle ---------- */
const WIDTH_KEY = "kranto.console.width";
export const WIDTH_DEFAULT = 380;
export const WIDTH_MIN = 320;
/** Classic's list keeps its 560 px floor beside the panel: the navigator, the
 * splitter and the list come first */
const CLASSIC_KEEP = 224 + 6 + 560;
/** the widest the panel may be: 60% of the window, and in Classic what leaves the list 560 px */
export function widthMax(win: number, classic: boolean): number {
  const most = Math.floor(win * 0.6);
  return Math.max(WIDTH_MIN, classic ? Math.min(most, win - CLASSIC_KEEP) : most);
}
export const clampWidth = (w: number, win: number, classic: boolean): number =>
  Math.round(Math.min(widthMax(win, classic), Math.max(WIDTH_MIN, w)));
/** the width this browser kept, or null (the default) */
export function loadWidth(storage: Pick<Storage, "getItem"> = localStorage): number | null {
  let v: string | null = null;
  try {
    v = storage.getItem(WIDTH_KEY);
  } catch {
    v = null;
  }
  const n = Number(v);
  return v && Number.isFinite(n) && n > 0 ? n : null;
}
export function saveWidth(w: number | null, storage: Pick<Storage, "setItem" | "removeItem"> = localStorage): void {
  try {
    if (w == null) storage.removeItem(WIDTH_KEY);
    else storage.setItem(WIDTH_KEY, String(Math.round(w)));
  } catch {
    /* a private window keeps it for the page's life */
  }
}
/** the width in effect: --conw on the page's root, every docked rule reads it */
export function applyWidth(w: number | null, root: HTMLElement = document.documentElement): void {
  if (w == null) root.style.removeProperty("--conw");
  else root.style.setProperty("--conw", `${Math.round(w)}px`);
}

export function loadPlace(storage: Pick<Storage, "getItem"> = localStorage): void {
  let v: string | null = null;
  try {
    v = storage.getItem(KEY);
  } catch {
    v = null;
  }
  if (v === "open" || v === "rail" || v === "min") {
    consoleUi.place = v;
    consoleUi.known = true;
  }
}

/** a place chosen by a press in this page's life: before setup it wins over the wait (F-11) */
export const pressed = { v: false };
/** setup is not done (boot reads /api/setup once; Start reading ends the wait): F-11 */
export const setupWait = { v: false };
let bootDone: () => void = () => {};
/** boot has read /api/setup (or found no server): the console's first place waits for it, so a
 * first page never starts Claude Code before boot knows whether setup is done */
export const booted = new Promise<void>((r) => (bootDone = r));
export function consoleWaits(on: boolean): void {
  setupWait.v = on;
  bootDone();
}

export function setPlace(p: Place, storage: Pick<Storage, "setItem"> = localStorage): void {
  pressed.v = true;
  consoleUi.place = p;
  consoleUi.known = true;
  try {
    storage.setItem(KEY, p);
  } catch {
    /* a private window keeps it for the page's life */
  }
}

/** Under this width Classic has no room for its list, its pane and the console docked side by side
 *: the console starts on its rail there; a press opens it as anywhere. */
export const CLASSIC_DOCK_MIN = 1400;
/** The first visit in a browser follows the setting (open by default), but Classic on a screen
 * narrower than CLASSIC_DOCK_MIN starts on the rail, and a phone minimized: there ✦ in the bar of
 * doors opens the read-and-approve sheet when the owner asks (the dock that covered 70%
 * of a phone goes); later, the browser's own. */
export function firstPlace(settings: ConsoleSettings,
  screen: { classic: boolean; width: number } = { classic: document.body.classList.contains("classic"), width: innerWidth },
  setupPending = false): void {
  // before setup is done the console waits, whatever this browser kept: on its
  // rail (minimized on a phone), not kept, and nothing starts until a press opens it
  if (setupPending && !pressed.v) {
    consoleUi.place = screen.width < PHONE_MAX ? "min" : "rail";
    return;
  }
  if (consoleUi.known) return;
  if (screen.width < PHONE_MAX) {
    consoleUi.place = "min";
    return;
  }
  const narrow = screen.classic && screen.width < CLASSIC_DOCK_MIN;
  consoleUi.place = settings.open && !narrow ? "open" : "rail";
}
/** under this width the console is the phone's sheet (base.css's phone width) */
export const PHONE_MAX = 760;

/** Settings › Assistant's Restart now: the panel (mounted once) ends and resumes its session */
export function restartConsole(harness: string | null = null): void {
  consoleUi.restart = { n: consoleUi.restart.n + 1, harness };
  if (consoleUi.place !== "open") setPlace("open");
}

/** ⌘J / ctrl+J: open the panel, or put the keys into it when it is open. */
export function toggleConsole(): void {
  if (consoleUi.place !== "open") setPlace("open");
  consoleUi.focusN++;
}

/** #/console (help.md, the testers' first guess; 3): the panel opens and takes the keys.
 * The console is mounted once beside every page, so the address is a press, not a page. */
export function openConsole(): void {
  if (consoleUi.place !== "open") setPlace("open");
  consoleUi.focusN++;
}

/** Whether a key event comes from inside the console's terminal: it belongs to it then. */
export function inConsole(target: EventTarget | null): boolean {
  return target instanceof Element && !!target.closest("#console .screen");
}
