// What the pages read: one cached GET each (lib/reads.svelte.ts), read again once it is
// older than a few seconds on the next draw, and the list's route while one of its rows is open.
import { read as cached, type Read } from "../lib/reads.svelte";
import type { Where } from "../lib/pages.svelte";
import type { Route } from "../lib/router";

/** a GET, cached by path, at most 10 s old once the page draws again */
export const read = <T>(path: string): Read<T> => cached<T>(path, 10000);

/** a path with its query, as the API takes it */
export const q = (path: string, query: Record<string, string | number>): string =>
  path + "?" + new URLSearchParams(Object.entries(query).map(([k, v]) => [k, String(v)])).toString();

/** where() with the focus: the section an object's route names */
export type FocusWhere = Where & { focus?: string | null };

/** the object's own route for its pane (the section kept), else null */
export function objectRoute(w: FocusWhere): Route | null {
  if (!w.object || !w.obj) return null;
  return { path: w.obj, q: w.sel ? {} : w.r.q, sel: null };
}

/** a list's filters while one of its rows is open (the list keeps them), forgotten when the list is
 * reached from another page through a link to one of its objects (N9: a deep link never brings
 * back an old filter) */
const LISTQ: Record<string, Record<string, string>> = {};
let lastNode: string | null = null;
export function listRoute(w: FocusWhere): Route {
  const node = w.node || "";
  if (!w.object || w.sel) LISTQ[node] = w.r.q;
  else if (lastNode !== node) delete LISTQ[node];
  lastNode = node;
  return w.object && !w.sel ? { path: w.list, q: LISTQ[node] || {}, sel: null } : w.r;
}
