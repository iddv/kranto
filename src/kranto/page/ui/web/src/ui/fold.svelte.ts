// Folded groups (UP #7): a long list's group (Sources' Wildcards, Proposed…) folds to its heading
// with the twisty in its heading, remembered per viewer in this browser's localStorage. A storage
// that cannot be read or written (private windows, a full quota) leaves every group open and the
// fold for this page's life only. A group may start folded (R4: Needs you's Decide,
// a group past the first screen): opening it is remembered as the viewer's choice (OPENED).
import { SvelteSet } from "svelte/reactivity";

export const FOLD_KEY = "kranto.folded";
export const OPEN_KEY = "kranto.unfolded";

function names(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
}
function load(): string[] {
  try {
    return names(JSON.parse(localStorage.getItem(FOLD_KEY) || "[]"));
  } catch {
    return [];
  }
}
function loadOpen(): string[] {
  try {
    return names(JSON.parse(localStorage.getItem(OPEN_KEY) || "[]"));
  } catch {
    return [];
  }
}

/** the folded groups' keys ("sources:wildcard", "topic-sources:proposed", …) */
export const FOLDED = new SvelteSet<string>(load());
/** the groups that start folded and the viewer opened */
export const OPENED = new SvelteSet<string>(loadOpen());


/** is the group folded: the viewer's choice, else where it starts */
export const isFolded = (key: string, start = false): boolean => FOLDED.has(key) || (start && !OPENED.has(key));

export function setFolded(key: string, on: boolean): void {
  if (on) {
    FOLDED.add(key);
    OPENED.delete(key);
  } else {
    FOLDED.delete(key);
    OPENED.add(key);
  }
  try {
    localStorage.setItem(FOLD_KEY, JSON.stringify([...FOLDED]));
    localStorage.setItem(OPEN_KEY, JSON.stringify([...OPENED]));
  } catch {
    // not kept: the fold lasts until the page is reloaded
  }
}
