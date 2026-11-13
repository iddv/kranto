<script lang="ts">
  // Watch › Map of All topics (#/watch/map, the library's Map and Clusters in one
  // page): the map itself over the column (the inline pane, MapPane), its legend and the
  // highlight, Map now, then every theme, rising first; a theme opens in the sheet
  // (sel=c<n>). A topic's own themes are its Map, #/watch/topic/<id>/map (WT).
  import type { View } from "../../lib/pages.svelte";
  import ClustersList from "../library/ClustersList.svelte";
  import MapList from "../library/MapList.svelte";
  import Embed from "./Embed.svelte";

  let { view }: { view: View } = $props();
</script>

<MapList {view} points={false} />
<Embed><ClustersList {view} /></Embed>
