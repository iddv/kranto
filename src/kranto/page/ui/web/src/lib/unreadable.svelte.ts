// One bad row never takes a page down, on the page's side. A list either API
// builds row by row may hold, in a row's place, one it could not read: {id, what it still knew (a
// label, a name, a title), unreadable: {what, words, error_id, exception}} (the server and the page
// rowsafe.py). The pages draw their own rows' shapes, never this one, so every read takes such rows
// out of its lists here, as it arrives (`contain`), and keeps them by the read's path. The shell
// lists them under the page's head (ui/Unreadables.svelte): one line each, "Couldn't read this
// source · Energy Feed · error 1a2b3c4d", with Send this error. Which reads are the page's: those
// the last draw asked for (`read()` notes each).
//
// A whole answer that failed (status 500) says its error's id in its words, "… (error 1a2b3c4d) …":
// `errorIdOf` finds it there, so Failed and a red flash offer Send this error too.
import { SvelteMap } from "svelte/reactivity";

export interface Mark {
  what: string;
  words: string;
  error_id: string;
  exception: string;
}
export interface Unreadable {
  id: unknown;
  label: string | null;
  unreadable: Mark;
}

const DEPTH = 4;
const KEPT = new SvelteMap<string, Unreadable[]>();

const isMark = (x: unknown): x is Mark => !!x && typeof x === "object" && typeof (x as Mark).error_id === "string" && typeof (x as Mark).what === "string";
export const isUnreadable = (x: unknown): x is Unreadable => !!x && typeof x === "object" && isMark((x as { unreadable?: unknown }).unreadable);

/** what a row still says of itself: its label, name, title or repo, else its id */
export function labelOf(r: Record<string, unknown>): string | null {
  for (const k of ["label", "name", "title", "repo", "key"]) {
    const v = r[k];
    if (typeof v === "string" && v.trim()) return v.trim().slice(0, 120);
  }
  return r.id == null ? null : String(r.id).slice(0, 60);
}

/** body with every unreadable row taken out of its list (to DEPTH), those rows kept under path */
export function contain<T>(path: string, body: T): T {
  const found: Unreadable[] = [];
  const walk = (x: unknown, depth: number): void => {
    if (depth > DEPTH || !x || typeof x !== "object") return;
    if (Array.isArray(x)) {
      for (let i = x.length - 1; i >= 0; i--) {
        const r = x[i];
        if (isUnreadable(r)) {
          found.unshift({ id: r.id, label: labelOf(r as unknown as Record<string, unknown>), unreadable: r.unreadable });
          x.splice(i, 1);
        } else walk(r, depth + 1);
      }
      return;
    }
    for (const v of Object.values(x as Record<string, unknown>)) walk(v, depth + 1);
  };
  walk(body, 0);
  if (found.length) KEPT.set(path, found);
  else if (KEPT.has(path)) KEPT.delete(path);
  return body;
}

// -- the reads the page draws -----------------------------------------------------------------------
let drawing = new Set<string>();
let drawn = $state<string[]>([]);
/** a draw begins: the reads it asks for are noted from now (route.ts) */
export function drawStarts(): void {
  drawing = new Set();
}
/** a read the draw asked for (reads.svelte.ts's read) */
export function asked(path: string): void {
  drawing.add(path);
}
/** the draw is done: its reads are the page's */
export function drawEnds(): void {
  const next = [...drawing].sort();
  if (next.join("\n") !== drawn.join("\n")) drawn = next;
}

/** the unreadable rows of what this page shows: its reads' (the page's first part, `_first`, is
 * kept for the callers) */
export function onPage(_first: string): Unreadable[] {
  const out: Unreadable[] = [];
  const seen = new Set<string>();
  const add = (rs: Unreadable[] | undefined) => {
    for (const r of rs || []) {
      const k = r.unreadable.what + ":" + String(r.id);
      if (!seen.has(k)) {
        seen.add(k);
        out.push(r);
      }
    }
  };
  for (const p of drawn) add(KEPT.get(p));
  return out;
}
/** every unreadable row kept now (a test, the self-check's walk) */
export const allKept = (): Unreadable[] => [...KEPT.values()].flat();
export function forget(): void {
  KEPT.clear();
  drawn = [];
}

// -- a failed answer --------------------------------------------------------------------------------
/** the error id a failed answer's words carry ("… (error 1a2b3c4d) …"), else null */
export function errorIdOf(text: string | null | undefined): string | null {
  const m = /\(error ([0-9a-f]{8})\)/.exec(String(text || ""));
  return m ? m[1]! : null;
}
