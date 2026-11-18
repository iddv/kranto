// The app's data: the server's /api/status when it hosts the page at /brb/ (HOST; false
// when it doesn't), who this browser acts as, and the one press (act): a busy button, then a flash
// and a fresh read. Every URL of the page's own server is relative, so the page works at / and at
// /brb/; the server's are absolute: it serves them next to /brb/. Every page reads what it needs
// through lib/reads.svelte.ts (the server's /api/ideas, /api/today, /api/status…): there is no
// snapshot of the page's own.
import type { Status } from "../../api/afk.gen";
import { ApiError } from "../../api/client";
import { drop as dropReads, stale as staleReads } from "../reads.svelte";
import { UPD_BUSY } from "../../pages/settings/updates";
import { render, typing } from "./route";
import type { Undo } from "./types";
import { confirmThen } from "../../ui/dialog.svelte";
import { noteError } from "../../ui/feedback";
import { contain } from "../unreadable.svelte";
import { shellDoors } from "../../features/shell";

let LOADED = false; // the first read is done: the page draws
let HOST: Status | false | null = null; // the server's /api/status when it hosts this page; false when it doesn't
let WHO: { origin: string | null; require_token?: boolean } | null = null; // GET /api/whoami: origin null: not signed in

/** the first read is done (boot): the page draws */
export const loaded = (): boolean => LOADED;
/** The server's status, as last read */
export const host = (): Status | null => HOST || null;
/** the cub shop is off on this host (cubs.developer unset; PR 1.2): Cubs shows your installed cubs
 * and their approvals, no Available, Made by Kranto or adding a cub. Before the switch: shown. */
export const shopOff = (): boolean => !!HOST && HOST.cubs_developer === false;

/** a refused answer's words: its error, a nested answer's (a prepared press), its say; never the
 * raw body when it is JSON (the owner saw {"ok":false,…} in a red banner) */
