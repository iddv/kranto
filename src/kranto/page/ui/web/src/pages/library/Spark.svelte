<script lang="ts">
  // A theme's share over the maps as a sparkline (the old page's spark()): nothing with fewer
  // than two; w and ht size it (a pane's Movement), else the row's cell does.
  import type { ArchivePoint, TrajectoryPoint } from "../../api/afk.gen";
  import { sparkLine } from "./map.svelte";

  let { traj, w = null, ht = null }: { traj: (TrajectoryPoint | ArchivePoint)[] | null | undefined; w?: string | null; ht?: string | null } = $props();
  const s = $derived(sparkLine(traj));
</script>

{#if s}<svg viewBox="0 0 100 24" preserveAspectRatio="none" class="spark" role="img" aria-label={s.label} style:width={w} style:height={ht}><polyline points={s.points} /></svg>{/if}
