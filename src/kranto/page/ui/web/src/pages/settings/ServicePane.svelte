<script lang="ts">
  // Settings › System › Where Kranto runs: the address, the homes and the version, read-only; what
  // changes them is a command on the machine (kranto setup system), and they apply after a restart.
  import Detail from "../../ui/Detail.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Kv from "../../ui/Kv.svelte";
  import Pane from "../../ui/Pane.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { app } from "../../lib/shell.svelte";
  import { EFFECT } from "../../lib/words";
  import { kindLine, SET_ST } from "../../ui/settings";

  let { view }: { view: View } = $props();
  const H = $derived((app()?.host() || null) as { version?: string } | null);
</script>

<Detail back={view.back}>
  <Pane title="Where Kranto runs" lede="One service on this machine, on 127.0.0.1 only: the page and watching in one process." sections={[{ id: "now", w: "Now" }, { id: "change", w: "To change it" }]}>
    {#snippet kind()}<Glyph name={SET_ST.set[0]} colour={SET_ST.set[1]} word={SET_ST.set[2]} />{kindLine("system", "service")}{/snippet}
    {#snippet section(s)}
      {#if s.id === "now"}<Kv rows={[["Address", location.host, "mono"], ["Version", H?.version || "–"]]} />
      {:else}<p class="small">On the machine Kranto runs on: <code>kranto setup system</code> (the home, the port, and whether Kranto runs as a service that starts at boot); <code>kranto paths</code> lists where everything is kept.</p><p class="muted small">{EFFECT.restart}</p>{/if}
    {/snippet}
  </Pane>
</Detail>
