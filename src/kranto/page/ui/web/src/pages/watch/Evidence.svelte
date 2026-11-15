<script lang="ts">
  // Watch › Evidence (#/watch/evidence, the library's Observations and every
  // topic's Evidence in one list): new since your visit, seen before; ?topic= narrows it (its
  // Topic filter); ?group=rollups is the compacted weeks (the library's Rollups, merged here). An
  // observation opens in the sheet.
  import type { View } from "../../lib/pages.svelte";
  import { href } from "../../lib/router";
  import ObsList from "../library/ObsList.svelte";
  import RollupsList from "../library/RollupsList.svelte";

  let { view }: { view: View } = $props();
  const rollups = $derived(view.w.r.q.group === "rollups");
</script>

{#if rollups}
  <p class="topic-only"><a href="#/watch/evidence">Evidence</a><span class="muted"> · </span>the compacted weeks</p>
  <RollupsList {view} />
{:else}
  <ObsList {view} />
  <p class="topic-only foot"><a href={href("watch/evidence", { group: "rollups" })} id="rollups-link">The compacted weeks (rollups) ›</a></p>
{/if}
