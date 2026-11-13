<script lang="ts">
  // Explain <what> (a cluster, an observation's neighbourhood): one model call in the background,
  // the answer kept by the server; the button says how long it has run.
  import { afkJob } from "../lib/job";
  import { app } from "../lib/shell.svelte";

  let { body, what }: { body: Record<string, string | number>; what: string } = $props();
  let busy = $state<string | null>(null);
  function press(btn: HTMLElement): void {
    const L = app();
    if (!L) return;
    busy = "Asking the model…";
    const w = what, b = body;
    void L.act(btn, async () => {
      const r = await afkJob(await L.api("/api/explain", b), "/api/explain?" + new URLSearchParams(Object.entries(b).map(([k, v]) => [k, String(v)])), (s) => { busy = `Asking the model… (${s} s)`; });
      L.afkDrop();
      return r;
    }, () => { busy = null; L.say(`Explained ${w}.`); }).finally(() => { busy = null; });
  }
</script>

<div class="inline"><button class="btn" onclick={(e) => press(e.currentTarget)}>{busy || "Explain " + what}</button><span class="muted small">one model call; the answer is kept</span></div>
