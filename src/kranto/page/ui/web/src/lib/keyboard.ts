// The keys, carried out (keys.json has the map, keys.ts decides): the shell's own verbs here
// (go, a topic, the palette, the ? sheet, find, esc's order), the rows' and the pane's verbs and
// the page's own keys through the app (lib/app/rows.ts).
import { action, keyName, type KeyAction } from "./keys";
import { go } from "./router";
import { inTerminal } from "../term/state.svelte";
import { inConsole, toggleConsole } from "../term/console.svelte";
import { app, navDrawer, openPalette, ui } from "./shell.svelte";

let chordAt = 0;
const CHORD_MS = 1500;

/** the chord the next key completes ("g"), if it was pressed within 1.5 s */
export const chordNow = (): string | null => (ui.chord && Date.now() - chordAt < CHORD_MS ? ui.chord : null);

export function onKeydown(e: KeyboardEvent): void {
  const L = app();
  if (!L) return;
  if ((document.getElementById("pal") as HTMLDialogElement | null)?.open) return; // the palette has its own keys
  // ⌘J (ctrl+J): the console, from anywhere, a terminal's included (keys.json)
  if (keyName(e) === "⌘J") {
    e.preventDefault();
    toggleConsole();
    return;
  }
  if (inTerminal(e.target) || inConsole(e.target)) return; // every key in a terminal is its own (ctrl+] leaves it)
  const key = keyName(e);
  if (!key) return;
  const first = L.keyFirst(key); // a popover's esc and why chips
  if (first) {
    if (first === "prevent") e.preventDefault();
    return;
  }
  const chord = chordNow();
  ui.chord = null;
  const active = document.activeElement as HTMLElement | null;
  const idle = !active || active === document.body || active.id === "dscroll" || active.id === "rows";
  const a = action(key, {
    typing: L.typing() || !!(active && active.isContentEditable),
    chord,
    rows: L.rowsNow().length > 0,
    focused: !!L.rowNow() && idle,
    pageKeys: new Set(L.pageKeys()),
  });
  if (!a) return;
  if ("chord" in a) {
    ui.chord = a.chord;
    chordAt = Date.now();
    e.preventDefault();
    setTimeout(() => {
      if (!chordNow()) ui.chord = null;
    }, CHORD_MS + 100);
    return;
  }
  if (doKey(a)) e.preventDefault();
}

/** one action of the map; true when it acted (the key's default is then prevented) */
export function doKey(a: KeyAction): boolean {
  const L = app();
  if (!L) return false;
  if ("go" in a) {
    if (!L.hasView(a.go)) return false;
    go(a.go);
    return true;
  }
  if ("topic" in a) {
    const t = L.topicAt(a.topic);
    if (!t) return false;
    go("topics/" + t.id);
    return true;
  }
  if ("page" in a) {
    L.runPageKey(a.page);
    return true;
  }
  if (!("run" in a)) return false;
  switch (a.run) {
    case "console":
      toggleConsole();
      return true;
    case "palette":
      openPalette("");
      return true;
    case "find": {
      const s = (document.querySelector("#rows #search") || document.getElementById("search")) as HTMLElement | null;
      if (s) s.focus();
      else openPalette("");
      return true;
    }
    case "sheet":
      L.keySheet();
      return true;
    case "close": // the Claude Code panel, then the navigator's drawer, then the ticks, then the selection
      return L.closeKey(ui.navOpen, () => navDrawer(false));
    case "menu":
    case "next":
    case "prev":
    case "nextGroup":
    case "prevGroup":
    case "nextSection":
    case "prevSection":
    case "open":
    case "pane":
    case "primary":
      return L.rowKey(a.run);
  }
  return false;
}
