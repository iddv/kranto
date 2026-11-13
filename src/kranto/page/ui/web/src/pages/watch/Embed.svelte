<script lang="ts">
  // A list drawn inside another page's (ui/List's EMBED): its groups only, under the page's title.
  import { setContext, type Snippet } from "svelte";
  import { EMBED } from "../../ui/List.svelte";

  let { children }: { children: Snippet } = $props();
  setContext(EMBED, true);
</script>

{@render children()}
