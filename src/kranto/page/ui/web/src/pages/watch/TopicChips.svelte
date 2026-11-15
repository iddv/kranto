<script lang="ts">
  // Watch › Sources by topic, on All topics' Sources: one row of chips, All ·
  // each of your topics with what it watches (the topic's own number) · No topic; a topic's chip
  // opens its Sources page (#/watch/topic/<id>/sources, WT), No topic is the list's no-topic
  // filter; the chip of where you are is pressed. On the phone the row scrolls sideways.
  import { plural } from "../../lib/format";
  import { read } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { watchPath } from "../../lib/app/watchscope";
  import { ui } from "../../lib/shell.svelte";
  import { TOPICS_API, type Topics } from "../topics/topics";

  let { at = 0, topic = null, broad = false }: { at?: number; topic?: string | null; broad?: boolean } = $props();
  // the server's, when it hosts the page (the list says so when it does not)
  const host = $derived(!!ui.facts?.header.host);
  const mine = $derived.by(() => {
    void at;
    return host ? read<Topics>(TOPICS_API, 30000).data : null;
  });
</script>

{#if mine}
  <nav class="src-chips chips" id="src-chips" aria-label="Sources by topic">
    <a class="chip" href={href("watch/sources")} aria-current={!topic && !broad ? "page" : null} title={`${plural(mine.all.sources, "source")} watched in all`}>All <span class="n">{mine.all.sources}</span></a>
    {#each mine.topics as t (t.id)}<a class="chip" href={"#/" + watchPath(t.id, "sources")} aria-current={String(t.id) === String(topic) ? "page" : null} title={`${t.name}: ${t.sources} watched`}>{t.name} <span class="n">{t.sources}</span></a>{/each}
    <a class="chip" href={href("watch/sources", { status: "broad" })} aria-current={broad ? "page" : null} title="Watched with no topic: every item is judged">No topic <span class="n">{mine.broad.length}</span></a>
  </nav>
{/if}

<style>
  .src-chips { flex-wrap: nowrap; overflow-x: auto; margin: 0 0 8px; padding-bottom: 2px; scrollbar-width: thin; }
  .src-chips .chip { flex: none; text-decoration: none; white-space: nowrap; }
  .src-chips .chip[aria-current="page"] { background: var(--violet-pastel); color: var(--chip-text); border-color: var(--violet); font-weight: 600; }
  .src-chips .n { color: var(--muted); font-variant-numeric: tabular-nums; }
  .src-chips .chip[aria-current="page"] .n { color: var(--chip-text); }
</style>
