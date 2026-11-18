<script lang="ts">
  // A topic's Sources (#/watch/topic/<id>/sources,
  // titled "Robotics › Sources", the topic's own, as Watch shows by default), one line of
  // the topic's own facts (the numbers its page says: one read, /api/topics/<id>), Add source
  // and Edit the topic, then its rows (TopicSourceRows, which the topic page's Sources section
  // draws too): the scout's proposals first with Watch these, then Watched, Wildcards and the
  // rest. Each row opens in the pane (sel=s<id>). The proposals' ticks are the old module's
  // (TICKS: Add topic, Today's proposals and Scout more share them).
  import List from "../../ui/List.svelte";
  import Tip from "../../ui/Tip.svelte";
  import { pct, plural, tokText } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { href } from "../../lib/router";
  import { n2 } from "../library/library";
  import { editTopic } from "./topicedit";
  import TopicSourceRows from "./TopicSourceRows.svelte";
  import RunLine from "../../ui/RunLine.svelte";
  import { readSourcesNow } from "../watch/readnow";
  import type { TopicPage } from "./topics";
  import { ui } from "../../lib/shell.svelte";

  let { view, t }: { view: View; t: TopicPage } = $props();
  const n = (f: (s: TopicPage["source_rows"][number]) => boolean): number => t.source_rows.filter(f).length;
  // the topic's facts in one line: what it watches, reads and keeps, what judging it cost, and what else is here
  const facts = $derived([`${t.sources} watched`,
    t.items_per_day ? `${t.items_per_day} items a day, ${pct(t.kept_per_day / t.items_per_day)} kept` : "nothing fetched in 7 days",
    t.tokens_month ? `${tokText(t.tokens_month)} this month` : null,
    [n((s) => s.group === "wildcard" && s.review === "approved") ? plural(n((s) => s.group === "wildcard" && s.review === "approved"), "wildcard") : null,
      n((s) => s.review === "proposed") ? `${n((s) => s.review === "proposed")} proposed` : null,
      n((s) => s.group === "invalid") ? `${n((s) => s.group === "invalid")} could not be fetched` : null].filter(Boolean).join(", ") || null].filter(Boolean).join(" · "));
</script>

{#snippet tip()}<Tip id={{ text: `Items a day: the last 7 days, before filtering. Kept and yield: the last 30 days. Items are compared with the topic before any model call; only those at similarity ${n2(t.prefilter)} or more are judged.` }} about="the columns" />{/snippet}
{#snippet oldTools()}<span class="tbn twrap"><span id="topic-sources-facts">{facts}</span>{@render tip()}<span class="grow"></span><a class="btn sm primary" id="topic-add-source-list" href={href("settings/sources/new", { topic: t.id })}>{`Add source to ${t.name}`}</a>{#if t.status !== "archived"}<button type="button" class="btn sm" id="topic-sources-edit" onclick={() => editTopic(t.id)}>Edit the topic</button>{/if}<button type="button" class="btn sm" id="sources-read-now" title="Read every source now (it spends: model calls)" onclick={(e) => readSourcesNow(e.currentTarget)}>Read sources now</button></span>{/snippet}
<!-- with the doors on its facts, Add source, the other verbs and the ingest's line
     are the page's head; the toolbar keeps the columns' ? and the bulk bar -->
{#snippet headTools()}<span class="tbn"><span class="muted">What the columns say</span>{@render tip()}</span>{/snippet}
<List title={`${t.name} › Sources`} tools={ui.headOn ? headTools : oldTools} head={ui.headOn ? {
  facts, primary: { label: `Add source to ${t.name}`, id: "topic-add-source-list", href: href("settings/sources/new", { topic: t.id }) },
  more: [...(t.status !== "archived" ? [{ label: "Edit the topic", id: "topic-sources-edit", run: () => editTopic(t.id) }] : []),
    { label: "Read sources now", id: "sources-read-now", title: "Read every source now (it spends: model calls)", run: (b: HTMLElement) => readSourcesNow(b) }],
  line: "kind:ingest", lineId: "sources-run-line" } : null}>
  {#if !ui.headOn}<RunLine subject="kind:ingest" tick={view.tick} id="sources-run-line" />{/if}
  <TopicSourceRows {t} at={view.tick} />
</List>

<style>
  .tbn.twrap { flex-wrap: wrap; row-gap: 4px; }
</style>
