<script lang="ts">
  // A topic's Themes (WORKSPACE.md 2.6): the latest map's clusters whose stories come mostly from
  // the topic's sources, rising first, each opening in the pane (sel=c<n>, Library › Clusters'
  // pane); when the map was made and a link to it. As Watch's Map of one topic (WT, title
  // "Robotics › Map") the map itself is over the column, with the other topics' clusters dimmed.
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import { pct } from "../../lib/format";
  import ThemeLine from "../library/ThemeLine.svelte";
  import { themeOrder, type TopicPage } from "./topics";

  let { t, at = 0, title = null }: { t: TopicPage; at?: number; title?: string | null } = $props();
  const list = $derived(themeOrder(t.themes_list));
</script>

<List title={title || "Themes"} label={title || t.name + " · Themes"} crumb={title ? null : t.name}>
  {#if list.length}
    <Group id="th" title="Themes" about={{ text: `Clusters of the latest map whose stories come at least ${pct(0.2)} from this topic's sources. Rising first.` }} count={String(list.length)} kind="themes">
      {#snippet right()}{#if t.snapshot}<span class="muted">{"mapped " + t.snapshot.created_at.slice(0, 10) + " · "}</span>{/if}<a href={title ? "#/watch/map" : "#/library/map"}>{title ? "All topics' map" : "Map"}</a>{/snippet}
      {#each list as c (c.cluster)}<ThemeLine {c} {t} {at} />{/each}
    </Group>
  {:else}
    <p class="empty">{t.snapshot ? "No cluster in the latest map comes mostly from this topic yet." : t.progress || "No map yet."}</p>
  {/if}
</List>
