<script lang="ts">
  // Library › Map, the list: the clusters' legend (each shows alone on the
  // map, ?c=, or opens its theme), then the points as rows, by cluster, highest signal first; a
  // point's row selects it on the map (?p=; j and k walk the points). "Highlight observations
  // containing…" dims the others on the map in the pane (MAP.words). Before the first map: what
  // it needs, with Map now. Without the server, it says so.
  import Glyph from "../../ui/Glyph.svelte";
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import Loading from "../../ui/Loading.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import Row from "../../ui/Row.svelte";
  import { cut } from "../../lib/format";
  import { confirmThen } from "../../ui/dialog.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { app, ui } from "../../lib/shell.svelte";
  import { shellDoors } from "../../features/shell";
  import { listRoute } from "../data.svelte";
  import { n2 } from "./library";
  import { MAP, dimmed, mapRead, slots, type Clusters, type Map } from "./map.svelte";

  // points: the points as rows, by cluster (the doors draw the map itself over the themes instead:
  // every dot a control was 9,660 of them)
  let { view, points = true }: { view: View; points?: boolean } = $props();
  const base = "library/map";
  const host = $derived(!!ui.facts?.header.host);
  const r = $derived(listRoute(view.w));
  const c = $derived.by(() => {
    void view.tick; // each draw may find the reads stale
    return host ? mapRead() : null;
  });
  // no map yet (or a failed read): the page says so, with the clusters' progress line
  const d = $derived(c?.error ? null : c?.data || null);
  const progress = $derived.by(() => {
    void view.tick;
    return c?.error ? read<Clusters>("/api/clusters", 60000).data?.progress || null : null;
  });
  const slot = $derived(d ? slots(d) : null);
  const sel = $derived(r.q.p ? Number(r.q.p) : null);
  const only = $derived(r.q.c != null && r.q.c !== "" ? String(r.q.c) : null);
  // each cluster's points, highest signal first (one cluster alone with ?c=)
  const groups = $derived.by(() => {
    if (!d) return [];
    const p = d.points;
    return d.clusters.filter((cl) => only == null || String(cl.cluster) === only).map((cl) => ({
      cl, ks: p.id.map((_, k) => k).filter((k) => p.c[k] === cl.cluster).sort((a, b) => (p.s[b] as number) - (p.s[a] as number)),
    }));
  });
  // how many points the words leave lit (with two letters or more)
  const count = $derived.by(() => {
    if (!d || MAP.words.trim().length <= 1) return "";
    const p = d.points;
    return `${p.id.filter((_, k) => !dimmed(p.t[k] ?? "", p.c[k] as number, r.q.c, MAP.words)).length} highlighted`;
  });

  function build(e: MouseEvent): void {
    const btn = e.currentTarget as HTMLElement;
    // with a map there, a new one is a choice that spends: the house confirm
    if (d) confirmThen("Draw the map again now?", "Every observation is placed again and the themes named: model calls through your provider, as the scheduled map makes.", "Map now", () => buildNow(btn));
    else buildNow(btn);
  }
  function buildNow(btn: HTMLElement): void {
    const L = app();
    L?.act(btn, async () => {
      const x = await L.hostForm("/run/snapshot");
      L.afkDrop();
      return x;
    }, () => L.say("Started building the map. It shows here when it is done."));
  }
</script>

{#snippet swatch(cluster: number)}<span class={"swatch k" + slot?.get(cluster)} aria-hidden="true"></span>{/snippet}

{#if !host}
  <div data-title="Library"><NeedHost what="The library" verb="needs" /></div>
{:else}
  <List title={shellDoors(host) ? "All topics › Map" : "Map"} crumb={shellDoors(host) ? null : "All topics"}>
    {#snippet tools()}<span class="tbn"><input type="search" id="map-filter" class="tb-q" placeholder="Highlight observations containing…" aria-label="Highlight observations containing" value={MAP.words} oninput={(e) => (MAP.words = e.currentTarget.value)} /><span class="muted" id="map-count">{count}</span>{#if !points && d}<span class="grow"></span><button type="button" class="btn sm" id="map-build" onclick={build}>Map now</button>{/if}</span>{/snippet}
    {#if c?.error}
      <section class="box"><div class="box-b"><p>No map yet. A map needs at least 30 observations; Kranto draws it again on a schedule while it runs, or now with Map now.</p>{#if progress}<p class="muted mt">{progress}</p>{/if}<button class="btn mt" onclick={build}>Map now</button></div></section>
    {:else if !d}
      <Loading />
    {:else}
      {@const p = d.points}
      <p class="quiet-topics">{`${Number(d.snapshot.n).toLocaleString("en-GB")} observations · ${d.snapshot.k} clusters · mapped ${(d.snapshot.created_at || "").slice(0, 10)}`}</p>
      {#if points}<Group id="legend" title="Clusters" count={String(d.clusters.length)} kind="legend">
        {#snippet right()}{#if only != null}<a href={href(base, { ...r.q, c: "", p: "" })}>Show all</a>{/if}{/snippet}
        {#each d.clusters as cl (cl.cluster)}
          <Row title={cut(cl.label, 80)} href={href(base, { ...r.q, c: only === String(cl.cluster) ? "" : cl.cluster, p: "" })} meta={[only === String(cl.cluster) ? "shown alone" : null, cl.cross_source ? "cross-source" : null].filter(Boolean).join(" · ")}>
            {#snippet st()}{@render swatch(cl.cluster)}{/snippet}
            {#snippet num()}{String(cl.size)}{/snippet}
            {#snippet end()}<a class="btn sm quiet" href={href("library/clusters/" + cl.cluster)} title="About this cluster">About</a>{/snippet}
          </Row>
        {/each}
      </Group>{/if}
      {#each points ? groups : [] as { cl, ks } (cl.cluster)}
        <Group id={"pts-" + cl.cluster} title={cut(cl.label, 60)} count={String(ks.length)} kind="pts">
          {#snippet right()}{@render swatch(cl.cluster)}{/snippet}
          {#each ks as k (k)}
            {@const s = p.s[k] as number}
            {@const id = p.id[k] as number}
            <Row go={href(base, { ...r.q, p: id })} cur={id === sel} hot={s >= 0.3} title={cut(p.t[k], 160)} href={href(base, { ...r.q, p: id })} meta={"#" + id} asideText>
              {#snippet st()}<Glyph name="dot" colour={s >= 0.3 ? "blue" : "grey"} word={"signal " + n2(s)} />{/snippet}
              {#snippet num()}{n2(s)}{/snippet}
              {#snippet aside()}{d.sources[p.src[k] as number] || ""}{/snippet}
            </Row>
          {/each}
        </Group>
      {/each}
    {/if}
  </List>
{/if}
