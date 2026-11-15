<script lang="ts">
  // A list's pages under its groups (the old page's pager()): Previous, "page 2 of 5", Next;
  // nothing when there is one page.
  import { href } from "../../lib/router";

  let { base, q, at, pages }: { base: string; q: Record<string, string>; at: number; pages: number } = $props();
</script>

{#if pages > 1}<div class="pager">{#if at > 1}<a href={href(base, { ...q, page: at - 1 })}>Previous</a>{/if}<span class="muted">{`page ${at} of ${pages}`}</span>{#if at < pages}<a href={href(base, { ...q, page: at + 1 })}>Next</a>{/if}</div>{/if}
