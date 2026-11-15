<script lang="ts">
  // A field's label with its hint as a ? beside it (the old page's flabel()): the hint is
  // words, {text, docs} with a link into the docs, or a tip of the page's tips table (tipId).
  import Tip from "./Tip.svelte";

  let { forId, text, hint = null, tipId = null }: {
    forId: string; text: string; hint?: string | { text: string; docs?: string } | null; tipId?: string | null;
  } = $props();
</script>

<div class="lbl"><label for={forId}>{text}</label>{#if tipId}<Tip id={tipId} about={text} />{:else if hint}<Tip id={typeof hint === "string" ? { text: hint } : hint} about={text} />{/if}</div>
