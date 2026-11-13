<script lang="ts">
  // Review (WORKSPACE.md 2.10): the list is the queue, the progress bar its toolbar, one row an
  // item with the grade given in its end cell; the current item is the selected row (data-cur:
  // the old module's markSel) and the pane. Keys only (QUEUE_KEYS, set as the page's keys on every
  // draw), the pointer works too: a grade posts and selects the next ungraded row. A row grades
  // too (a phone has no keys and shows the list): the cluster, or ← → on a pair, until a grade is
  // given; then the grade's word.
  import { untrack } from "svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Grade from "../../ui/Grade.svelte";
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import Row from "../../ui/Row.svelte";
  import { plural } from "../../lib/format";
  import { QUEUE_KEYS } from "../../lib/keys";
  import type { View } from "../../lib/pages.svelte";
  import { app } from "../../lib/shell.svelte";
  import { KINDWORD, reviewMinutes, type QueueItem } from "./review";
  import { pathNow, Q, reviewAdvance, reviewDo, reviewGiven, reviewKey, reviewLoad, reviewPick, titleOf, whatOf } from "./review.svelte";
  import { ui } from "../../lib/shell.svelte";
  import ReviewPane from "./ReviewPane.svelte";

  let { view }: { view: View } = $props();
  const host = $derived.by(() => {
    void view.tick; // the server's status, as the old module last read it
    return !!app()?.host();
  });
  // the queue, read once per visit
  $effect(() => {
    void view.tick;
    if (!host) return;
    const p = pathNow();
    untrack(() => reviewLoad(p));
  });
  // the queue's keys, the page's own on every draw (they win over j/k, enter and the Grade keys)
  $effect(() => {
    void view.tick;
    const L = app();
    if (!L || !host || Q.error || !Q.items) return;
    for (const m of QUEUE_KEYS) L.pageKey(m.keys, () => reviewKey(m.keys));
  });
  const n = $derived(Q.items?.length || 0);
  const done = $derived(Q.at >= n);
  const left = $derived(n - Object.keys(Q.given).length);
</script>

{#snippet progress()}<div class="progress"><span class="mono">{done ? `${n} of ${n}` : `${Q.at + 1} of ${n}`}</span><div class="meter" role="img" aria-label={`${n - left} of ${n} done`}><span style={`width:${Math.round((n - left) / n * 100)}%`}></span></div><span>{done || !left ? "done" : `about ${plural(reviewMinutes(left), "minute")} left`}</span></div>{/snippet}

{#if !host}
  <List title="Review" about="grading" crumb="this week's queue"><NeedHost what="The review queue" verb="needs" /></List>
{:else if Q.error}
  <List title="Review" about="grading" crumb="this week's queue"><p class="empty">{"Could not read the queue: " + Q.error}</p></List>
{:else if !Q.items}
  <List title="Review" about="grading" crumb="this week's queue"><p class="empty">Loading…</p></List>
{:else if !n}
  <List title="Review" about="grading" crumb="this week's queue"><div class="mark-empty"><img src="static/brand/icon-192.png" alt="" width="96" height="96" /><p>Nothing waits for a grade this week. The queue fills with the cards Kranto writes this week; it is rebuilt each week.</p><a class="btn" href="#/">Go home</a></div></List>
{:else}
  <List title="Review" about="grading" crumb="this week's queue" tools={progress}>
    {#if ui.facts?.door}<div class="inpane review-card"><ReviewPane {view} /></div>{/if}
    <Group id="queue" title="The queue" count={String(n)} kind="queue">
      {#snippet right()}<span class="muted">{Q.week || ""}</span>{/snippet}
      {#each Q.items as x, i (i)}
        {@const kw = KINDWORD[x.target] || x.target}
        <Row title={titleOf(x)} cur={i === Q.at} on={() => reviewPick(i)} asideText>
          {#snippet st()}{#if Q.given[i]}<Glyph name="check" colour="green" word="Graded" />{:else}<Glyph name="open" colour="grey" word="Not graded yet" />{/if}{/snippet}
          {#snippet num()}<span class="kindtag">{kw}</span>{/snippet}
          {#snippet aside()}{x.topic || ""}{/snippet}
          {#snippet grade()}{#if Q.given[i]}<span class="given">{Q.given[i]}</span>{:else}<Grade target={x.target} id={x.id} what={whatOf(x)} origin="review" context={{ slot: x.slot, position: i + 1 }} done={(g) => { reviewGiven(i, g ? g.value : null); Q.at = i; reviewAdvance(); }} />{/if}{/snippet}
        </Row>
      {/each}
    </Group>
  </List>
{/if}
