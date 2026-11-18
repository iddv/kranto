<script lang="ts">
  // Mute's menu: 7 days, 30 days, read less, or Retire; each acts on every topic the source
  // feeds, and says so when that is more than one (reach: "everywhere: all 4 topics").
  let { label, pick, reach = null }: { label: string; pick: (what: string) => void; reach?: string | null } = $props();
</script>

{#snippet item(what: string, words: string)}<button role="menuitem" type="button" onclick={() => pick(what)}><span class="grow">{words}{#if reach}<small class="m-note">{reach}</small>{/if}</span></button>{/snippet}
<div class="muted small pop-h">{label}</div>{@render item("7", "Mute for 7 days")}{@render item("30", "Mute for 30 days")}{@render item("less", "Read less")}{@render item("retire", "Retire")}

<style>
  .m-note { display: block; color: var(--muted); font-size: 11.5px; font-weight: 400; line-height: 1.3; }
</style>
