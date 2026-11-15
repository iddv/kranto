<script lang="ts">
  // #/ideas' detail pane through the page seam: an idea card (ideas/:id, or sel=i<id> away from
  // home: a Needs you row, a topic's Ideas), or with nothing selected, says so.
  import Detail from "../../ui/Detail.svelte";
  import type { View } from "../../lib/pages.svelte";
  import Idea from "./Idea.svelte";
  import { ideaOf } from "./ideas";

  let { view }: { view: View } = $props();
  const id = $derived(view.w.object === "idea" && view.w.obj ? String(view.w.obj[1]) : null);
  const i = $derived.by(() => {
    void view.tick; // the cards' read, read again on its schedule
    return id ? ideaOf(id) : null;
  });
</script>

<Detail back={view.back}>
  {#if !id}
    <div class="pane-empty"><p class="empty">Nothing selected.</p></div>
  {:else if !i}
    <div class="pane-empty"><p class="empty">No such idea.</p></div>
  {:else}
    {#key i.id}<Idea {view} {i} />{/key}
  {/if}
</Detail>
