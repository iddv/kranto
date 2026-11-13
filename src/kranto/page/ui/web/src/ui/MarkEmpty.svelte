<script lang="ts">
  import { pageUrl } from "../lib/base";
  // An empty state (PLAN.md 1.5; UI-v4.md 1.4; the old page's markEmpty): the mark, one sentence
  // that says what will appear and when, and one link.
  import type { Snippet } from "svelte";

  let { text, children }: { text: string; children?: Snippet } = $props();
</script>

<div class="mark-empty"><img src={pageUrl("static/brand/icon-192.png")} alt="" width="96" height="96" /><p>{text}</p>{@render children?.()}</div>
