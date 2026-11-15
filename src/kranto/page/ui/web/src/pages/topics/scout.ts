// Scout more (the topic's head and its Edit sheet,): the scout's job runs in the
// background (the button says for how long); its close matches are ticked on the topic's
// Sources, which it opens with what the scout said.
import { go } from "../../lib/router";
import { app } from "../../lib/shell.svelte";
import { afkJob, type Scouted } from "../welcome/welcome.svelte";
import { TICKS } from "./proposals";

export function scoutMore(btn: HTMLElement | null, x: { id: number }, word: (w: string | null) => void): Promise<void> {
  const L = app();
  if (!L) return Promise.resolve();
  word("Scouting…");
  return L.act(btn, async () => {
    const r = await afkJob<Scouted>(L, await L.api(`/api/topics/${x.id}/scout`, {}), `/api/topics/${x.id}/scout`, "Scouting", (w) => word(w));
    L.afkDrop();
    return r;
  }, (r) => {
    const s = r as Scouted, tk = (TICKS[x.id] ||= new Set());
    for (const p of s.proposals) if (p.pretick) tk.add(p.id);
    go(`topics/${x.id}/sources`);
    L.say(s.message + " Tick what to watch under Proposed.");
  }).finally(() => word(null));
}
