<script lang="ts">
  // Settings › Privacy & access, the pane: with nothing selected what the page holds; a row opens the pane
  // of the list it came from (keeps every row's selection key, so old links land here).
  import type { View } from "../../lib/pages.svelte";
  import { groupOf } from "../../ui/settings";
  import PageAbout from "./PageAbout.svelte";
  import AccessPane from "./AccessPane.svelte";
  import PrivacyPane from "./PrivacyPane.svelte";
  let { view }: { view: View } = $props();
  const id = $derived(groupOf(view.w));
</script>

{#if !id}<PageAbout {view} />{:else if ["mode", "today", "notice", "errors"].includes(id) || id.startsWith("sent:")}<PrivacyPane {view} />{:else if id.startsWith("tok:") || id === "new-agent"}<AccessPane {view} />{:else}<PageAbout {view} missing />{/if}
