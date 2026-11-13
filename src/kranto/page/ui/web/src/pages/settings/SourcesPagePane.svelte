<script lang="ts">
  // Settings › Sources, the pane (the accounts folded in): an account (sel=eacct:<id>)
  // or a site's page (settings/connections/<key>) opens Connections' pane; everything else, a
  // source, Add source and the page with nothing selected, Sources' own.
  import type { View } from "../../lib/pages.svelte";
  import { groupOf } from "../../ui/settings";
  import ConnectionsPane from "./ConnectionsPane.svelte";
  import SourcesPane from "./SourcesPane.svelte";

  let { view }: { view: View } = $props();
  const id = $derived(groupOf(view.w));
</script>

{#if view.w.object === "connection" || (id && id.startsWith("acct:"))}<ConnectionsPane {view} />{:else}<SourcesPane {view} />{/if}
