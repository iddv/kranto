// An incident put away by the owner (#488: "Your OpenRouter key is refused" stayed for a day of
// good calls and nothing could put it away): the server keeps it away until it happens again. The
// band, Needs you's Fix row and the home's row share this one call.
import { ACT_PATH } from "../lib/activity";
import { drop } from "../lib/reads.svelte";
import { app } from "../lib/shell.svelte";

export function dismissIncident(id: string, btn: HTMLElement): void {
  const L = app();
  if (!L) return;
  void L.act(btn, () => L.api("/api/activity/dismiss", { incident: id }), () => {
    drop(ACT_PATH, true);
    L.toast("Put away. It comes back only if it happens again.");
    L.render();
  });
}
