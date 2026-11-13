<script lang="ts">
  // A row's other verbs (the row diet): ⋯ in its end cell, the one menu (arrow
  // keys, enter, esc). Shown on hover, on focus and on the chosen row where there is a pointer
  // (base.css), always on a touch screen; the row's sheet has the same verbs.
  import type { MenuItem } from "../lib/app";
  import { app } from "../lib/shell.svelte";

  let { items, label = "More" }: { items: MenuItem[]; label?: string } = $props();
</script>

<button type="button" class="btn sm more row-more" aria-haspopup="menu" aria-label={label} title={label} onclick={(e) => { e.stopPropagation(); app()?.menu(e.currentTarget, items); }}>⋯</button>
