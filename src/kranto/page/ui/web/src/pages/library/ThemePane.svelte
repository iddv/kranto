<script lang="ts">
  // Library › Clusters, the pane: a theme (#/library/clusters/<n>, a cluster
  // of the latest map), what it has in common, the idea cards on its lineage, its highest-signal
  // members, its movement and its mix; Watch it, Card it now (one card on this theme on request,
  // as the owner decided: one card call and its check, after a confirm that says the cost), or see it
  // on the map. With nothing selected, "Nothing selected.". Its grade,
  // Watch's popover and Explain are the old module's, shared with Today's theme rows until Today
  // moves. A theme shown away from here (sel=c<n> on a topic's page or Today) is this pane too.
  import Explain from "../../ui/Explain.svelte";
  import { confirmThen } from "../../ui/dialog.svelte";
  import Detail from "../../ui/Detail.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Loading from "../../ui/Loading.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import Pane, { type Sec } from "../../ui/Pane.svelte";
  import { pct } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { app, ui } from "../../lib/shell.svelte";
  import { themeIdeas } from "../ideas/cards";
  import CiteLine from "../ideas/CiteLine.svelte";
  import ObsLine from "./ObsLine.svelte";
  import Spark from "./Spark.svelte";
  import { mix, obsHref, type Observations } from "./library";
  import { moveText, themeSt, type Clusters } from "./map.svelte";

  let { view }: { view: View } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const n = $derived(view.w.object === "theme" && view.w.obj ? String(view.w.obj[2]) : null);
  const c = $derived.by(() => {
    void view.tick; // each draw may find the reads stale
    return host && n ? read<Clusters>("/api/clusters", 60000) : null;
  });
  const d = $derived(c?.data || null);
  const x = $derived(d && n != null ? d.clusters.find((k) => String(k.cluster) === n) || null : null);
  // its 20 highest-signal members
  const m = $derived.by(() => {
    void view.tick;
    return x ? read<Observations>(`/api/observations?cluster=${x.cluster}&sort=signal&limit=20`, 60000) : null;
  });
  // the cards on its lineage (never by its cluster number, which means another theme in each map)
  const ideas = $derived.by(() => {
    void view.tick;
    return x ? themeIdeas(x.lineage_id) : null;
  });
  const secs = $derived.by((): Sec[] => !x ? [] : [{ id: "about", w: "About" },
    ...(ideas ? [{ id: "ideas", w: "Ideas", n: ideas.length }] : []),
    { id: "members", w: "Highest signal", n: m?.data ? m.data.results.length : null },
    { id: "movement", w: "Movement", about: x.movement ? "library.movement" : null }, { id: "mix", w: "Mix" }]);
  // one card on this theme now (the server's POST /api/themes/<lineage>/card: in the background)
  function cardIt(btn: HTMLElement, lineage: string, label: string): void {
    const L = app();
    if (!L) return;
    confirmThen(`Card "${label}" now?`, ["Kranto writes one idea card from this theme's evidence and checks its citations, outside the daily selection: one card call and its check, counted under Settings › Spend.", "The card appears under this theme's Ideas in about a minute; the same evidence is never carded twice."], "Card it",
      () => void L.act(btn, () => L.api(`/api/themes/${encodeURIComponent(lineage)}/card`, {}), () => L.toast("Writing a card on this theme: it appears under its Ideas in about a minute.")));
  }
  // the topic most of its stories come from
  const topic = $derived(x ? Object.entries(x.topic_mix || {}).sort((a, b) => b[1] - a[1])[0] : undefined);
</script>

{#snippet refs(ids: number[])}{#each ids as id, i (i)}{i ? " " : ""}<a href={obsHref(id)}>{`[${i + 1}]`}</a>{/each}{/snippet}

<Detail back={view.back}>
  {#if !n}
    <div class="pane-empty"><p class="empty">Nothing selected.</p></div>
  {:else if !host}
    <NeedHost what="The library" verb="needs" />
  {:else if !d}
    <div class="pane-in" data-title="Theme"><Loading error={c?.error} /></div>
  {:else if !x}
    <div class="pane-empty"><p class="empty">{`No cluster ${n} in the latest map. Cluster numbers change with each map.`}</p></div>
  {:else}
    {@const g = themeSt(x)}
    {@const mv = x.movement}
    <Pane title={x.label} right={`cluster ${x.cluster} · ${x.lineage_id}`} sections={secs}>
      {#snippet kind()}<Glyph name={g[0]} colour={g[1]} word={g[2]} />{` theme · ${topic ? topic[0] + " · " : ""}${g[2].toLowerCase()}`}{/snippet}
      {#snippet lede()}{`${x.stories || x.size} stories`}{mv && mv.new_in_cluster != null ? `, +${mv.new_in_cluster} since the last map` : ""}{` · ${pct(x.share, 1)} of the map of ${d.snapshot?.created_at.slice(0, 10)} · `}{x.cross_source ? "cross-source" : `one source supplies ${pct(x.max_source_share)}`}{/snippet}
      {#snippet acts()}<button class="btn sm" id="card-theme" title="One idea card from this theme's evidence now: one card call and its check" onclick={(e) => cardIt(e.currentTarget, x.lineage_id, x.label)}>Card it now</button><a class="btn sm" href={href("library/map", { c: x.cluster })}>Show on the map</a><a class="btn sm quiet" href={href("library", { cluster: x.cluster })}>{`All ${x.size} in Observations`}</a>{/snippet}
      {#snippet section(s)}
        {#if s.id === "about"}
          {#if x.synthesis}
            <p>{x.synthesis.text}</p><p class="muted small mt">{"Numbers refer to "}{@render refs(x.synthesis.input_ids)}.</p>
          {:else}
            <Explain body={{ cluster: x.cluster }} what="this cluster" />
          {/if}
        {:else if s.id === "ideas"}
          {#if ideas && ideas.length}<ul class="lst pl">{#each ideas as k (k.number)}<CiteLine x={k} />{/each}</ul>{:else}<p class="muted small">No ideas from this theme yet.</p>{/if}
        {:else if s.id === "members"}
          {#if !m?.data}<Loading error={m?.error} />{:else}<ul class="lst pl">{#each m.data.results as o (o.id)}<ObsLine {o} />{/each}</ul>{/if}
        {:else if s.id === "movement"}
          {#if mv}
            <Spark traj={x.trajectory} w="100%" ht="40px" /><dl class="kv small mt"><dt>share</dt><dd>{pct(x.share, 1)}</dd><dt>{"since " + (mv.since || "").slice(0, 10)}</dt><dd>{moveText(x)}</dd><dt>maps</dt><dd>{String(mv.points)}</dd></dl>
          {:else}
            <p class="muted">Only one map so far: no movement yet.</p>
          {/if}
        {:else}
          <dl class="kv small">{#if x.stories != null}<dt>stories</dt><dd>{`${x.stories} (copies of one text count once)`}</dd>{/if}<dt>sources</dt><dd>{mix(x.source_mix, 12)}</dd>{#if Object.keys(x.origin_mix || {}).length}<dt>origins</dt><dd>{mix(x.origin_mix, 8)}</dd>{/if}{#if Object.keys(x.topic_mix || {}).length}<dt>topics</dt><dd>{mix(x.topic_mix, 8)}</dd>{/if}{#if (x.keywords || []).length}<dt>keywords</dt><dd>{x.keywords.join(", ")}</dd>{/if}</dl>
        {/if}
      {/snippet}
    </Pane>
  {/if}
</Detail>
