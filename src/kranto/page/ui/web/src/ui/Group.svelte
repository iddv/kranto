<script lang="ts">
  // A group of rows (the old page's lgroup()): its heading with a count and an optional ? (a tip
  // id, or words), a right-hand slot, the rows, and a foot (an empty state, a See all). hidden: a
  // list that filters as you type hides a group with no row left. fold: a key that lets the group
  // fold to its heading (UP #7), remembered per viewer (fold.svelte.ts). says: what the group
  // means, in words beside its heading rather than behind a ? (SRC D2). start: the group starts
  // folded until the viewer opens it (R4: at most seven decisions before scrolling).
  import type { Snippet } from "svelte";
  import Tip from "./Tip.svelte";
  import { isFolded, setFolded } from "./fold.svelte";

  let { id, title, count = null, about = null, says = null, kind = null, hidden = false, fold = null, start = false, right, children, foot }: {
    id: string; title: string; count?: string | null; about?: string | { text: string; docs?: string } | null; says?: string | null; kind?: string | null;
    hidden?: boolean; fold?: string | null; start?: boolean; right?: Snippet; children?: Snippet; foot?: Snippet;
  } = $props();
  const folded = $derived(!!fold && isFolded(fold, start));
</script>

<section class={"grp" + (kind ? " " + kind : "") + (folded ? " folded" : "")} aria-labelledby={id} {hidden}><div class="ghd">{#if fold}<button type="button" class="twisty" aria-expanded={!folded} aria-controls={id + "-rows"} title={folded ? "Show " + title : "Fold " + title} onclick={() => setFolded(fold, !folded)}>{folded ? "▸" : "▾"}</button>{/if}<h2 {id}>{title}</h2>{#if count != null}<span class="n">{count}</span>{/if}{#if about}<Tip id={about} about={title} />{/if}{#if says}<span class="g-says muted small">{says}</span>{/if}<span class="grow"></span>{@render right?.()}</div><ul class="lst" id={fold ? id + "-rows" : null} hidden={folded}>{@render children?.()}</ul>{#if !folded}{@render foot?.()}{/if}</section>
