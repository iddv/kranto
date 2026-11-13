<script lang="ts">
  // Settings › Watching, the pane: with nothing selected what the page holds; a row opens the pane
  // of the list it came from (keeps every row's selection key, so old links land here).
  import type { View } from "../../lib/pages.svelte";
  import { groupOf } from "../../ui/settings";
  import PageAbout from "./PageAbout.svelte";
  import KeysPane from "./KeysPane.svelte";
  import ModelsPane from "./ModelsPane.svelte";
  import WatchReadPane from "./WatchReadPane.svelte";
  import SearchPane from "./SearchPane.svelte";
  import ConnectionsPane from "./ConnectionsPane.svelte";
  let { view }: { view: View } = $props();
  const id = $derived(groupOf(view.w));
</script>

{#if view.w.object === "connection" || (id && id.startsWith("acct:"))}<ConnectionsPane {view} />{:else if !id}<PageAbout {view} />{:else if id === "key"}<KeysPane {view} />{:else if id.startsWith("role:")}<ModelsPane {view} />{:else if id.startsWith("read:")}<WatchReadPane {view} />{:else if id === "search" || id.startsWith("search:")}<SearchPane {view} />{:else}<PageAbout {view} missing />{/if}
