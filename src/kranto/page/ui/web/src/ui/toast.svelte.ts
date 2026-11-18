// The toast: one line at the bottom right, with Undo; never part of the page, so a
// page's redraw leaves it be (Toast.svelte draws it, once one has been said). A red one is an
// error: Feedback's details name the last few, and it offers Tell us.
import { noteError } from "./feedback";

export const TOAST = $state<{ text: string; undo: (() => void) | null; kind: string; shown: boolean; hidden: boolean }>({
  text: "", undo: null, kind: "", shown: false, hidden: true,
});
let timer: ReturnType<typeof setTimeout> | undefined;

/** its words, an Undo when undo is given (9 s, else 5 s; a red one 9 s, for its Tell us) */
export function toast(text: string, undo?: (() => void) | null, kind?: string): void {
  if (kind === "red") noteError(text);
  Object.assign(TOAST, { text, undo: undo || null, kind: kind || "", shown: true, hidden: false });
  clearTimeout(timer);
  timer = setTimeout(() => {
    TOAST.hidden = true;
  }, undo || kind === "red" ? 9000 : 5000);
}
