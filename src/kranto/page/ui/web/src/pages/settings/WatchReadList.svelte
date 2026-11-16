<script lang="ts">
  // Settings › Watching › Reading: how often the sources are read, a row whose pane is its
  // field and Save (UP #3; the server's /api/settings/reading writes it). Deep dives left.
  import Group from "../../ui/Group.svelte";
  import SetRow from "../../ui/SetRow.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { ui } from "../../lib/shell.svelte";
  import { SET_ST } from "../../ui/settings";
  import { READING, type Reading } from "./spend.svelte";

  let { view }: { view: View; part?: string | null } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const r = $derived.by(() => {
    void view.tick;
    return host ? read<Reading>(READING, 30000) : null;
  });
  const d = $derived(r?.data || null);
</script>

{#if host}
  <Group id="w-read" title="Reading" count="1" kind="sets">
    <SetRow key="read:every" word="How often sources are read" summary={d ? `every ${d.every_hours} h` : r?.error ? "Could not read: " + r.error : "reading…"} state={d && d.every_hours !== 3 ? SET_ST.set : SET_ST.dflt} />
  </Group>
{/if}
