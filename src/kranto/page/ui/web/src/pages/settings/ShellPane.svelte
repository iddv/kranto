<script lang="ts">
  // Settings › System › The home, the pane: the rows Needs you and New show at most, each change
  // one write through the one writer (POST /api/shell). The pins, what is hidden and which cubs may
  // add rows are Arrange on the home; the layout is Settings › Appearance › Layout.
  import Detail from "../../ui/Detail.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Pane from "../../ui/Pane.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { app } from "../../lib/shell.svelte";
  import { kindLine, SET_ST } from "../../ui/settings";
  import { arrange, arrangement } from "../../features/shell";
  import { resetHome } from "../../features/home";

  let { view }: { view: View } = $props();
  const a = $derived.by(() => {
    void view.tick;
    return arrangement(!!app()?.host());
  });
  function cap(key: string, e: Event): void {
    const v = Number((e.currentTarget as HTMLInputElement).value);
    if (Number.isInteger(v)) void arrange(key, v, null, "Saved: the home follows it.");
  }
</script>

<Detail back={view.back}>
  {#if a}
    <Pane title="Rows at most" lede="Needs you and New stay short on the home; and N more opens the rest.">
      {#snippet kind()}<Glyph name={SET_ST.set[0]} colour={SET_ST.set[1]} word={SET_ST.set[2]} />{kindLine("system", "the home")}{/snippet}
      {#snippet top()}<div class="caps"><label>Needs you <input type="number" id="hf-needs-cap" min="1" max="10" value={a.needs_cap} onchange={(e) => cap("shell.needs_cap", e)} /></label>
        <label>New today <input type="number" id="hf-new-cap" min="0" max="10" value={a.new_cap} onchange={(e) => cap("shell.new_cap", e)} /></label></div>
        {#if a.widgets}
          <p class="small"><a href="#/home?arrange=1" id="hf-arrange">Arrange the home</a>: move, size, add and remove its widgets; the features' pins; which features may add rows (each widget's ⋯).</p>
          <p class="small"><button class="btn sm" id="hf-reset" onclick={(e) => a && resetHome(a, e.currentTarget)}>Reset to default</button> <span class="muted">the home as it came: its seven parts in their order, every added feature pinned in install order; Undo for a few seconds.</span></p>
        {:else}<p class="small"><a href="#/home?arrange=1">Arrange the home</a>: the pins, what is hidden, which features may add rows.</p>{/if}{/snippet}
    </Pane>
  {:else}
    <div class="pane-empty"><p class="empty">The home comes from the server, which is not answering.</p></div>
  {/if}
</Detail>

<style>
  .caps { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; margin: 6px 0; }
  .caps input { width: 70px; margin-left: 6px; }
</style>
