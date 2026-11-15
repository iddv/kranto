<script lang="ts">
  // The queue's pane: the item just graded with its chips (a–f), the current item (ReviewCard) and
  // its chips once graded, so far; when every item is done, the tally and the ways on. A new item
  // starts at the pane's top.
  import { untrack } from "svelte";
  import Detail from "../../ui/Detail.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import { cut, plural } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { app } from "../../lib/shell.svelte";
  import { gradeOf, GWORD } from "../../ui/grades.svelte";
  import Chips from "./Chips.svelte";
  import ReviewCard from "./ReviewCard.svelte";
  import { KINDWORD } from "./review";
  import { Q, reviewAgain, reviewChipTarget, titleOf } from "./review.svelte";

  let { view }: { view: View } = $props();
  const host = $derived.by(() => {
    void view.tick; // the server's status, as the old module last read it
    return !!app()?.host();
  });
  const items = $derived(Q.items || []);
  const n = $derived(items.length);
  const done = $derived(Q.at >= n);
  const tally = $derived(`So far: ${plural(Q.grades, "grade")}, ${plural(Q.skips, "skip")}, ${plural(Q.chips, "chip")}.`);
  const t = $derived(reviewChipTarget());
  const last = $derived(Q.last != null ? items[Q.last] || null : null);
  const justGraded = $derived(last && Q.last !== Q.at ? gradeOf(last.target, last.id, null) : null);
  // the pane's top for each new item (the old pane was drawn anew for each)
  $effect(() => {
    void Q.at;
    untrack(() => {
      const box = document.getElementById("dscroll");
      if (box) box.scrollTop = 0;
    });
  });
</script>

<Detail>
  {#if !host || !n}
    <div class="pane-empty"><p class="empty">{Q.items && !n ? "The queue is empty this week." : "Reading the queue…"}</p></div>
  {:else if done}
    <div class="pane-in" data-title="Review"><section class="qcard"><p class="dk mono"><Glyph name="check" colour="green" word="Done" />{" review · done"}</p><h2 class="dt">Done.</h2><p class="lede">{tally}</p><div class="acts"><a class="btn" href="#/home">Back home</a><button type="button" class="btn" onclick={reviewAgain}>Read the queue again</button></div></section></div>
  {:else}
    {@const x = items[Q.at]}
    <div class="pane-in" data-title="Review">
      {#if last && justGraded}<div class="qlast"><span class="muted small">{`Just graded ${KINDWORD[last.target]} "${cut(titleOf(last), 60)}" ${GWORD[justGraded.value]}.`}</span>{#if t === Q.last}<Chips target={last.target} id={last.id} o={{ origin: "review", context: { slot: last.slot } }} />{/if}</div>{/if}
      {#if x}<ReviewCard {x} i={Q.at} />{#if t === Q.at}<Chips target={x.target} id={x.id} o={{ origin: "review", context: { slot: x.slot } }} />{/if}{/if}
      <section class="sec" id="s-so-far"><h3>So far this week</h3><p class="small">{tally}</p></section>
    </div>
  {/if}
</Detail>
