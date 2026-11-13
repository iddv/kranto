<script lang="ts">
  // Desk › News, the list: the latest brief of each topic News is on for (the morning view; a
  // brief opens in the pane, sel=f<id>), then every topic with its News switch: off until you
  // turn it on, one press; Brief now writes one at once. Without the server, it says so.
  import Glyph from "../../ui/Glyph.svelte";
  import { doorsNow } from "../shell";
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import Loading from "../../ui/Loading.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import NewsToday from "./NewsToday.svelte";
  import Row from "../../ui/Row.svelte";
  import { ago, dt, plural } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { app, ui } from "../../lib/shell.svelte";
  import { ACT, LATEST, ROWS, SEL, briefSt, cadenceWords, nextWords, type Latest, type TopicRow, type TopicRows } from "./news";

  let { view }: { view: View } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const rows = $derived.by(() => {
    void view.tick; // each draw may find the reads stale
    return host ? read<TopicRows>(ROWS, 30000) : null;
  });
  const latest = $derived.by(() => {
    void view.tick;
    return host ? read<Latest>(LATEST, 30000) : null;
  });
  const d = $derived(rows?.data || null);
  const briefs = $derived((latest?.data?.topics || []).filter((t) => t.brief));

  /** News on or off for one topic: one press, no dialog (nothing is spent until its hour) */
  function toggle(btn: HTMLElement, t: TopicRow): void {
    const L = app();
    if (!L) return;
    const on = !t.news.enabled;
    void L.act(btn, () => L.api(ACT("toggle"), { fields: { topic_id: t.id, on } }), (r) => {
      L.afkDrop();
      const n = (r as { next_due?: string | null }).next_due;
      L.say(on ? `News is on for ${t.name}: ${cadenceWords(t.news)}${n ? ", the first at " + n.slice(0, 16).replace("T", " ") : ""}.` : `News is off for ${t.name}.`);
    });
  }
  /** Brief now: written in the background; the list shows it when it is done */
  function now(btn: HTMLElement, t: TopicRow): void {
    const L = app();
    if (!L) return;
    void L.act(btn, () => L.api(ACT("write_now"), { fields: { topic_id: t.id } }), () => {
      L.afkDrop();
      L.say(`Writing ${t.name}'s brief: it shows here in a minute or so.`);
    });
  }
</script>

{#if !host}
  <div data-title="News"><NeedHost what="News" verb="needs" /></div>
{:else if doorsNow()}
  <!-- with the doors on, News is Today (the briefs as prose), Earlier and Topics -->
  <NewsToday {view} />
{:else}
  <List title="News" about="news" crumb="Desk">
    {#if !d}
      <Loading error={rows?.error} />
    {:else if !d.enabled}
      <p class="empty">News is off in your settings (news.enabled).</p>
    {:else}
      {#if d.search_off}<p class="quiet-topics">{d.search_off}</p>{/if}
      <Group id="nb" title="Latest briefs" count={String(briefs.length)} kind="briefs">
        {#each briefs as t (t.topic.id)}
          {@const b = t.brief!}
          {@const g = briefSt(b.status)}
          <Row sel={SEL + b.id} title={t.topic.name} href={href("news", { sel: SEL + b.id })}
               meta={b.status === "ok" ? (b.items[0]?.headline || "") : b.status === "quiet" ? (b.quiet || "Nothing new.") : (b.error || "failed")}
               asideText age={ago(dt(b.created_at))}>
            {#snippet st()}<Glyph name={g[0]} colour={g[1]} word={g[2]} />{/snippet}
            {#snippet aside()}{plural(b.items.length, "item")}{/snippet}
          </Row>
        {:else}
          <p class="empty">No brief yet. A new topic's first brief is written right after its first read.</p>
        {/each}
      </Group>
      <Group id="nt" title="Topics" count={String(d.topics.filter((t) => t.news.enabled).length) + " on"} kind="topics">
        {#each d.topics as t (t.id)}
          <Row title={t.name} meta={t.news.enabled ? cadenceWords(t.news) + nextWords(t.next_due) : "News is off for this topic"}
               off={!t.news.enabled} asideText age={t.last ? ago(dt(t.last.created_at)) : null}>
            {#snippet st()}<Glyph name={t.news.enabled ? "check" : "dot"} colour={t.news.enabled ? "green" : "grey"} word={t.news.enabled ? "on" : "off"} />{/snippet}
            {#snippet end()}{#if t.news.enabled}<button class="btn sm" data-act="brief-now" disabled={t.running} title={t.running ? "A brief is being written" : "Write this topic's brief now"} onclick={(e) => now(e.currentTarget, t)}>Brief now</button>{/if}<button class={"btn sm" + (t.news.enabled ? "" : " primary")} data-act="news-toggle" onclick={(e) => toggle(e.currentTarget, t)}>{t.news.enabled ? "Turn off" : "Turn on"}</button>{/snippet}
          </Row>
        {/each}
      </Group>
    {/if}
  </List>
{/if}
