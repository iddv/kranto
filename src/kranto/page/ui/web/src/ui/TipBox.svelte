<script lang="ts">
  // A ? tip's words in the one popover, with a link to its paragraph on /brb/help when it has one.
  let { text, docs }: { text: string; docs: string | null } = $props();
</script>

<p>{text}</p>{#if docs}<a href={"help#" + docs} target="_blank" rel="noopener">More in the docs ↗</a>{/if}
