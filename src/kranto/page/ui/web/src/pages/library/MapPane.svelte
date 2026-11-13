<script lang="ts">
  // Library › Map, the pane (WORKSPACE.md 4, 5): the map as an SVG scatter (built once per
  // snapshot, map.svelte.ts), the selected point (?p=) with its nearest neighbours in meaning
  // (each a walk to it on the map, or its page when it is not on the map), and how to read the
  // map (a fold that stays open). ?c= dims every cluster but one, and a topic's Map (WT,
  // topics/<id>/map) every cluster but the topic's themes; the list's highlight dims the points
  // without its words. Without the server, "Nothing selected.".
  import { keepOpen, OPENED } from "../../ui/opened.svelte";
  import Detail from "../../ui/Detail.svelte";
  import Loading from "../../ui/Loading.svelte";
  import Icon from "../../shell/Icon.svelte";
  import { cut, n3, plural } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { app, ui } from "../../lib/shell.svelte";
  import { n2, obsHref } from "./library";
  import { topicApi, type TopicPage } from "../topics/topics";
  import { MAP, mapHighlight, mapRead, mapView, type Map, type ObservationPage } from "./map.svelte";

  let { view }: { view: View } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const q = $derived(view.w.r.q);
  const c = $derived.by(() => {
    void view.tick; // each draw may find the reads stale
    return host ? mapRead() : null;
  });
  // a failed read is no map, as the old page read it
  const d = $derived(c?.error ? null : c?.data || null);
  const v = $derived(d ? mapView(d) : null);
  const sel = $derived(q.p ? Number(q.p) : null);
  // a topic's Map: its themes stay lit (none yet: every cluster dims)
  const tid = $derived(/^topics\/[^/]+\/map$/.test(view.w.node || "") ? (view.w.node || "").split("/")[1]! : null);
  const tc = $derived.by(() => {
    void view.tick;
    return host && tid ? read<TopicPage>(topicApi(tid), 20000) : null;
  });
  const only = $derived(q.c || (tc?.data ? tc.data.themes_list.map((x) => x.cluster).join(",") || "-1" : null));
  // the selected point's index, when it is on the map
  const i = $derived(v && sel != null ? (v.at.get(sel)?.[2] ?? null) : null);
  const nc = $derived.by(() => {
    void view.tick;
    return i != null ? read<ObservationPage>(`/api/observations/${sel}?k=12`, 60000) : null;
  });
  const near = $derived(nc?.data ? nc.data.similar : []);
  const byC = $derived(new globalThis.Map((d?.clusters || []).map((x) => [x.cluster, x])));
  const qy = $derived(d?.snapshot.quality || {});
  const nl = $derived(qy.structure_null || {});
  const four = (x: number | undefined) => Number(x).toFixed(4);

  // the highlight follows the selection, its neighbours, ?c= and the list's words
  $effect(() => {
    if (v) mapHighlight(v, i != null ? sel : null, near, only, MAP.words);
  });
</script>

<Detail>
  {#if !host}
    <div class="pane-empty"><p class="empty">Nothing selected.</p></div>
  {:else if !d || !v}
    <div class="pane-in" data-title="Map">{#if c?.error}<p class="empty">No map yet.</p>{:else}<Loading />{/if}</div>
  {:else}
    {@const p = d.points}
    <div class="pane-in map-pane" data-title="Map"><div class="dh"><p class="dk mono">{"map · "}{plural(d.snapshot.k, "cluster")}</p><h2 class="dt">{i == null ? `${d.snapshot.n} observations` : "#" + p.id[i]}</h2>{#if i != null}<div class="acts"><span class="grow"></span><span class="muted mono small">{"signal " + n2(p.s[i])}</span></div>{/if}</div>
      <div class="viz-box" {@attach (el) => { el.replaceChildren(v.svg); }}></div>
      <section class="sec" id="s-point">
        {#if i == null}
          <p class="muted">Pick a point.</p>
        {:else}
          {@const s = p.s[i] as number}
          {@const ci = p.c[i] as number}
          <p class="inline small"><span class={"st c-" + (s >= 0.4 ? "blue" : "grey")} title="signal: content quality × durability × opportunity"><Icon name="dot" /><span>{n2(s)}</span></span><span class="muted">{d.sources[p.src[i] as number]}</span></p>
          <p class="mt">{p.t[i]}</p>
          <p class="small mt"><a href={obsHref(p.id[i] as number)}>{"Open observation #" + p.id[i]}</a>{" · cluster "}<a href={href("library/clusters/" + ci)}>{byC.get(ci)?.label || String(ci)}</a></p>
          <h3 class="mt">Nearest in meaning</h3>
          {#if !nc?.data}
            <Loading error={nc?.error} />
          {:else}
            <ul class="ctx">{#each nc.data.neighbours as n (n.id)}<li><span>{#if v.at.has(n.id)}<a href={href("library/map", { ...q, p: n.id })} title="Walk here on the map">{cut(n.summary, 110)}</a>{:else}<a href={obsHref(n.id)}>{cut(n.summary, 110)}</a>{/if}</span><span class="n">{n2(n.score)}</span></li>{/each}</ul>
          {/if}
        {/if}
      </section>
      <details class="fold" id={"map-how"} open={OPENED.has("map-how")} ontoggle={keepOpen("map-how")}><summary>How to read this map</summary><div class="small">
        <p>{`Position comes from a 2-d UMAP projection of each observation's embedding. It keeps neighbourhoods but distorts distances: two points far apart on screen are not necessarily unrelated. Clusters were found separately, in a 10-dimensional UMAP projection, with k = ${d.snapshot.k} chosen by silhouette among the best few, preferring a k whose clusters survive re-clustering a subsample.`}</p>
        {#if qy.silhouette_umap != null}<p class="mono mt">{`Cluster separation (silhouette): ${n3(qy.silhouette_umap)} in the 10-d projection, ${n3(qy.silhouette_native)} in the original embedding space. Structure-free null (${nl.reps} column permutations): ${four(nl.null_mean)} ± ${four(nl.null_sd)} vs ${four(nl.real)} real${nl.z != null ? ` (z = ${nl.z})` : ""}.`}</p>{/if}
        {#if nl.covariance_z != null}
          <p class="mono mt">{`Single-blob null (one Gaussian with this library's mean and covariance, no clusters): ${four(nl.covariance_null_mean)} ± ${four(nl.covariance_null_sd)} (z = ${nl.covariance_z}).`}</p>
          <p class="mt">{nl.clustered ? "Read together: the clusters separate better than cuts through one continuous cloud of the same shape would, but in the original space they overlap. Treat boundaries as soft." : "These clusters are not clearly better separated than cuts through one continuous cloud of the same shape (z below 2 against the single-blob null). Read them as a way to browse, not as distinct themes, and do not read movement between them as evidence."}</p>
        {:else if qy.silhouette_umap != null}
          <p class="mt">Read together: the clusters are real structure, not an artefact of the projection, but in the original space they overlap heavily. Treat boundaries as soft.</p>
        {/if}
        {#if qy.stories}<p class="mono mt">{`Stories: ${qy.stories.observations} observations tell ${qy.stories.distinct} distinct stories; copies of one text (crossposts, reposts) count once in shares, source mixes and movement.`}</p>{/if}
        <p class="mt muted">The eight largest clusters have their own colour; the others are grey. Hover a point for its text.</p>
      </div></details>
    </div>
  {/if}
</Detail>
