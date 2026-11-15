<script lang="ts">
  // News › Earlier (#/news/earlier with the doors on): one row a day: the day,
  // the lead story's headline, "full story" when the day has one, how many stories. Ten days, then
  // "Show all N days". A row opens that day (#/news/b/<id>, in Today's layout). With more topics,
  // one group a topic. An article is reached from its day and its story, so there is no separate
  // list of them. ?topic= narrows it to one topic.
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import Loading from "../../ui/Loading.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import Row from "../../ui/Row.svelte";
  import Empty from "../../ui/Empty.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { ui } from "../../lib/shell.svelte";
  import { featurePath } from "../index";
  import { ROWS, articlesPath, briefHref, dayWords, type Brief, type ItemArticle, type TopicRows } from "./news";

  const SHOWN = 10;
  let { view }: { view: View } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const only = $derived(view.w.r.q.topic || "");
  const c = $derived.by(() => {
    void view.tick;
    return host ? read<{ briefs: Brief[] }>(featurePath("news", "briefs.list", only ? { limit: 50, topic_id: only } : { limit: 50 }), 30000) : null;
  });
  const rows = $derived.by(() => {
    void view.tick;
    return host ? read<TopicRows>(ROWS, 60000) : null;
  });
  const arts = $derived.by(() => {
    void view.tick;
    return host ? read<{ articles: (ItemArticle & { brief_id?: number })[] }>(articlesPath(only), 30000) : null;
  });
  const withStory = $derived(new Set((arts?.data?.articles || []).map((a) => a.brief_id)));
  const nameOf = (id: number): string => (rows?.data?.topics || []).find((t) => t.id === id)?.name || `topic ${id}`;
  const groups = $derived.by(() => {
    const by = new Map<number, Brief[]>();
    for (const b of c?.data?.briefs || []) by.set(b.topic_id, [...(by.get(b.topic_id) || []), b]);
    return [...by.entries()].map(([topic, briefs]) => ({ topic, briefs }));
  });
  let all = $state<Record<number, boolean>>({});
  const lead = (b: Brief): string => b.status === "ok" ? (b.items.find((i) => !i.background) || b.items[0])?.headline || "" : b.status === "quiet" ? "A quiet day" : "No brief: it could not be written";
  const count = (b: Brief): string => {
    const n = b.items.filter((i) => !i.background).length;
    return b.status === "ok" ? `${n} ${n === 1 ? "story" : "stories"}` : "";
  };
</script>

{#if !host}
  <div data-title="Earlier"><NeedHost what="News" verb="needs" /></div>
{:else}
  <List title="Earlier" label="Earlier days" sub="One row a day; each opens that day.">
    {#if !c?.data}
      <Loading error={c?.error} />
    {:else if !groups.length}
      <Empty text="No brief yet. A new topic's first brief is written right after its first read." />
    {:else}
      {#each groups as g (g.topic)}
        {@const many = g.briefs.length > SHOWN && !all[g.topic]}
        <Group id={"ne" + g.topic} title={groups.length > 1 || !only ? nameOf(g.topic) : "Days"} count={String(g.briefs.length)} kind="days">
          {#each many ? g.briefs.slice(0, SHOWN) : g.briefs as b (b.id)}
            <Row title={`${dayWords(b.created_at)} · ${lead(b)}`} href={briefHref(b.id)} meta={withStory.has(b.id) ? "full story" : null}>
              {#snippet num()}{count(b)}{/snippet}
            </Row>
          {/each}
          {#if many}<li class="more-days"><button type="button" class="linkish small" onclick={() => (all = { ...all, [g.topic]: true })}>{`Show all ${g.briefs.length} days`}</button></li>{/if}
        </Group>
      {/each}
    {/if}
  </List>
{/if}
