<script lang="ts">
  // Library › Rollups, the list: the compacted weeks, newest first, 50 a page; the search finds
  // the 100 that match best (paged here). Each opens in the pane (sel=u<id>). Without the server,
  // it says so.
  import FilterBar from "../../ui/FilterBar.svelte";
  import { untrack } from "svelte";
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import Loading from "../../ui/Loading.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import { plural } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { app, ui } from "../../lib/shell.svelte";
  import { listRoute } from "../data.svelte";
  import Pager from "./Pager.svelte";
  import RollupLine from "./RollupLine.svelte";
  import { ROLLUPS_PAGE, rollupsPath, type Rollups } from "./library";

  let { view }: { view: View } = $props();
  const base = "library/rollups";
  const host = $derived(!!ui.facts?.header.host);
  const r = $derived(listRoute(view.w));
  const at = $derived(Math.max(1, parseInt(r.q.page || "", 10) || 1));
  const c = $derived.by(() => {
    void view.tick; // each draw may find the reads stale
    return host ? read<Rollups>(rollupsPath(r.q), 60000) : null;
  });
  const d = $derived(c?.data || null);
  const rows = $derived(!d ? [] : r.q.q ? d.results.slice((at - 1) * ROLLUPS_PAGE, at * ROLLUPS_PAGE) : d.results);
  const total = $derived(!d ? 0 : r.q.q ? d.results.length : d.total ?? 0);

</script>

{#if !host}
  <div data-title="Library"><NeedHost what="The library" verb="needs" /></div>
{:else}
  <List title="Rollups" about="rollups" crumb="All topics">
    {#snippet tools()}<span class="tbn filters"><FilterBar r={{ path: [base], q: r.q, sel: null }} base={base} placeholder="Search the compacted weeks" selects={[] as never} /></span>{/snippet}
    {#if !d}
      <Loading error={c?.error} />
    {:else}
      <p class="quiet-topics" title={`Kept for ${d.retention_line}, then compacted.`}>{`${plural(d.rollups, "rollup")} stand in for ${plural(d.replaced, "observation")}.`}</p>
      {#if rows.length}
        <Group id="ru" title={r.q.q ? "Matching rollups" : "Compacted weeks"} count={String(total)} kind="rollups">
          {#each rows as x (x.id)}<RollupLine {x} {base} q={r.q} />{/each}
        </Group>
      {:else}
        <p class="empty">{r.q.q ? `No rollup matches "${r.q.q}".` : "Nothing has been compacted yet."}</p>
      {/if}
      <Pager {base} q={r.q} {at} pages={Math.max(1, Math.ceil(total / ROLLUPS_PAGE))} />
    {/if}
  </List>
{/if}
