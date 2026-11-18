<script lang="ts">
  // Topics, the pane (WORKSPACE.md 2.7): with nothing selected, a topic's pages show the topic
  // (TopicCard: its facts, what is rising, its best sources; Scout more, Pause, Add source), and
  // the Topics node says "Nothing selected."; a row of the Topics node is its topic (sel=t<id>).
  // A source (sel=s<id>), an observation (sel=o<id>) or a theme (sel=c<n>) is its home's moved
  // pane; a card or a build the old module's or Builds'.
  import Detail from "../../ui/Detail.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { ui } from "../../lib/shell.svelte";
  import TopicCard from "./TopicCard.svelte";

  let { view }: { view: View } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const node = $derived(view.w.node || "");
  const code = $derived(view.w.object === "need" ? view.w.id || "" : null);
  // the topic the pane shows: a Topics row's, else the topic page's own
  const topic = $derived(code ? (code[0] === "t" ? code.slice(1) : null) : !view.w.object && /^topics\/[^/]+/.test(node) ? (node.split("/")[1] as string) : null);
</script>

{#snippet gone(text: string)}<div class="pane-empty"><p class="empty">{text}</p></div>{/snippet}

<Detail back={view.back}>
  {#if code && !host}
    {@render gone("This comes from the server, which is not answering.")}
  {:else if topic && host}
    <TopicCard {view} id={topic} />
  {:else if code}
    {@render gone("Nothing to show.")}
  {:else}
    {@render gone("Nothing selected.")}
  {/if}
</Detail>
