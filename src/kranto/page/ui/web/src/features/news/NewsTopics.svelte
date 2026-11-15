<script lang="ts">
  // News › Topics (#/news/topics with the doors on): a row a topic, the one row
  // anatomy: its state, its name, its cadence and hour (or the next brief) in the
  // meta, and News's switch in its end cell (on or off: one press, nothing spent until its hour;
  // HIG's one control a row may hold). The row opens its sheet (sel=t<id>: how often, at what hour,
  // Brief now). The same key as the switch on the topic's page; here several are turned on
  // at once.
  import Glyph from "../../ui/Glyph.svelte";
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import Loading from "../../ui/Loading.svelte";
  import Empty from "../../ui/Empty.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import Row from "../../ui/Row.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { ui } from "../../lib/shell.svelte";
  import { ROWS, TOPIC_SEL, cadenceWords, newsSet, nextWords, type TopicRow, type TopicRows } from "./news";

  let { view }: { view: View } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const rows = $derived.by(() => {
    void view.tick;
    return host ? read<TopicRows>(ROWS, 30000) : null;
  });
  const d = $derived(rows?.data || null);
  const meta = (t: TopicRow): string => (t.news.enabled ? cadenceWords(t.news) + nextWords(t.next_due) + (t.running ? " · writing now" : "") : "News is off for this topic");
</script>

{#if !host}
  <div data-title="News topics"><NeedHost what="News" verb="needs" /></div>
{:else}
  <List title="Topics" label="News topics" sub="News per topic: on or off here; how often and at what hour in its row.">
    {#if !d}
      <Loading error={rows?.error} />
    {:else if !d.enabled}
      <Empty text="News is off: it writes no brief until it is on." link={{ href: "#/settings/news", w: "Settings › News ›" }} />
    {:else}
      {#if d.search_off}<p class="quiet-topics">{d.search_off}</p>{/if}
      <Group id="nt" title="Topics" count={`${d.topics.filter((t) => t.news.enabled).length} on`} kind="topics">
        {#each d.topics as t (t.id)}
          {@const on = t.news.enabled}
          <Row sel={TOPIC_SEL + t.id} title={t.name} href={href("news/topics", { ...view.w.r.q, sel: TOPIC_SEL + t.id })} meta={meta(t)}>
            {#snippet st()}<Glyph name={on ? "check" : "dot"} colour={on ? "green" : "grey"} word={on ? "on" : "off"} />{/snippet}
            {#snippet end()}<button type="button" class="btn sm sw" role="switch" aria-checked={on ? "true" : "false"} aria-label={`News for ${t.name}`} data-act="news-toggle" onclick={(e) => { e.stopPropagation(); newsSet(e.currentTarget, t, !on); }}>{on ? "On" : "Off"}</button>{/snippet}
          </Row>
        {/each}
      </Group>
    {/if}
  </List>
{/if}
