<script lang="ts">
  // A section of a Today row's pane (the old page's paneSec): s-<id> is what [ and ] step to.
  import type { Snippet } from "svelte";

  let { id, title, children }: { id: string; title: string; children?: Snippet } = $props();
</script>

<section class="sec" id={"s-" + id}><h3>{title}</h3>{@render children?.()}</section>
