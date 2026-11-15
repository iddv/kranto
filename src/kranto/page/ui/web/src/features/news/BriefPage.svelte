<script lang="ts">
  // A brief's own day (#/news/b/:id;): drawn in Today's layout for that day (one
  // line a story, one open, Write a post and Idea from this), with "About this brief" (the period,
  // the search, the model, where its cost is counted, what the checks did) folded under Details.
  import { dt, longTime, plural, rel } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import NewsToday from "./NewsToday.svelte";
  import { SPEND_LINE, searchLine, shortDay, type Brief } from "./news";

  let { view }: { view: View } = $props();
  const id = $derived(view.w.r.path[2] || "");
</script>

{#snippet about(b: Brief)}
  <details class="small brief-details" id="brief-about"><summary>Details</summary>
    <dl class="kv small"><dt>Covers</dt><dd>{`${shortDay(b.period_start)} to ${shortDay(b.period_end)}`}</dd><dt>Written</dt><dd><time title={longTime(b.created_at)}>{rel(dt(b.created_at))}</time>{b.trigger === "now" ? " (Brief now)" : ""}</dd><dt>Search</dt><dd>{searchLine(b)}</dd><dt>Model</dt><dd>{b.model || "none"}</dd><dt>Cost</dt><dd>{SPEND_LINE}</dd>
      <dt>Checks</dt><dd>{`${plural(Number(b.checks.dropped_uncited || 0), "story", "stories")} dropped for citing nothing, ${plural(Number(b.checks.repeats || 0), "repeat")} of the last brief left out, ${plural(Number(b.checks.cut || 0), "story", "stories")} cut to length`}</dd></dl>
    <p class="muted">Every story rests on the lines it cites: something kept from your sources, or a dated search result. Nothing comes from the model's memory.</p>
  </details>
{/snippet}

<NewsToday {view} bid={id} details={about} />
