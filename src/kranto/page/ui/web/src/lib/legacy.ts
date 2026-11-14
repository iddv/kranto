// Names from before the product was called Kranto that a browser may still hold: the page's
// counterpart of src/kranto/legacy.py, and the only file of the page that holds them (a test
// refuses them anywhere else). Nothing is moved: each old key is read once, when the new one is
// missing, copied to the new name and left where it is.
import { COMMAND } from "./product";

const OLD = "be" + "ars"; // written in two parts so a search for the old name finds it here only

/** the keys kept in this browser's localStorage, without their prefix */
export const BROWSER_KEYS = ["theme", "look", "look.custom", "layout"] as const;
export type BrowserKey = (typeof BROWSER_KEYS)[number];

export const newKey = (name: BrowserKey): string => `${COMMAND}.${name}`;
export const oldKey = (name: BrowserKey): string => `${OLD}.${name}`;
/** the old keys already read, so one cleared since (a theme set back to Auto) stays cleared */
export const ADOPTED_KEY = `${COMMAND}.adopted`;

type Store = Pick<Storage, "getItem" | "setItem">;

function adopted(storage: Store): string[] {
  try {
    const x = JSON.parse(storage.getItem(ADOPTED_KEY) || "[]") as unknown;
    return Array.isArray(x) ? x.map(String) : [];
  } catch { return []; }
}

/** the stored value of ``name``: the new key's; when it is missing, the old key's, read once and
 *  copied to the new key (the old one is left). null when neither holds one, or storage is off. */
export function stored(name: BrowserKey, storage?: Store): string | null {
  try {
    const s = storage ?? localStorage;
    const now = s.getItem(newKey(name));
    if (now !== null) return now;
    const seen = adopted(s);
    if (seen.includes(name)) return null;
    const old = s.getItem(oldKey(name));
    if (old === null) return null;
    s.setItem(newKey(name), old);
    s.setItem(ADOPTED_KEY, JSON.stringify([...seen, name]));
    return old;
  } catch { return null; }
}

/** every old key copied where the new one is missing (as the app loads); the names copied */
export function adoptStored(storage?: Store): BrowserKey[] {
  const s = storage ?? (typeof localStorage === "undefined" ? undefined : localStorage);
  if (!s) return [];
  const copied: BrowserKey[] = [];
  for (const name of BROWSER_KEYS) {
    let had = true;
    try { had = s.getItem(newKey(name)) !== null; } catch { /* storage off */ }
    if (!had && stored(name, s) !== null) copied.push(name);
  }
  return copied;
}
