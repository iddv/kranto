// What every Settings page shares (WORKSPACE.md 2.12): a page is a list of its setting groups
// and real rows (a group's state, its name and its value in one line, never a field), and a
// group's form is in the detail pane when it is selected (sel=e<key>).
import { href } from "../lib/router";
import type { Where } from "../lib/pages.svelte";

/** a group's state: [icon, colour, word] */
export type St = readonly [string, string, string];
/** the one set of Settings' state words; a page adds a word only here. One glyph
 * per word and one word per glyph (UP #10): Off and Default, Set and Changed, Needs you and Missing
 * used to share one. */
export const SET_ST = {
  ok: ["check", "green", "Ok"], warn: ["warn", "amber", "Needs you"], off: ["skipped", "grey", "Off"],
  set: ["dot", "blue", "Set"], dflt: ["open", "grey", "Default"], changed: ["queued", "amber", "Changed, not saved"],
  missing: ["failed", "amber", "Missing"], checking: ["running", "grey", "Checking…"], offered: ["closed", "grey", "Not offered"],
  broken: ["x", "red", "Not working"], waiting: ["waiting", "grey", "Waiting"], paused: ["paused", "grey", "Paused"],
  hand: ["file", "amber", "By hand"],
} as const satisfies Record<string, St>;
/** what each word means: the legend under Settings' ? and on every Settings page's pane */
export const SET_LEGEND: [St, string][] = [
  [SET_ST.ok, "working, or turned on and fine"], [SET_ST.warn, "waiting on you: open it to see what"],
  [SET_ST.broken, "tried and failed: open it for the error"], [SET_ST.missing, "something it needs is not there"],
  [SET_ST.set, "a value you chose"], [SET_ST.dflt, "Kranto's default: nothing chosen"],
  [SET_ST.changed, "typed here, not saved yet"], [SET_ST.off, "turned off"],
  [SET_ST.waiting, "waiting for something else first"], [SET_ST.paused, "paused by you"],
  [SET_ST.checking, "being read now"], [SET_ST.offered, "not offered on this install"],
  [SET_ST.hand, "written by hand in your settings file: shown here, changed there"],
];
/** a status word's one glyph and colour, whatever a page asked for (Glyph draws a word with it) */
const BY_WORD: Record<string, St> = Object.fromEntries(Object.values(SET_ST).map((s) => [s[2], s]));
// the pages' older words for the same states, drawn with that state's glyph
for (const [w, k] of [["Failed", "broken"], ["Can't be used", "broken"], ["Cannot reach it", "broken"], ["Works", "ok"],
  ["Connected", "ok"], ["Ready", "ok"], ["On", "ok"], ["Not connected", "off"], ["Unknown", "checking"]] as const)
  BY_WORD[w] = [SET_ST[k][0], SET_ST[k][1], w];
export const stOfWord = (word: string): St | null => BY_WORD[word] || null;

/** a Settings pane's kind line, after its glyph: "settings · <page>" on a
 * page's own pane, "<page> · <group>" on a group's; always lower case */
export const kindLine = (page: string, group?: string | null): string =>
  " " + (group ? `${page} · ${group}` : `settings · ${page}`).toLowerCase();

/** the selected group's key (sel=e<key>), or null with nothing selected */
export const groupOf = (w: Where): string | null =>
  w.object === "need" && w.id && w.id.startsWith("e") ? w.id.slice(1) : null;

/** this route with a row selected (the list's rows open in the pane this way) */
export const selHref = (w: Where, code: string): string =>
  href(w.r.path.map(encodeURIComponent).join("/"), { ...w.r.q, sel: code });
