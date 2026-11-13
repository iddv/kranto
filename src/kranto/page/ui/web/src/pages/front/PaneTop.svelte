<script lang="ts">
  // The head of a Today row's own pane (an issue, a message, the proposals, the queue; the old
  // page's paneTop): the kind line, the title, a lede, the actions. It does not stick: these panes
  // are short. Its sections are Sec.svelte.
  import type { Snippet } from "svelte";

  let { kind, title, lede = null, acts }: { kind: Snippet; title: string; lede?: Snippet | string | null; acts?: Snippet } = $props();
</script>

<p class="dk mono">{@render kind()}</p><h2 class="dt">{title}</h2>{#if lede}<p class="lede">{#if typeof lede === "string"}{lede}{:else}{@render lede()}{/if}</p>{/if}{#if acts}<div class="acts">{@render acts()}</div>{/if}
