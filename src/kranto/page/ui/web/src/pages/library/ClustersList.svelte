<script lang="ts">
  // Library › Clusters, the list: the latest map's clusters as themes, largest
  // first, most cross-source, or moving beyond what the sources explain; each opens in the pane
  // (library/clusters/<n>). Under them the Parallax archive's themes (Parallax's own clusters,
  // followed across its snapshots: the alive ones and those that ran eight snapshots or more),
  // each listing its members in Observations. Without the server, it says so.
  import Glyph from "../../ui/Glyph.svelte";
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import Loading from "../../ui/Loading.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import Row from "../../ui/Row.svelte";
  import { plural } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { go, href } from "../../lib/router";
  import { ui } from "../../lib/shell.svelte";
  import { listRoute } from "../data.svelte";
  import Spark from "./Spark.svelte";
  import ThemeLine from "./ThemeLine.svelte";
  import { ARCHIVE_THEMES, type ArchiveTheme, type ArchiveThemes, type Clusters } from "./map.svelte";

  let { view }: { view: View } = $props();
  const SORTS: [string, string][] = [["", "largest"], ["cross", "most cross-source"], ["moving", "moving beyond what the sources explain"]];
  const host = $derived(!!ui.facts?.header.host);
  const r = $derived(listRoute(view.w));
  const sort = $derived(["cross", "moving"].includes(r.q.sort || "") ? (r.q.sort as string) : "");
  const c = $derived.by(() => {
    void view.tick; // each draw may find the reads stale
    return host ? read<Clusters>("/api/clusters" + (sort ? "?sort=" + sort : ""), 60000) : null;
  });
  const d = $derived(c?.data || null);
  const a = $derived.by(() => {
    void view.tick;
    return host && d?.snapshot ? read<ArchiveThemes>(ARCHIVE_THEMES, 600000).data : null;
  });
  // the archive's themes worth a row: alive in Parallax's latest snapshot, or long-lived
  const px = $derived(a && a.themes.length ? a.themes.filter((t) => t.alive || t.epochs >= 8) : null);
  const day = (s: string | null | undefined) => (s || "").slice(0, 10);
  const archiveMeta = (t: ArchiveTheme) => [t.alive ? "alive" : "ended", `${day(t.first_at)} to ${day(t.last_at)}`, plural(t.epochs, "snapshot"),
    t.dispatches.length ? `in ${plural(t.dispatches.length, "dispatch", "dispatches")}` : null, t.keywords.length ? t.keywords.slice(0, 5).join(", ") : null].filter(Boolean).join(" · ");
</script>

{#if !host}
  <div data-title="Library"><NeedHost what="The library" verb="needs" /></div>
{:else}
  <List title="Clusters" about="library.clusters" crumb="All topics">
    {#snippet tools()}<span class="tbn"><select class="tb-f" aria-label="Sort" onchange={(e) => go("library/clusters", { sort: e.currentTarget.value })}>{#each SORTS as [v, w] (v)}<option value={v} selected={sort === v}>{"sort " + w}</option>{/each}</select><span class="grow"></span><a href="#/library/map">Map</a></span>{/snippet}
    {#if !d}
      <Loading error={c?.error} />
    {:else if !d.snapshot}
      <p class="empty">{"No map yet, so no clusters. " + (d.progress || "")}</p>
    {:else}
      <Group id="cl" title="Themes" count={String(d.clusters.length)} kind="themes">
        {#snippet right()}<span class="muted">{`the map of ${d.snapshot?.created_at.slice(0, 10)}`}</span>{/snippet}
        {#each d.clusters as x (x.cluster)}<ThemeLine c={x} at={view.tick} />{/each}
      </Group>
      {#if px}
        <div id="parallax-themes">
          <Group id="px" title="Parallax themes" count={String(px.length)} kind="themes">
            {#snippet right()}<a href={href("library", { source: "parallax" })}>the archive in Observations</a>{/snippet}
            {#each px as t (t.lineage_id)}
              <Row title={t.name || t.lineage_id} href={t.members ? href("library", { theme: t.lineage_id }) : null} meta={archiveMeta(t)}>
                {#snippet st()}{#if t.alive}<Glyph name="dot" colour="green" word="Alive: in Parallax's latest snapshot" />{:else}<Glyph name="dot" colour="grey" word="Ended before Parallax's latest snapshot" />{/if}{/snippet}
                {#snippet num()}{String(t.size)}{/snippet}
                {#snippet aside()}<Spark traj={t.trajectory} />{/snippet}
              </Row>
            {/each}
          </Group>
        </div>
      {/if}
    {/if}
  </List>
{/if}
