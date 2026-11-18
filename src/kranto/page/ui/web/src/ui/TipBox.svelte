<script lang="ts">
  // A ? tip's words in the one popover, with a link to its paragraph on /brb/help when it has one.
  // The address is the page's own (pageUrl): the page is drawn at "/" and the help is served
  // beside its files, so a bare "help#…" opened "/help", which does not exist.
  import { pageUrl } from "../lib/base";

  let { text, docs }: { text: string; docs: string | null } = $props();
</script>

<p>{text}</p>{#if docs}<a href={pageUrl("help#" + docs)} target="_blank" rel="noopener">More in the docs ↗</a>{/if}
