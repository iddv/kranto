<script lang="ts">
  // A topic's proposed sources (sel=p<topic>): the scout's proposals ticked as the topic's Sources
  // ticks them (the close matches until you change them; wildcards never), and Watch these. The
  // proposals' group and its ticks are the old module's (proposalBox, TICKS, watchTicked: Add topic,
  // a topic's Sources and Scout more share them), read from the topic's page (/api/topics/<id>).
  import Glyph from "../../ui/Glyph.svelte";
  import Loading from "../../ui/Loading.svelte";
  import Proposals from "../topics/Proposals.svelte";
  import { TICKS, watchTicked } from "../topics/proposals";
  import { plural } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { app } from "../../lib/shell.svelte";
  import { topicApi, type TopicPage } from "../topics/topics";
  import PaneTop from "./PaneTop.svelte";
  import type { TodayTopic } from "./needs";

  let { x, view }: { x: TodayTopic; view: View } = $props();
  const c = $derived.by(() => {
    void view.tick; // each draw may find the read stale
    return read<TopicPage>(topicApi(x.id), 20000);
  });
  const tp = $derived(c.data);
  const proposed = $derived(tp ? tp.source_rows.filter((s) => s.review === "proposed") : []);

  /** the proposals ticked for this topic: the close matches until you change them */
  function ticks(): Set<number> {
    if (!tp) return new Set();
    return (TICKS[tp.id] ||= new Set(tp.source_rows.filter((s) => s.pretick).map((s) => s.id)));
  }
  /** Watch these: what is ticked is watched for the topic (a wildcard with no topic) */
  function watchThese(btn: HTMLElement): void {
    const L = app();
    if (!L || !tp) return;
    const tk = ticks(), rows = proposed, id = tp.id, name = tp.name;
    void L.act(btn, async () => {
      const n = await watchTicked(id, rows, tk);
      L.afkDrop();
      return n;
    }, (n) => {
      delete TICKS[id];
      L.say(`Watching ${plural(n as number, "more source")} for ${name}. Their first fetch is the next ingest run.`);
    });
  }
</script>

{#snippet kind()}<Glyph name="open" colour="amber" word="Proposed" />{" proposed sources · " + x.name}{/snippet}
{#snippet acts()}<a class="btn sm" href={href(`topics/${x.id}/sources`)}>Open the topic's Sources</a>{/snippet}
{#snippet head()}<PaneTop {kind} title={`${plural(x.proposed, "proposed source")} for ${x.name}`} lede="From the scout. The ticked ones are close matches; wildcards are never ticked for you." {acts} />{/snippet}

{#if !tp}
  <div class="pane-in">{@render head()}<Loading error={c.error} /></div>
{:else}
  <div class="pane-in" data-title="Proposed sources">{@render head()}{#if proposed.length}<Proposals title="Proposed" tid={tp.id} rows={proposed} ticked={ticks()}>{#snippet foot()}<button class="btn primary" id="watch-these" onclick={(e) => watchThese(e.currentTarget)}>Watch these</button>{/snippet}</Proposals>{:else}<p class="empty">Nothing is proposed now.</p>{/if}</div>
{/if}