export function refusalText(j: unknown, t: string, status: number, statusText = ""): string {
  const o = (j && typeof j === "object" ? j : null) as { error?: unknown; say?: unknown; message?: unknown; answer?: unknown } | null;
  const inner = o && o.answer && typeof o.answer === "object" ? (o.answer as { error?: unknown; say?: unknown }) : null;
  for (const x of [o?.error, inner?.error, inner?.say, o?.say, o?.message, typeof o?.answer === "string" ? o.answer : null]) if (typeof x === "string" && x.trim()) return x.trim();
  if (o || /^\s*[[{]/.test(t)) return `Kranto refused this without saying why (HTTP ${status}).`;
  return t.trim() || statusText || `HTTP ${status}`;
}
export async function api(path: string, body?: unknown): Promise<unknown> {
  const r = await fetch(path, body === undefined ? { cache: "no-store" } : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const t = await r.text();
  let j: { error?: string } | null = null;
  try {
    j = JSON.parse(t);
  } catch {
    /* text */
  }
  if (r.status === 401 && WHO) WHO = { ...WHO, origin: null }; // the sign-in line shows
  // an ApiError (an Error with its status): a caller tells a refusal of what was typed (4xx: a
  // provider refused a key) from Kranto's own failure (5xx: Tell us)
  if (!r.ok) throw new ApiError(r.status, refusalText(j, t, r.status, r.statusText));
  // a read's rows that could not be read are taken out of its lists, kept for the page's
  // "Couldn't read" lines (lib/unreadable)
  return j === null ? t : body === undefined ? contain(path, j) : j;
}
/** who this browser acts as: the session cookie a one-time code from kranto open set. The
 * page reads without it; a press needs it. Absolute: the server (or brb ui) answers it. */
export async function loadWho(): Promise<void> {
  try {
    const r = await fetch("/api/whoami", { cache: "no-store" });
    WHO = r.ok ? await r.json() : null;
  } catch {
    WHO = null;
  }
}
export const signedOut = (): boolean => !!(WHO && WHO.require_token && !WHO.origin);
/** The server's plain forms (pause, resume, run, grade). Asks for JSON: pause and resume answer
 * {ok, error}, with 502 when only one half changed; the others still answer with a redirect, so
 * a success there only means the request was taken and the caller checks the state it wanted
 * (togglePause reads both halves back). Returns the message the redirect carries (?msg=), if any. */
export async function hostForm(path: string, fields?: Record<string, string>): Promise<string | null> {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" }, body: new URLSearchParams(fields || {}).toString() });
  const t = await r.text();
  let j: { ok?: boolean; error?: string } | null = null;
  try {
    j = JSON.parse(t);
  } catch {
    /* a redirected page */
  }
  if (r.status === 401 && WHO) WHO = { ...WHO, origin: null };
  if (!r.ok || (j && j.ok === false)) throw new Error(refusalText(j, t, r.status, r.statusText));
  return r.redirected ? new URL(r.url).searchParams.get("msg") : null;
}
let BOOTED: string | null = null; // the server's version when this page loaded: another one answering means an update finished
export async function loadHost(): Promise<void> {
  try {
    const r = await fetch("/api/status", { cache: "no-store" });
    const j = r.ok ? await r.json() : null;
    HOST = j && "budget_usd" in j ? j : UPDT ? HOST : false; // restarting during an update: keep the last read
  } catch {
    HOST = UPDT ? HOST : false;
  }
  if (HOST && BOOTED === null) BOOTED = HOST.version;
  else if (HOST && HOST.version !== BOOTED && UPDT) {
    location.reload();
    return;
  }
  if (LOADED) updTrack();
}
/** a fresh read: what Kranto is doing (the top bar, Activity, the pages' lines) is read again with
 * the rest, showing what it said meanwhile (the server caches it 2 s); the
 * pages' own reads are read again on their schedules */
export async function load(): Promise<void> {
  LOADED = true;
  staleReads("api/activity");
}
export const afkPaused = (): boolean => !!(HOST && HOST.paused);

/** the flash at the list's top: set by a press, drawn by the next draw (route.ts's renderList) */
export interface Flash {
  text: string;
  kind?: string;
  undo?: Undo;
}
export let FLASH: Flash | null = null;
export const takeFlash = (): Flash | null => {
  const f = FLASH;
  FLASH = null;
  return f;
};
/** a flash at the list's top, drawn now */
export const say = (text: string, kind?: string): void => {
  if (kind === "red") noteError(text); // Feedback's details name the last few
  FLASH = { text, kind };
  render();
};
/** a flash for the next draw (a press that goes to another route) */
export const flash = (text: string, kind?: string): void => {
  if (kind === "red") noteError(text);
  FLASH = { text, kind };
};
/** a flash with an Undo while the server offers it (Stop round, Cancel) */
export const flashUndo = (text: string, until: number, run: (btn: HTMLElement) => void): void => {
  FLASH = { text, undo: { until, run } };
  render();
};

/** one press: the button busy, then a fresh read and done (or a red flash) */
export async function act(btn: HTMLElement | null, fn: () => Promise<unknown>, done?: (r: unknown) => void): Promise<void> {
  if (btn) {
    (btn as HTMLButtonElement).disabled = true;
    btn.setAttribute("aria-busy", "true");
  }
  try {
    const r = await fn();
    await load();
    // the button as it was at the press: a moved page keeps its button (its own binding disables
    // it again if it should)
    if (btn) {
      (btn as HTMLButtonElement).disabled = false;
      btn.removeAttribute("aria-busy");
    }
    if (done) done(r);
    else render();
  } catch (e) {
    if (btn) {
      (btn as HTMLButtonElement).disabled = false;
      btn.removeAttribute("aria-busy");
    }
    say((e as Error).message, "red");
  }
}

/** Not signed in: the page reads, but every press is refused until this browser has the
 * session cookie. `kranto open` on the machine Kranto runs on prints a one-time link (10 minutes);
 * its code also works in the list's sign-in line (the shell's ListHead.svelte, which calls this).
 * Agents never use this: they send their own token. */
export function signIn(code: string, btn: HTMLElement): Promise<void> {
  return act(btn, async () => {
    const r = await api("/auth/code", { code });
    await loadWho();
    return r;
  }, () => say("Signed in: this browser can act now."));
}

/** what an idea card waits for, in Needs you's and the home's row: its two verbs */
export const CARD_VERBS = "Later or Pass";
/** what Pause stops, for its tooltip, its confirm and its flash (the header is Header.svelte) */
export const PAUSES = "reading sources and writing ideas";
export async function togglePause(btn: HTMLElement | null, pausing: boolean): Promise<void> {
  // with the doors on, Pause is one press: it is undone by Resume, so it asks nothing and its
  // flash offers Resume (D-6; HIG Alerts: no alert for an undoable action)
  if (pausing && shellDoors(!!HOST)) {
    await doPause(btn, true, true);
    return;
  }
  if (pausing) {
    confirmThen("Pause everything?", `This stops ${PAUSES}. Resume starts them again.`, "Pause", () => doPause(btn, true));
    return;
  }
  await doPause(btn, false);
}
async function doPause(btn: HTMLElement | null, pausing: boolean, undo = false): Promise<void> {
  await act(btn, async () => {
    if (!HOST) throw new Error("Pause is the server's, which is not answering.");
    const note = await hostForm(pausing ? "/pause" : "/resume", pausing ? { reason: "paused from Kranto" } : {});
    await loadHost();
    await load();
    // "Paused" is said only when watching is: read it back
    if (afkPaused() !== pausing) throw new Error(`${pausing ? "Not paused" : "Not resumed"}: watching did not change.` + (note ? " " + note : ""));
  }, () => {
    const said = pausing ? `Paused: this stops ${PAUSES}.` : `Resumed: ${PAUSES}.`;
    if (undo) flashUndo(said, Date.now() + 9000, (b) => void doPause(b, false));
    else say(said);
  });
}

/** The server's cached reads under these paths, marked stale but kept: the next draw reads them
 * again and shows the old ones meanwhile, so a list never blanks to "Loading…" */
export function afkStale(...prefixes: string[]): void {
  prefixes.forEach(staleReads);
}
/** every cached read of the server is read again (its paths are absolute; the page's are not) */
export function afkDrop(): void {
  dropReads("/");
}
/** The server's cached reads under this path dropped, to be read again */
export function afkDropPrefix(p: string): void {
  dropReads(p);
}

/* Updates: the server's /api/status carries update {available, installed,
   channel, state, detail, reason, to, notes, notes_url, can_apply}; /api/update the rest (the
   cache, the settings, the history, busy). Restart to update asks Kranto's helper (POST
   /api/update), which backs up, installs, restarts and checks itself,
   rolling back on its own; while it runs the header says what it is doing, and the page reloads
   itself when the new version answers. */
export { UPD_BUSY }; // the steps' words: Settings › System › Updates' table, which Needs you's row reads too
const UPD_API = "/api/update";
export const updNow = () => (HOST && HOST.update ? HOST.update : null);
export const updBusy = (u: { state: string } | null): boolean => !!(u && UPD_BUSY[u.state]);
export const updBad = (u: { state: string } | null): boolean => !!(u && (u.state === "rolled_back" || u.state === "failed"));
let UPDT: ReturnType<typeof setInterval> | null = null; // while an update runs: /api/status every 5 s (loadHost reloads the page on a new version)
function updTrack(): void {
  const busy = updBusy(updNow());
  if (busy && !UPDT) UPDT = setInterval(loadHost, 5000);
  if (!busy && UPDT) {
    clearInterval(UPDT);
    UPDT = null;
    afkDropPrefix(UPD_API);
    if (!typing()) render();
  }
}
type UpdAnswer = { to?: string; when?: string };
/** Restart to update: the header's pill and Needs you's row use it too */
export function updApply(btn: HTMLElement | null, body?: { when?: string; to?: string }): Promise<void> {
  return act(btn, async () => {
    const r = await api(UPD_API, body || {});
    afkDropPrefix(UPD_API);
    await loadHost();
    updTrack();
    return r;
  }, (r) => {
    const a = r as UpdAnswer;
    say(`Updating to ${a.to}. Kranto restarts by itself; this page reloads when the new version answers.`);
  });
}
export function updRollback(btn: HTMLElement | null, to: string): void {
  confirmThen(`Roll back to ${to}?`, "Kranto restarts on it; the data stays as it is.", "Roll back", () => doRollback(btn, to));
}
function doRollback(btn: HTMLElement | null, to: string): Promise<void> {
  return act(btn, async () => {
    const r = await api(UPD_API + "/rollback", {});
    afkDropPrefix(UPD_API);
    await loadHost();
    updTrack();
    return r;
  }, () => say(`Rolling back to ${to}. Kranto restarts by itself; this page reloads when it answers.`));
}
/** an update still waiting: let it go */
export function updCancel(btn: HTMLElement | null): Promise<void> {
  return act(btn, async () => {
    const r = await api(UPD_API + "/cancel", {});
    afkDropPrefix(UPD_API);
    await loadHost();
    updTrack();
    return r;
  }, () => say("The update is cancelled; nothing was changed."));
}
