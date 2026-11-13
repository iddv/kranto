// Every settings Save: the write, then one toast that says what was saved
// and when it takes effect, with Undo for 9 s that writes the previous value back. A Save with
// nothing to go back to (a new key, a first version) passes no undo and gets the plain toast.
import { app } from "../lib/shell.svelte";
import { saidSaved, type Effect } from "../lib/words";

export interface SaveOpts {
  /** what the write does: the request, then whatever must be read again */
  write: () => Promise<unknown>;
  /** what was saved, from the answer ("builds a day, no cap") */
  what: (r: unknown) => string;
  effect: Effect;
  /** the previous value written back, or null when there is nothing to go back to */
  undo?: (() => Promise<unknown>) | null;
  /** after the write and after an Undo: drop the reads, redraw */
  after?: () => void;
}

export function saveUndo(btn: HTMLElement | null, o: SaveOpts): Promise<void> | undefined {
  const L = app();
  if (!L) return;
  return L.act(btn, o.write, (r) => {
    o.after?.();
    const text = saidSaved(o.what(r), o.effect);
    const undo = o.undo;
    L.toast(text, undo ? () => void L.act(null, undo, () => {
      o.after?.();
      L.toast("Undone: the previous value is back.");
    }) : null);
    L.render();
  });
}
