<script lang="ts">
  // A Settings page's pane with nothing selected: what the page holds, its groups in the
  // order the list draws them, and what each state's mark means (UP #10); and "No such setting."
  // for a selection the page does not have.
  import Detail from "../../ui/Detail.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Pane from "../../ui/Pane.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { kindLine, SET_LEGEND } from "../../ui/settings";
  // Accounts (the doors' page) too
  import { doorsSetPage as setPage } from "./doorpages";

  let { view, missing = false }: { view: View; missing?: boolean } = $props();
  const p = $derived(setPage(view.w.node));
</script>

<Detail back={view.back}>
  {#if missing || !p}
    <div class="pane-empty"><p class="empty">No such setting.</p></div>
  {:else}
    <Pane title={p.title} lede={p.lede} sections={[{ id: "groups", w: "Its groups" }, { id: "marks", w: "What the marks mean" }]}>
      {#snippet kind()}{kindLine(p.title).trim()}{/snippet}
      {#snippet section(s)}{#if s.id === "groups"}<ul class="small">{#each p.groups as g (g)}<li>{g}</li>{/each}</ul><p class="muted small mt">Select a row to change it; every Save says when it takes effect.</p>{:else}<dl class="kv small legend" id="marks-legend">{#each SET_LEGEND as [st, means] (st[2])}<dt><Glyph name={st[0]} colour={st[1]} word={st[2]} /></dt><dd>{means}</dd>{/each}</dl>{/if}{/snippet}
    </Pane>
  {/if}
</Detail>
