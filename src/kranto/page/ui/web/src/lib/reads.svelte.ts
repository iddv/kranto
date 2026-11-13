// A moved page's reads (the server's JSON, the page's API): cached by path, reactive, read again
// once older than the page asks (maxAge) on the next draw, so the live feed's reads keep them
// fresh. Never a request on the server's side: a read waits on local state only (is
// the server's; the page just never blocks on one read for another).
import { SvelteMap } from "svelte/reactivity";
import { asked, contain } from "./unreadable.svelte";

export interface Read<T> {
  data: T | null;
  error: string | null;
  at: number;
  loading: boolean;
}
const READS = new SvelteMap<string, Read<unknown>>();
let fetcher: (path: string) => Promise<unknown> = async (path) => {
  const r = await fetch(path, { cache: "no-store" });
  const text = await r.text();
  let body: unknown = null;
  try {
    body = JSON.parse(text);
  } catch {
    body = text;
  }
  if (!r.ok) {
    const e = (body as { error?: unknown } | null)?.error;
    // never a JSON body as the words
    throw new Error(typeof e === "string" ? e : (!/^\s*[[{]/.test(text) && text.trim()) || r.statusText || `HTTP ${r.status}`);
  }
  return contain(path, body);
};
/** how reads go out: the app's api() (it notes a 401 for the sign-in line) */
export function setFetcher(f: (path: string) => Promise<unknown>): void {
  fetcher = f;
}
let arrived: (ok: boolean) => void = () => {};
/** what a read's answer sets off: the page draws again (the selection, the key hint and the
 * outline follow what arrived), as the old page's reads did */
export function onArrive(f: (ok: boolean) => void): void {
  arrived = f;
}

const EMPTY: Read<never> = { data: null, error: null, at: 0, loading: true };

/** the cached answer for path, asking again when it is older than maxAge (or never read) */
export function read<T>(path: string, maxAge = 30000): Read<T> {
  asked(path); // the page's reads: their unreadable rows are listed under its head
  const c = READS.get(path) as Read<T> | undefined;
  if ((!c || (Date.now() - c.at > maxAge && !c.loading)) && !(c && c.loading)) queueMicrotask(() => load(path));
  return c || EMPTY;
}
async function load(path: string): Promise<void> {
  const c = READS.get(path);
  if (c?.loading) return;
  READS.set(path, { ...(c || { data: null, error: null, at: 0 }), loading: true });
  try {
    READS.set(path, { data: await fetcher(path), error: null, at: Date.now(), loading: false });
    arrived(true);
  } catch (e) {
    READS.set(path, { data: c?.data ?? null, error: (e as Error).message, at: Date.now(), loading: false });
    arrived(false);
  }
}
/** a write's answer replaces what the page shows (a token list after Rotate) */
export function put<T>(path: string, data: T): void {
  READS.set(path, { data, error: null, at: Date.now(), loading: false });
}
/** the next draw reads these again (exact: that path alone, not the paths under it) */
export function drop(prefix: string, exact = false): void {
  if (exact) READS.delete(prefix);
  else for (const k of [...READS.keys()]) if (k.startsWith(prefix)) READS.delete(k);
}
/** the next draw reads these again (paths under prefix), showing what was read meanwhile: a list
 * never blanks to "Loading…" (the app's afkStale) */
export function stale(prefix: string): void {
  for (const [k, c] of [...READS.entries()]) if (k.startsWith(prefix) && c.data != null && !c.loading) READS.set(k, { ...c, at: 0 });
}
/** Try again (ui/Failed.svelte): every read that failed is asked again on the next draw, or path's alone */
export function retry(path: string | null = null): void {
  for (const [k, c] of [...READS.entries()]) if ((path ? k === path : true) && c.error && !c.loading) READS.delete(k);
}
/** what is cached for path, never asking (a count from a page read once it was opened) */
export function peek<T>(path: string): Read<T> | null {
  return (READS.get(path) as Read<T> | undefined) ?? null;
}
