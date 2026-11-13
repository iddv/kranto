<script lang="ts">
  // Watch › Evidence's sheet: an observation's (ObsPane), or with ?group=rollups a compacted week's
  // (RollupPane), as the library's two pages had.
  import type { View } from "../../lib/pages.svelte";
  import ObsPane from "../library/ObsPane.svelte";
  import RollupPane from "../library/RollupPane.svelte";

  let { view }: { view: View } = $props();
</script>

{#if view.w.r.q.group === "rollups"}<RollupPane {view} />{:else}<ObsPane {view} />{/if}
