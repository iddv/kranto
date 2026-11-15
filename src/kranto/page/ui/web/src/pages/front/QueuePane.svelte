<script lang="ts">
  // Needs you's Review row's pane (sel=r): what is in this week's queue, by kind, and Start (#/review,
  // keys only). The queue is the one Review reads (pages/review).
  import Glyph from "../../ui/Glyph.svelte";
  import { plural } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { gradable, KINDWORD, REVIEW_API, reviewMinutes, type Queue } from "../review/review";
  import PaneTop from "./PaneTop.svelte";
  import Sec from "./Sec.svelte";

  let { view, host }: { view: View; host: boolean } = $props();
  const items = $derived.by(() => {
    void view.tick;
    return host ? gradable(read<Queue>(REVIEW_API, 60000).data?.items || []) : [];
  });
  const n = $derived(items.length);
  const by = $derived.by(() => {
    const o: Record<string, number> = {};
    for (const x of items) { const k = KINDWORD[x.target] || String(x.target); o[k] = (o[k] || 0) + 1; }
    return Object.entries(o).map(([k, v]) => plural(v, k)).join(" · ");
  });
</script>

{#snippet kind()}<Glyph name="dot" colour="blue" word="Review" />{" review · this week's queue"}{/snippet}
{#snippet acts()}<a class="btn primary" href="#/review">Start</a>{/snippet}

<div class="pane-in" data-title="Review"><PaneTop {kind} title={`${plural(n, "item")} waiting for a grade`} lede={`About ${plural(reviewMinutes(n), "minute")}, keys only: 1 useful, 2 not useful, 3 wrong, 0 skip.`} {acts} /><Sec id="in" title="In the queue"><p>{by || "Nothing this week."}</p></Sec></div>
