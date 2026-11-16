<script lang="ts">
  // A theme (a cluster of the latest map) as one row (the old page's themeLine): rising, burst
  // or steady, its stories, the label with its source mix, its share and its movement, the
  // sparkline and the new arrivals. It opens in the pane (library/clusters/<n>). On a
  // topic's pages (t) its share is the topic's ("40% from this topic"). On Today (today:
  // The server's rising themes) it is Rising, its topic's name first, with no share and no age.
  import type { Cluster, TopicRef } from "../../api/afk.gen";
  import Glyph from "../../ui/Glyph.svelte";
  import Row from "../../ui/Row.svelte";
  import { pct } from "../../lib/format";
  import { href } from "../../lib/router";
  import { app } from "../../lib/shell.svelte";
  import Spark from "./Spark.svelte";
  import { moveText, themeSt } from "./map.svelte";

  /** a map's cluster, a topic's theme (topic_share) or one of Today's rising themes (topic; its
   * grade is sent but not typed in afk.gen.ts's RisingTheme) */
  type Theme = Pick<Cluster, "cluster" | "lineage_id" | "label" | "name" | "keywords" | "size" | "stories" | "cross_source" | "rising" | "movement" | "trajectory">
    & { share?: number | null; topic_share?: number | null; grade?: unknown; topic?: TopicRef };
  let { c, t = null, today = false, at = 0 }: { c: Theme; t?: { id: number; name: string } | null; today?: boolean; at?: number } = $props();
  const g = $derived<[string, string, string]>(today ? ["ready", "blue", "Rising"] : themeSt(c));
  const share = $derived(t && c.topic_share != null ? `${pct(c.topic_share)} from this topic` : c.share != null ? `${pct(c.share, 1)} of the map` : null);
  const meta = $derived((today ? [c.topic?.name, c.cross_source ? "cross-source" : "mostly one source", moveText(c)]
    : [g[2].toLowerCase(), c.cross_source ? "cross-source" : "mostly one source", share, moveText(c)]).filter(Boolean).join(" · "));
  const fresh = $derived(c.movement?.new_in_cluster);
</script>

<Row sel={"c" + c.cluster} title={c.label} href={href("library/clusters/" + c.cluster)} {meta} age={!today && fresh != null ? "+" + fresh : null}>
  {#snippet st()}<Glyph name={g[0]} colour={g[1]} word={g[2]} />{/snippet}
  {#snippet num()}{String(c.stories || c.size)}{/snippet}
  {#snippet aside()}<Spark traj={c.trajectory} />{/snippet}
</Row>
