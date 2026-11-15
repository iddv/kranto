// The layout and the home's arrangement, as the server keeps them in kranto.yaml
// under shell: (GET /api/shell; POST /api/shell is its one writer). One set of pages, the doors'
// (their addresses, their rows, their sheet's contents), in one frame: the home and the doors,
// each door one column with its subnav and every object in one sheet. The Classic frame (the
// navigator on the left) was cut in open-source wave 1; a file that says classic reads
// as New. The arrangement is read once before the first draw (boot) and again after a write.
// Without the server (brb ui alone) there are no doors: 0.4.10's pages and the tree.
import { put, read } from "../lib/reads.svelte";
import { app, ui } from "../lib/shell.svelte";

export const SHELL_API = "/api/shell";

/** one cub's place on the home */
export interface CubPlace {
  id: string;
  trust: string;
  pinned: boolean;
  place: number | null;
  hidden: boolean;
  needs_you: boolean;
  new: boolean;
}
export type Layout = "new" | "classic";
export interface Arrangement {
  /** the frame (shell.layout); a server of 0.5.8 or older answers home and doors instead */
  layout?: Layout;
  home?: boolean;
  doors?: boolean;
  pins: string[];
  hidden: string[];
  needs_cap: number;
  new_cap: number;
  cubs: CubPlace[];
  pins_max: number;
  /** the home's widgets in order (core.home.resolve); absent from an older the server */
  widgets?: import("./home").HomeEntry[];
  /** the person arranged the home (shell.widgets is set) */
  custom?: boolean;
}

let FIRST: Arrangement | null = null; // as read at boot: the shell to draw before any read arrives

/** read the arrangement before the first draw; an older the server (no /api/shell) is the tree */
export async function loadShell(fetcher: (path: string) => Promise<unknown>): Promise<void> {
  try {
    FIRST = (await fetcher(SHELL_API)) as Arrangement;
    put(SHELL_API, FIRST);
  } catch {
    FIRST = null;
  }
}

/** the arrangement as last read (null without the server) */
export function arrangement(host: boolean): Arrangement | null {
  if (!host) return null;
  return read<Arrangement>(SHELL_API, 60000).data || FIRST;
}

/** the doors' pages and addresses: in either layout, whenever the server hosts
 * the page; the old routes redirect to them */
export const shellDoors = (host: boolean): boolean => !!arrangement(host);
/** the same, for a page as it draws (redrawn on every draw): the doors' page in either layout */
export const doorsNow = (): boolean => ui.drawn >= 0 && shellDoors(!!app()?.host());
/** the layout: one, New (open-source wave 1, PR 1.4). A stored `shell.layout: classic` (or an
 * older the server's two switches off) reads as New; the server keeps what the file says. */
export function layoutOf(_a: Arrangement | null): Layout {
  return "new";
}
/** the frame: the home at #/, the doors' heads and subnavs, the one sheet, the phone's tab bar,
 * whenever the server hosts the page (brb ui alone keeps 0.4.10's tree) */
export const frameNew = (host: boolean): boolean => shellDoors(host);
/** the classic frame is gone: never drawn */
export const frameClassic = (_host: boolean): boolean => false;

/** one write through the one writer (POST /api/shell), its answer drawn at once */
export function arrange(key: string, value: unknown, btn: HTMLElement | null = null, said?: string): Promise<void> {
  const L = app();
  if (!L) return Promise.resolve();
  return L.act(btn, async () => put(SHELL_API, await L.api(SHELL_API, { key, value })), () => {
    if (said) L.say(said);
    else L.render();
  });
}
/** Arrange's Reset to defaults: every pin, hide, cap and allowance back to its default */
export function arrangeReset(btn: HTMLElement | null = null): Promise<void> {
  const L = app();
  if (!L) return Promise.resolve();
  return L.act(btn, async () => put(SHELL_API, await L.api(SHELL_API, { reset: true })), () => L.say("The home is back to its defaults: every cub in install order, Needs you by trust."));
}
/** the pins with one moved by step (‹ -1, › +1) */
export function moved(pins: string[], id: string, step: number): string[] {
  const i = pins.indexOf(id), j = i + step;
  if (i < 0 || j < 0 || j >= pins.length) return pins;
  const out = pins.slice();
  [out[i], out[j]] = [out[j]!, out[i]!];
  return out;
}

/** a cub's place, or its defaults when the arrangement has no row for it yet */
export function placeOf(a: Arrangement | null, id: string, trust: string): CubPlace {
  return a?.cubs.find((c) => c.id === id) || { id, trust, pinned: true, place: null, hidden: false, needs_you: trust === "first-party" || trust === "owner", new: true };
}
