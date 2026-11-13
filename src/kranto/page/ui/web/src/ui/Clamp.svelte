<script lang="ts">
  // A long text that is content (a hold's reason) clamped at two lines, with more (2.1,
  // rule 5; the old page's clamp()): "more" only when it is long; it stays open while the pane is.
  let { text }: { text: string } = $props();
  let open = $state(false);
  const long = $derived(String(text || "").length > 150);
</script>

<span class="clampw"><span class={"clamp" + (open || !long ? " open" : "")}>{text}</span>{#if long}<button type="button" class="linkish small clampmore" aria-expanded={open} onclick={(e) => { e.stopPropagation(); open = !open; }}>{open ? "less" : "more"}</button>{/if}</span>
