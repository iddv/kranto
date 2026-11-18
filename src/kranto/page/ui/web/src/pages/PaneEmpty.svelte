<script lang="ts">
  // The detail pane when no page draws it: nothing selected; or a Today-style row (sel=) that this
  // list's page has no pane for, with the way back to the list.
  import type { View } from "../lib/pages.svelte";
  import { host } from "../lib/app/data";

  let { view }: { view: View } = $props();
  const text = $derived(!view.w.object ? "Nothing selected." : host() ? "Nothing to show." : "This comes from the server, which is not answering.");
</script>

{#if view.w.object}<div class="pane"><div class="dback"><a class="btn sm" href={view.back}>‹ Back to the list</a></div><div class="pane-empty"><p class="empty">{text}</p></div></div>{:else}<div class="pane"><div class="pane-empty"><p class="empty">{text}</p></div></div>{/if}
