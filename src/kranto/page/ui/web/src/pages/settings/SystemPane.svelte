<script lang="ts">
  // Settings › System, the pane: with nothing selected what the page holds; a row opens the pane
  // of the list it came from (keeps every row's selection key, so old links land here).
  import type { View } from "../../lib/pages.svelte";
  import { groupOf } from "../../ui/settings";
  import PageAbout from "./PageAbout.svelte";
  import GradesPane from "./GradesPane.svelte";
  import HealthPane from "./HealthPane.svelte";
  import ServicePane from "./ServicePane.svelte";
  import UpdatesPane from "./UpdatesPane.svelte";
  import ShellPane from "./ShellPane.svelte";
  import ActivitySetPane from "./ActivitySetPane.svelte";
  import MemorySetPane from "./MemorySetPane.svelte";
  let { view }: { view: View } = $props();
  const id = $derived(groupOf(view.w));
</script>

{#if !id}<PageAbout {view} />{:else if id === "service-memory"}<MemorySetPane {view} />{:else if id.startsWith("service")}<ServicePane {view} />{:else if ["version", "auto", "channel"].includes(id) || id.startsWith("hist:")}<UpdatesPane {view} />{:else if ["calls", "items", "from", "retention", "memory", "reading"].includes(id) || /^(run|err|msg|dec):/.test(id)}<HealthPane {view} />{:else if id === "grades"}<GradesPane {view} />{:else if id === "caps"}<ShellPane {view} />{:else if id === "activity"}<ActivitySetPane {view} />{:else}<PageAbout {view} missing />{/if}
