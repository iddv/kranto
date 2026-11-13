<script lang="ts">
  // Filter ▾'s popover: one select per filter, labelled; a change applies it (the route changes).
  import type { Select } from "./FilterBar.svelte";

  let { filters, q, pick }: { filters: Select[]; q: Record<string, string>; pick: (key: string, v: string) => void } = $props();
</script>

{#each filters as [key, name, opts] (key)}<label for={"fpop-" + key}>{name}</label><select id={"fpop-" + key} onchange={(e) => pick(key, e.currentTarget.value)}>{#each opts as [v, w] (v)}<option value={v} selected={(q[key] || "") === v}>{w || "all"}</option>{/each}</select>{/each}
