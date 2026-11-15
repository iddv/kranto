<script lang="ts">
  // ⋯'s items in the one popover (ui/popover.ts's menu()): each group of verbs between rules; a
  // verb that is not on now is greyed, with its why (its title, and in words for a reader); a
  // verb's note is a second line under it (what it reaches: SRC D3).
  import type { MenuItem } from "../lib/app/types";

  let { items, press }: { items: MenuItem[]; press: (x: MenuItem) => void } = $props();
  const groups = $derived([...new Set(items.map((x) => x.group || ""))]);
</script>

{#each groups as g, n (g)}{#if n}<hr />{/if}{#each items.filter((y) => (y.group || "") === g) as x, i (i)}<button type="button" role="menuitem" data-menu={x.id || null} data-verb={x.verb || null} aria-disabled={x.why ? "true" : null} title={x.why || x.title || null} onclick={() => press(x)}><span class="grow">{x.label}{#if x.note}<small class="m-note">{x.note}</small>{/if}</span>{#if x.key}<kbd>{x.key}</kbd>{/if}{#if x.why}<span class="sr-only">{" (" + x.why + ")"}</span>{/if}</button>{/each}{/each}

<style>
  .m-note { display: block; color: var(--muted); font-size: 11.5px; font-weight: 400; line-height: 1.3; }
</style>
