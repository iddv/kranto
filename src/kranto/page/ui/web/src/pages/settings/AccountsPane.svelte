<script lang="ts">
  // Settings › Posting, the sheet: a posting account (ConnectionsPane), as its old page opened it,
  // or the newsletter platform (NewsletterPane).
  import type { View } from "../../lib/pages.svelte";
  import { groupOf } from "../../ui/settings";
  import ConnectionsPane from "./ConnectionsPane.svelte";
  import NewsletterPane from "./NewsletterPane.svelte";
  import PageAbout from "./PageAbout.svelte";

  let { view }: { view: View } = $props();
  const id = $derived(groupOf(view.w));
</script>

{#if view.w.object === "connection" || (id && id.startsWith("acct:"))}<ConnectionsPane {view} />{:else if id === "nl"}<NewsletterPane {view} />{:else}<PageAbout {view} />{/if}
