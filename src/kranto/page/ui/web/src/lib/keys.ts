// The one key map (UI-v4.md 2.4). Every shortcut is declared once, in keys.json (the Python
// tests read it too); the ? sheet, the nav's tooltips and the palette's hints are drawn from it.
// action() is a pure function from (key, state) to what to do; the shell carries it out.
// A row's "go" is a route; "run" is a shell verb; "page" is a verb the page declares through
// its page keys (p on an idea, 1 on a row, ...), so the same letter can mean the page's own
// primary action and does nothing on a page that has none.
import KEYS_JSON from "./keys.json";

export interface KeyRow {
  group: string;
  keys: string;
  does: string;
  go?: string;
  run?: string;
  page?: boolean;
}
export interface QueueKey {
  keys: string;
  does: string;
  do: string;
  value?: string;
  at?: number;
}
export const KEYMAP: readonly KeyRow[] = KEYS_JSON.KEYMAP;
export const QUEUE_KEYS: readonly QueueKey[] = KEYS_JSON.QUEUE_KEYS;

/** The name a keydown is known by in KEYMAP: "j", "⇧x", "⌘K", "⌘a", "enter", "esc", "?". */
export function keyName(e: Pick<KeyboardEvent, "key" | "altKey" | "metaKey" | "ctrlKey" | "shiftKey">): string | null {
  const k = e.key || "";
  if (e.altKey) return null;
  if (e.metaKey || e.ctrlKey)
    return k.toLowerCase() === "k" ? "⌘K" : k.toLowerCase() === "j" && !e.shiftKey ? "⌘J" : k.toLowerCase() === "a" ? "⌘a" : k === "Enter" ? "⌘enter" : null;
  if (k === "Enter") return "enter";
  if (k === "Escape") return "esc";
  if (k === "Tab") return e.shiftKey ? null : "tab"; // acts only on a focused row (action), else the browser's
  if (k.length !== 1) return null;
  if (e.shiftKey && /^[a-z]$/i.test(k)) return "⇧" + k.toLowerCase();
  return k;
}

const GO_KEYS: Record<string, string> = {}; // "t" -> "needs", from the "g x" rows
for (const m of KEYMAP) if (m.go && /^g [a-z]$/.test(m.keys)) GO_KEYS[m.keys.slice(2)] = m.go;
const BY_KEY: Record<string, KeyRow> = {};
for (const m of KEYMAP) if (!m.go) BY_KEY[m.keys] = m;
const ROW_RUNS = new Set(["next", "prev", "nextGroup", "prevGroup", "primary"]);

export interface KeyState {
  /** focus is in a field or a dialog is open: nothing fires but ⌘K */
  typing: boolean;
  /** "g" after a g was pressed, else null */
  chord: string | null;
  /** the page has rows to move over */
  rows: boolean;
  /** one of them is focused (enter acts) */
  focused: boolean;
  /** the keys the page declares */
  pageKeys: Set<string>;
}
export type KeyAction =
  | { go: string }
  | { topic: number }
  | { run: string }
  | { page: string }
  | { chord: string };

/** What a key does; null: the browser's own. */
export function action(key: string | null, state: KeyState): KeyAction | null {
  if (!key) return null;
  if (key === "⌘K") return { run: "palette" };
  if (key === "⌘J") return { run: "console" }; // from anywhere, a field's included
  if (state.typing) return null;
  if (state.chord === "g") {
    if (/^[1-9]$/.test(key)) return { topic: Number(key) };
    const to = GO_KEYS[key];
    return to ? { go: to } : null;
  }
  const pk = state.pageKeys || new Set();
  if (pk.has(key)) return { page: key }; // the page's verb wins over a shell one (o, x...)
  if (key === "g") return { chord: "g" };
  const m = BY_KEY[key];
  if (!m || m.page || !m.run) return null;
  if (m.run === "pane" && !state.focused) return null; // tab moves the browser's focus unless a row has the cursor
  if (ROW_RUNS.has(m.run)) {
    if (!state.rows) return null;
    if (m.run === "primary" && !state.focused) return null; // enter on a link is the link's
  }
  return { run: m.run };
}

/** the g chord's menu, in the status bar while it is pending */
export const CHORD_HINT = "g then: h Home · w Watch · t Needs you · r Review · i Ideas · n News · l Evidence · a Activity · s Settings · 1–9 a topic";

/** The "g x" keys of a route, for its tooltip, the ? sheet and the palette. */
export const hint = (go: string): string | null => KEYMAP.find((m) => m.go === go)?.keys || null;

const QUEUE_BY: Record<string, QueueKey> = {};
for (const m of QUEUE_KEYS) QUEUE_BY[m.keys] = m;
export interface QueueState {
  chips?: number;
  chipTarget?: unknown;
  done?: boolean;
}
export interface QueueAction {
  do: string;
  value?: string;
  at?: number;
}
/** The review queue's keys (LEARNING.md 3.4): one item at a time, no pointer needed. */
export function queueAction(key: string, state: QueueState): QueueAction | null {
  const m = QUEUE_BY[key];
  if (!m) return null;
  if (state.done) return m.do === "prev" ? { do: "prev" } : null;
  if (m.do === "grade") return { do: "grade", value: m.value };
  if (m.do === "chip") return state.chipTarget && (m.at ?? 0) < (state.chips || 0) ? { do: "chip", at: m.at } : null;
  return { do: m.do };
}
