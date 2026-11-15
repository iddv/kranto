// Read sources now (Watch's Topics and Sources,): it spends, so the house confirm
// first, then the server's /run/ingest; what it keeps shows on the page, and the page's RunLine
// (kind:ingest) says the read in hand, with Stop.
import { app } from "../../lib/shell.svelte";
import { confirmThen } from "../../ui/dialog.svelte";

export function readSourcesNow(btn: HTMLElement): void {
  confirmThen("Read every source now?", "Every active source is read and its new items judged: model calls through your provider, as a scheduled read makes. What it keeps shows here.", "Read now", () => {
    const L = app();
    void L?.act(btn, async () => {
      const r = await L.hostForm("/run/ingest");
      L.afkDrop();
      return r;
    }, () => L.say("Reading every source now. What it keeps shows here when it finishes."));
  });
}
