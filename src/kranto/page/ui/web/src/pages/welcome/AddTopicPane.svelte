<script lang="ts">
  // Topics › Add topic's pane (#/topics/new): its side, the topics so far and what happens next
  // (the form is the list, AddTopic). Without the server, nothing.
  import Detail from "../../ui/Detail.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { ui } from "../../lib/shell.svelte";
  import TopicAside from "./TopicAside.svelte";

  let { view }: { view: View } = $props();
  const host = $derived(!!ui.facts?.header.host);
</script>

<Detail back={view.back}>{#if host}<div class="pane-in" data-title="Add topic"><TopicAside {view} /></div>{:else}<div></div>{/if}</Detail>
