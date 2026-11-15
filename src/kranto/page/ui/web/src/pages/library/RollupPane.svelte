<script lang="ts">
  // Library › Rollups, the pane: a compacted week (sel=u<id>) from the list it was read in (the
  // rollups' page, or a search's compacted weeks on Observations: no read of its own), its facts
  // and its links; with nothing selected, "Nothing selected.".
  import Detail from "../../ui/Detail.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Loading from "../../ui/Loading.svelte";
  import Pane from "../../ui/Pane.svelte";
  import { cut, dt, longTime, rel } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { ui } from "../../lib/shell.svelte";
  import { mix, n2, obsQuery, rollupIn, rollupSt, rollupsPath, type Observations, type Rollups } from "./library";

  let { view }: { view: View } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const id = $derived(view.w.object === "need" && view.w.id?.startsWith("u") ? view.w.id.slice(1) : null);
  const c = $derived.by(() => {
    void view.tick; // each draw may find the reads stale
    if (!host || !id) return null;
    return view.w.node === "library" || (view.w.node === "watch/evidence" && view.w.r.q.group !== "rollups") ? read<Observations>(obsQuery(view.w.r.q).path, 60000) : read<Rollups>(rollupsPath(view.w.r.q), 60000);
  });
  const x = $derived(c?.data && id ? rollupIn(c.data, id) : null);
  const urls = $derived((x?.urls || []).filter((u) => /^https?:/i.test(u)));
</script>

{#snippet gone(text: string)}<div class="pane-empty"><p class="empty">{text}</p></div>{/snippet}

<Detail back={view.back}>
  {#if !id}
    {@render gone("Nothing selected.")}
  {:else if !host}
    {@render gone("This comes from the server, which is not hosting this page.")}
  {:else if !c?.data}
    <div class="pane-in"><Loading error={c?.error} /></div>
  {:else if !x}
    {@render gone("This rollup is not on the list any more. Search the compacted weeks again.")}
  {:else}
    {@const g = rollupSt(x)}
    {@const week = (x.period_start || "").slice(0, 10)}
    <Pane title={x.label} lede={x.summary} right={"signal " + n2(x.mean_signal)} sections={[{ id: "facts", w: "Facts" }, ...(urls.length ? [{ id: "links", w: "Links", n: urls.length }] : [])]}>
      {#snippet kind()}<Glyph name={g[0]} colour={g[1]} word={g[2]} />{` rollup · week of ${week}`}{/snippet}
      {#snippet section(s)}
        {#if s.id === "facts"}
          <dl class="kv small"><dt>Week of</dt><dd>{week}</dd><dt>Observations</dt><dd>{String(x.size)}</dd><dt>Sources</dt><dd>{mix(x.source_mix, 8)}</dd>{#if (x.keywords || []).length}<dt>Keywords</dt><dd>{x.keywords.join(", ")}</dd>{/if}{#if x.score != null}<dt>Match</dt><dd class="mono">{n2(x.score)}</dd>{/if}<dt>Compacted</dt><dd>{#if x.created_at}<time title={longTime(x.created_at)}>{rel(dt(x.created_at))}</time>{/if}</dd></dl>
        {:else}
          <ul class="ctx">{#each urls as u, i (i)}<li><a href={u} rel="noopener noreferrer" target="_blank">{cut(u, 90)}</a><span class="n">{String(i + 1)}</span></li>{/each}</ul>
        {/if}
      {/snippet}
    </Pane>
  {/if}
</Detail>
