<script lang="ts">
  // A new topic's first hour, at the top of its page until its first idea card exists:
  // four rows in order, Sources, First read, First brief, First ideas, each with its state and its
  // time, and under them the quiet line when the first read kept little. The words and the times
  // are the server's (GET /api/topics/<id>/start: stored rows and the scheduler's own next runs,
  // never promised by hand); read every 20 s while something is still to come.
  import Group from "../../ui/Group.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Row from "../../ui/Row.svelte";
  import { when } from "../../lib/format";
  import { read } from "../../lib/reads.svelte";
  import { nextAt } from "../ideas/ideas";
  import { briefHref } from "../../features/news/news";
  import { href } from "../../lib/router";
  import { startApi, type TopicStart, type TopicStartRow } from "./topics";

  let { tid, at = 0 }: { tid: number | string; at?: number } = $props();
  const s = $derived.by(() => {
    void at;
    return read<TopicStart>(startApi(tid), 20000).data || null;
  });
  const GLYPH: Record<TopicStartRow["state"], [string, string, string]> = {
    done: ["check", "green", "Done"], running: ["running", "blue", "Now"], waiting: ["waiting", "grey", "Next"],
    quiet: ["dot", "grey", "Quiet"], off: ["closed", "grey", "Off"], failed: ["failed", "red", "Failed"],
  };
  /** a row's time: when it happened, or when it comes ("tonight at 22:00") */
  const time = (r: TopicStartRow): string => !r.at ? "" : r.state === "done" || r.state === "quiet" || r.state === "running" ? when(r.at) : nextAt(r.at);
  const link = (r: TopicStartRow): string | null => r.key === "brief" && r.brief_id ? briefHref(r.brief_id) : r.key === "sources" && r.state !== "done" ? href(`topics/${tid}/sources`) : null;
</script>

{#if s && !s.done}
  <Group id="topic-start" title="The first hour" count={`${s.rows.filter((r) => r.state === "done" || r.state === "quiet").length} of 4`} kind="start">
    {#each s.rows as r (r.key)}
      {@const g = GLYPH[r.state] || GLYPH.waiting}
      <Row title={r.title} href={link(r)} meta={r.words} age={time(r)} sel={"start:" + r.key}>
        {#snippet st()}<Glyph name={g[0]} colour={g[1]} word={g[2]} />{/snippet}
      </Row>
    {/each}
    {#snippet foot()}{#if s.quiet}<p class="more" id="topic-quiet">{s.quiet}</p>{/if}{/snippet}
  </Group>
{/if}
<!-- its rows' layout (the time whole, the words under the title on a phone) is .grp.start's, in
     base.css: the home's first hour draws the same rows -->
