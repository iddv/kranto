// Mark all seen (⇧a): the last-visit marker moves to now (opening a page never moves it), with
// Undo back to where it was.
import { peek } from "../../lib/reads.svelte";
import { app } from "../../lib/shell.svelte";
import { TODAY_API } from "./needs";

export function markSeen(btn: HTMLElement | null): Promise<void> {
  const L = app();
  if (!L) return Promise.resolve();
  const before = (peek<{ since?: string }>(TODAY_API)?.data || {}).since;
  const fresh = () => { L.afkStale("/api/today", "/api/observations"); L.render(); };
  return L.act(btn, () => L.api("/api/seen", {}), (r) => {
    fresh();
    L.toast("Marked everything seen: new counts from now.", () => void L.act(null, () => L.api("/api/seen", { at: (r as { previous?: string } | null)?.previous || before }), fresh));
  });
}
