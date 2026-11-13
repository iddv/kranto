<script lang="ts">
  // Settings › Sources, the pane: a source (#/settings/sources/<id>, or sel=s<id> anywhere: a
  // topic's page, Today, Health) is SourcePane; a kind chosen in the catalog (sel=epreset:<key>)
  // or a proposal to review (sel=ereview:<id>) is CatalogPane. With nothing selected, what is
  // read for which topic and how a source is added; at Add source, Describe what to add (a pasted
  // list, resolved and reviewed as one group: DescribePane), or pick a kind on the left.
  import Detail from "../../ui/Detail.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Kv from "../../ui/Kv.svelte";
  import Loading from "../../ui/Loading.svelte";
  import Pane from "../../ui/Pane.svelte";
  import Tip from "../../ui/Tip.svelte";
  import Icon from "../../shell/Icon.svelte";
  import { plural } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { ui } from "../../lib/shell.svelte";
  import { groupOf, kindLine } from "../../ui/settings";
  import CatalogPane from "./CatalogPane.svelte";
  import DescribePane from "./DescribePane.svelte";
  import SourcePane from "./SourcePane.svelte";
  import { GROUPS, listGroup, SOURCES_API, type Sources } from "./sources.svelte";

  let { view }: { view: View } = $props();
  const id = $derived(groupOf(view.w));
  const host = $derived(!!ui.facts?.header.host);
  const source = $derived(view.w.object === "source" && view.w.obj ? String(view.w.obj[2]) : null);
  const adding = $derived(view.w.r.path[1] === "sources" && view.w.r.path[2] === "new");
  const c = $derived.by(() => {
    void view.tick; // each draw may find the reads stale
    return host && !source && !id && !adding ? read<Sources>(SOURCES_API) : null;
  });
  const d = $derived(c?.data || null);
  const by = (k: string): number => (d ? d.sources.filter((s) => listGroup(s) === k).length : 0);
</script>

{#snippet gone(text: string)}<div class="pane-empty"><p class="empty">{text}</p></div>{/snippet}
{#snippet addBtn()}<a class="btn sm primary" href="#/settings/sources/new">Add source</a>{/snippet}

{#if source}
  <SourcePane {view} id={source} />
{:else if id}
  <CatalogPane {view} {id} />
{:else}
  <Detail back={view.back}>
    {#if adding && !host}
      <Pane title="Add source">
        {#snippet kind()}<Glyph name="open" colour="blue" word="Add source" />{kindLine("sources", "add source")}{/snippet}
        {#snippet lede()}Pick a kind on the left.<Tip id="sources.access" about="how a source is read" />{/snippet}
      </Pane>
    {:else if adding}
      <DescribePane {view} />
    {:else if !host}
      {@render gone("Sources need the server, which is not hosting this page.")}
    {:else if !d}
      <div class="pane-in"><Loading error={c?.error} /></div>
    {:else}
      {@const reddit = d.reddit.watched}
      <Pane title="Where the kranto read" acts={addBtn} sections={[{ id: "topics", w: "Topics", n: d.topics.length }, { id: "counts", w: "By state", about: { text: `Items a day: the last 7 days, before filtering. Kept and yield: the last 30 days. A source is kept ${d.default_retention_days} days by default.` } }]}>
        {#snippet kind()}<Glyph name="dot" colour="blue" word="Sources" />{kindLine("sources")}{/snippet}
        {#snippet top()}{#if reddit}<div class="note c-amber" role="status"><Icon name="warn" /><div><strong>{"Reddit's feeds stop on 13 Nov 2026. "}</strong>{`${plural(reddit, "Reddit source")} you watch will stop then. Click Scout more on their topics: the scout proposes replacements for each.`}</div></div>{/if}{/snippet}
        {#snippet section(s)}
          {#if s.id === "topics"}
            {#if d.topics.length}<ul class="ctx">{#each d.topics as t (t.id)}<li><a href={href(`topics/${t.id}/sources`)}>{t.name}</a><span class="n">{plural(t.sources, "source")}</span></li>{/each}</ul>
            {:else}<p class="small">{"No topics yet; "}<a href="#/topics/new">add one</a>.</p>{/if}
          {:else}
            <Kv rows={GROUPS.map(([k, w]) => (by(k) ? [w, String(by(k)), "mono"] : null))} />
          {/if}
        {/snippet}
      </Pane>
    {/if}
  </Detail>
{/if}
