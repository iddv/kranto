<script lang="ts">
  // The lists a Settings page is made of, each drawing its groups only (List's
  // EMBED): a page puts today's groups under one title, in the order you set kranto up.
  import { setContext, type Component } from "svelte";
  import type { View } from "../lib/pages.svelte";
  import { EMBED } from "./List.svelte";

  let { view, parts }: { view: View; parts: [Component<{ view: View; part?: string }>, string?][] } = $props();
  setContext(EMBED, true);
</script>

{#each parts as [Comp, part], i (i)}<Comp {view} {part} />{/each}
