<script lang="ts">
  // What an approval reads back, once (the dialog body, shared with the asks' dialog: SEND): the
  // subject in bold, a short list of key facts, and each long text drawn as markdown, collapsed to
  // a few lines with Show all. One look for every approval dialog.
  import Md from "./Md.svelte";

  // named: each long text says what it is above it (a prepared change's new voice card), where a
  // single body needs no name (a factory issue's text)
  let { subject = null, keys = [], longs = [], named = false }: { subject?: string | null; keys?: [string, string][]; longs?: [string, string][]; named?: boolean } = $props();
  let all = $state(false);
</script>

{#if subject}<p class="pd-subject"><strong>{subject}</strong></p>{/if}
{#if keys.length}
  <dl class="pd-keys">{#each keys as [k, v], i (i + ":" + k)}<dt>{k}</dt><dd>{v}</dd>{/each}</dl>
{/if}
{#each longs as [k, text], i (i + ":" + k)}
  {#if named}<p class="pd-name">{k}</p>{/if}
  <div class={"pd-body" + (all ? " open" : "")} data-field={k}><Md {text} /></div>
{/each}
{#if longs.length}<button type="button" class="linkish small" id="pd-all" aria-expanded={all} onclick={() => (all = !all)}>{all ? "Show less" : "Show all"}</button>{/if}

<style>
  .pd-subject { margin: 0 0 8px; }
  .pd-name { margin: 8px 0 2px; font-size: 13px; color: var(--muted); }
  .pd-keys { display: grid; grid-template-columns: max-content 1fr; gap: 2px 12px; margin: 0 0 10px; font-size: 13px; }
  .pd-keys dt { color: var(--muted); }
  .pd-keys dd { margin: 0; overflow-wrap: anywhere; }
  .pd-body { max-height: 7.5em; overflow: hidden; position: relative; font-size: 13px; border: 1px solid var(--line); border-radius: 6px; padding: 6px 10px; }
  .pd-body.open { max-height: 50vh; overflow: auto; }
  .pd-body:not(.open)::after { content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 2.5em; background: linear-gradient(transparent, var(--bg)); }
  .pd-body :global(p) { margin: 0 0 6px; }
  .pd-body :global(ul), .pd-body :global(ol) { margin: 0 0 6px; padding-left: 18px; }
</style>
