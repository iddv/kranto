<script lang="ts">
  // A 16 px icon from lib/icons.ts, as the old page's icon() draws it.
  import { ICON } from "../lib/icons";

  let { name, cls = "" }: { name: string; cls?: string } = $props();
  const shapes = $derived(ICON[name] || ICON.dot || []);
</script>

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" class={"i" + (cls ? " " + cls : "")} aria-hidden="true">{#each shapes as [tag, attrs], i (i)}<svelte:element this={tag} {...attrs} />{/each}</svg>
