<script lang="ts">
  // A topic's Ideas: the idea cards from it, newest first, in Ideas' groups. The cards and their
  // groups are one read (pages/ideas/cards.ts's topicWork); a row is Ideas' card row (CardLine:
  // the grade).
  import { topicWork } from "../ideas/cards";
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import Loading from "../../ui/Loading.svelte";
  import CardLine from "../ideas/CardLine.svelte";
  import { plural } from "../../lib/format";
  import type { CardX } from "../ideas/ideas";
  import type { TopicPage } from "./topics";

  let { t, at = 0 }: { t: TopicPage; at?: number } = $props();
  const work = $derived.by(() => {
    void at; // the cards are read again on each draw
    return topicWork(t);
  });
  const ideas = $derived(work?.ideas ?? null);
  const order = $derived(ideas ? ideas.slice().sort((a, b) => b.number - a.number) : []);
  const groups = $derived(work ? work.groups.map(([k, w]) => ({ k, w, xs: order.filter((x) => work.group(x) === k) })).filter((g) => g.xs.length) : []);
</script>

<List title="Ideas" label={t.name + " · Ideas"} crumb={t.name}>
  {#snippet tools()}<span class="tbn"><span>{ideas ? plural(ideas.length, "idea") : ""}</span></span>{/snippet}
  {#if ideas == null}
    <Loading />
  {:else}
    {#if order.length}
      {#each groups as g (g.k)}
        <Group id={"ti-" + g.k} title={g.w} count={String(g.xs.length)} kind="ideas">{#each g.xs as x (x.number)}<CardLine x={x as unknown as CardX} {t} />{/each}</Group>
      {/each}
    {:else}
      <p class="empty">No ideas from this topic yet.</p>
    {/if}
  {/if}
</List>
