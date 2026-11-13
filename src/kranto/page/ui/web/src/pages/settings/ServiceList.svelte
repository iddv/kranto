<script lang="ts">
  // Settings › System › Service: where Kranto runs, read-only here; the home, the
  // port and the service change with kranto setup system, on the machine, and after a restart.
  // One fact a row: its address.
  import Group from "../../ui/Group.svelte";
  import SetRow from "../../ui/SetRow.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { app } from "../../lib/shell.svelte";
  import { SET_ST } from "../../ui/settings";
  import { read } from "../../lib/reads.svelte";
  import { memoryWords, SERVICE_SETTINGS, type ServiceMemory } from "./memoryset";

  let { view }: { view: View; part?: string | null } = $props();
  // service.memory: the server's; none where the server does not host the page
  const host = $derived(!!app()?.host());
  const mem = $derived.by(() => {
    void view.tick;
    return host ? read<{ memory: ServiceMemory }>(SERVICE_SETTINGS, 15000) : null;
  });
</script>

<Group id="sys-service" title="Service" count={host ? "2" : "1"} kind="sets">
  <SetRow key="service" word="Where Kranto runs" summary={location.host} state={SET_ST.set} />
  {#if mem}<SetRow key="service-memory" word="Memory" summary={mem.data ? memoryWords(mem.data.memory) : mem.error ? `Could not read it: ${mem.error}` : "reading…"} state={SET_ST.set} />{/if}
</Group>
