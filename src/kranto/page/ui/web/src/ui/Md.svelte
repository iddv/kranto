<script lang="ts">
  // Markdown as text (ui/md.ts): every word a text node, never HTML. links: a widget's note may
  // link to a Kranto route or an https:// page its cub may fetch (the server narrowed them).
  import { blocks, type Run } from "./md";

  let { text, links = false }: { text: string; links?: boolean } = $props();
  const bs = $derived(blocks(text, links));
</script>

{#snippet runs(rs: Run[])}{#each rs as r, i (i)}{#if r.t === "code"}<code>{r.s}</code>{:else if r.t === "strong"}<strong>{r.s}</strong>{:else if r.t === "em"}<em>{r.s}</em>{:else if r.t === "link"}{#if r.href.startsWith("#/")}<a href={r.href}>{r.s}</a>{:else}<a href={r.href} target="_blank" rel="noopener noreferrer">{r.s}</a>{/if}{:else}{r.s}{/if}{/each}{/snippet}

<div class="md">{#each bs as b, i (i)}{#if b.k === "pre"}<pre><code>{b.s}</code></pre>{:else if b.k === "p"}<p>{@render runs(b.runs)}</p>{:else if b.k === "h"}<p class="md-h"><strong>{@render runs(b.runs)}</strong></p>{:else if b.k === "ol"}<ol>{#each b.items as it, j (j)}<li>{@render runs(it)}</li>{/each}</ol>{:else}<ul>{#each b.items as it, j (j)}<li>{@render runs(it)}</li>{/each}</ul>{/if}{/each}</div>
