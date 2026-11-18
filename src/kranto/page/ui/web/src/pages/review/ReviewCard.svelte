<script lang="ts">
  // The queue's current item, in the pane: the kind line, the title (enter
  // opens the item's own page), its line and facts, the grade bar (a grade moves on by itself),
  // Skip. The slot goes into the grade's context only.
  import Glyph from "../../ui/Glyph.svelte";
  import Grade from "../../ui/Grade.svelte";
  import { KINDWORD, type QueueItem } from "./review";
  import { hrefOf, Q, reviewAdvance, reviewDo, reviewGiven, titleOf } from "./review.svelte";

  let { x, i }: { x: QueueItem; i: number } = $props();
  const n = $derived(Q.items?.length || 0);
  const kw = $derived(KINDWORD[x.target] || x.target);
  const what = $derived(`${kw} #${x.id}`);
  const facts = $derived(x.facts || []);
  const link = $derived(hrefOf(x));
  const line = $derived(x.line || "");
</script>

{#snippet kind()}<p class="dk mono q-what"><Glyph name="dot" colour="blue" word={kw} />{` ${kw} · ${i + 1} of ${n}`}{x.topic ? " · " + x.topic : ""}</p>{/snippet}

<section class="qcard" aria-label={"Item " + (i + 1)}>{@render kind()}<h2 class="dt">{#if link}<a href={link} title="Open its own page (enter)">{titleOf(x)}</a>{:else}{titleOf(x)}{/if}</h2>{#if line}<p class="q-line lede">{line}</p>{/if}{#if facts.length}<p class="muted small mono">{facts.join(" · ")}</p>{/if}<div class="gh mt"><span class="muted small">Your grade</span><Grade target={x.target} id={x.id} {what} origin="review" context={{ slot: x.slot, position: i + 1 }} done={(g) => { reviewGiven(i, g ? g.value : null); reviewAdvance(); }} /><button type="button" class="btn sm" onclick={() => reviewDo({ do: "skip" })}>{"Skip, ask next week "}<kbd>0</kbd></button>{#if link}<a class="btn sm quiet" href={link}>{`Open the ${kw}'s page `}<kbd>enter</kbd></a>{/if}</div></section>
