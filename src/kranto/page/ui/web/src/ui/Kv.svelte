<script lang="ts" module>
  import type { Snippet } from "svelte";
  /** one line: its name, its value (words, or drawn), an optional class for the value */
  export type KvRow = [string, string | number | Snippet | null | undefined, string?];
</script>

<script lang="ts">
  // Names and values in two columns (the old page's kvList): an empty value is "–".
  let { rows }: { rows: (KvRow | null | false)[] } = $props();
  const shown = $derived(rows.filter((r): r is KvRow => !!r));
</script>

<dl class="kv small">{#each shown as [k, v, cls], i (i)}<dt>{k}</dt><dd class={cls || null}>{#if v == null || v === ""}–{:else if typeof v === "function"}{@render v()}{:else}{v}{/if}</dd>{/each}</dl>
