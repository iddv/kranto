<script lang="ts">
  // The detail pane's frame for a moved page (the old page's renderDetail): "‹ Back to the list"
  // when an object is open, then the pane.
  import type { Snippet } from "svelte";

  let { back = null, children }: { back?: string | null; children?: Snippet } = $props();
</script>

<div class="pane">{#if back}<div class="dback"><a class="btn sm" href={back}>‹ Back to the list</a></div>{/if}{@render children?.()}</div>
