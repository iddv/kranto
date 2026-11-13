<script lang="ts">
  // Watch › Topics, the digest (#/watch with the doors on, where Today's digest
  // went): a row a topic, the newest-new first and the paused ones last, each saying what is new
  // since your visit in words ("47 kept since your visit, 2 themes rising", or "quiet since your
  // visit"); the row opens the topic's page, j and k its sheet. The library as a whole and the
  // broad lane under them. The head: the facts, Add topic its one primary, Read
  // sources now… under ⋯ (it spends: the house confirm). A row's other verbs are under its ⋯ on
  // hover: Edit (the topic's sheet,), Pause or Resume, Archive; archived topics
  // are under Archived, each with Restore. Without the server, it says topics need it.
  import Glyph from "../../ui/Glyph.svelte";
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import Loading from "../../ui/Loading.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import Row from "../../ui/Row.svelte";
  import Icon from "../../shell/Icon.svelte";
  import { nextRead, plural } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { ui } from "../../lib/shell.svelte";
  import { readSourcesNow } from "./readnow";
  import { TODAY_API, TOPICS_API, topicSt, type Today, type Topic, type Topics } from "../topics/topics";
  import { archiveTopic, editTopic, pauseTopic, restoreTopic } from "../topics/topicedit";
  import RowMore from "../../ui/RowMore.svelte";

  let { view }: { view: View } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const c = $derived.by(() => {
    void view.tick; // each draw may find the reads stale
    return host ? read<Topics>(TOPICS_API, 20000) : null;
  });
  const d = $derived(c?.data || null);
  const td = $derived.by(() => {
    void view.tick;
    return host ? read<Today>(TODAY_API, 60000).data || null : null;
  });
  const newOf = (t: Topic): number => td?.topics.find((x) => x.id === t.id)?.new_kept || 0;
  const rows = $derived(d ? d.topics.slice().sort((a, b) => Number(a.status === "paused") - Number(b.status === "paused") || newOf(b) - newOf(a)) : []);
  const next = $derived(ui.facts?.header.host?.next || null);
  const n = (x: number): string => x.toLocaleString("en-GB");
  const facts = $derived(d ? [plural(d.topics.length, "topic"), plural(d.all.sources, "source"), `${n(d.all.observations)} observations`, next ? "next read " + nextRead(next) : null].filter(Boolean).join(" · ") : "");

  /** the digest's words for a topic: what is new since your visit, or that it was quiet */
  function digest(t: Topic): string {
    if (t.status === "paused") return "paused: its sources are not read";
    const k = newOf(t);
    const rising = t.rising ? `${t.rising === 1 ? "one theme" : plural(t.rising, "theme")} rising` : null;
    return [k ? `${n(k)} kept since your visit` : "quiet since your visit", rising].filter(Boolean).join(", ");
  }
</script>

{#if !host}
  <div data-title="Topics"><NeedHost what="Topics" /></div>
{:else}
  <List title="Topics" crumb={facts} head={{ primary: { label: "Add topic", id: "add-topic", href: "#/topics/new", title: "A name and one sentence; the scout proposes sources" },
    more: [{ label: "Read sources now", id: "read-now", title: "Read every source now (it spends: model calls)", run: (b) => readSourcesNow(b) }] }}>
    {#if !d}
      <Loading error={c?.error} />
    {:else}
      {#if d.progress}<div class="flash blue" role="status"><Icon name="dot" /><div>{d.progress}</div></div>{/if}
      <Group id="tp" title="Your topics" count={String(d.topics.length)} kind="topics">
        {#each rows as t (t.id)}
          {@const m = topicSt(t.status)}
          {@const k = newOf(t)}
          <Row sel={"t" + t.id} title={t.name} href={href("topics/" + t.id)} isNew={!!k}
            meta={[digest(t), plural(t.sources, "source") + (t.proposed ? `, ${t.proposed} proposed` : ""), t.description].filter(Boolean).join(" · ")}>
            {#snippet st()}<Glyph name={m[0]} colour={m[1]} word={m[2]} />{/snippet}
            {#snippet num()}{k ? n(k) : ""}{/snippet}
            {#snippet end()}<RowMore label={`More for ${t.name}`} items={[{ label: "Edit", id: "topic-edit", title: `Edit ${t.name}: its name, description, sources and settings`, run: () => editTopic(t.id) },
              { label: t.status === "paused" ? "Resume topic" : "Pause topic", id: "pause-topic", run: (b) => pauseTopic(b, t) },
              { label: "Archive", id: "archive-topic", title: "Off your lists and not read; its evidence and ideas stay (Undo brings it back)", run: (b) => void archiveTopic(b, t) }]} />{/snippet}
          </Row>
        {/each}
        {#snippet foot()}{#if !d.topics.length}<p class="more">No topics yet. <a href="#/topics/new">Add topic</a>.</p>{/if}{/snippet}
      </Group>
      {#if d.archived?.length}
        <Group id="tp-archived" title="Archived" about={{ text: "Not read, and off your lists. Their evidence, themes and ideas stay readable." }} count={String(d.archived.length)} kind="topics" fold="watch-topics:archived">
          {#each d.archived as t (t.id)}
            <Row sel={"t" + t.id} title={t.name} href={href("topics/" + t.id)} meta={[plural(t.observations, "observation"), t.description].filter(Boolean).join(" · ")}>
              {#snippet st()}<Glyph name="closed" colour="grey" word="Archived" />{/snippet}
              {#snippet end()}<button type="button" class="btn sm" data-act="topic-restore" onclick={(e) => { e.stopPropagation(); void restoreTopic(e.currentTarget, t); }}>Restore</button>{/snippet}
            </Row>
          {/each}
        </Group>
      {/if}
      <Group id="lib" title="Everything kept" count={null} kind="topics">
        <Row title="Evidence, all topics" href="#/watch/evidence"
          meta={[`${n(d.all.observations)} observations`, plural(d.all.sources, "source"), plural(d.all.themes, "theme"), d.all.map ? "mapped " + d.all.map.slice(0, 10) : "no map yet"].join(" · ")}>
          {#snippet st()}<Glyph name="dot" colour="grey" word="Library" />{/snippet}
        </Row>
      </Group>
      {#if d.broad.length}
        <!-- the broad lane, in the owner's words: No topic -->
        <Group id="broad" title="No topic" says="watched for no topic: every item is judged" count={String(d.broad.length)} kind="topics">
          {#each d.broad as s (s.id)}
            <Row sel={"s" + s.id} title={s.label} href={"#/settings/sources/" + s.id} meta={[s.wildcard ? "wildcard" : "no topic", `${s.items_per_day} items a day`, `${s.kept_per_day} kept a day`].join(" · ")}>
              {#snippet st()}<Glyph name="open" colour="grey" word={s.wildcard ? "Wildcard" : "No topic"} />{/snippet}
            </Row>
          {/each}
        </Group>
      {/if}
    {/if}
  </List>
{/if}
