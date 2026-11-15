<script lang="ts">
  // The core's one topic picker: "which of your topics", for any setting of type
  // topics a feature or a cub declares, drawn on its generated Settings page in both layouts. A
  // switch per topic of yours (the navigator's list, the server's); none picked means every topic,
  // and it says so. Each press is one write of the whole list, by the caller.
  import { app } from "../lib/shell.svelte";

  let { id, value, pick }: { id: string; value: unknown; pick: (ids: number[], btn: HTMLElement) => void } = $props();
  const topics = $derived((app()?.host()?.topics as { id: number; name: string }[] | undefined) || []);
  const chosen = $derived(Array.isArray(value) ? value.map(Number) : []);
  const words = $derived(!chosen.length ? `Every topic (${topics.length})` : `${chosen.length} of ${topics.length} topics`);
  function toggle(t: number, btn: HTMLElement): void {
    pick(chosen.includes(t) ? chosen.filter((x) => x !== t) : [...chosen, t].sort((a, b) => a - b), btn);
  }
</script>

<span class="tp" {id} role="group" aria-label="Topics">
  <span class="muted small tp-w">{words}</span>
  {#each topics as t (t.id)}{@const on = chosen.includes(t.id)}<button class="chip" aria-pressed={on ? "true" : "false"} data-topic={t.id} onclick={(e) => toggle(t.id, e.currentTarget)}>{t.name}</button>{" "}{/each}
  {#if !topics.length}<span class="muted small">No topics yet.</span>{/if}
</span>

<style>
  .tp { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; justify-content: flex-end; }
  .tp-w { flex-basis: 100%; text-align: right; }
  @media (max-width: 700px) { .tp { justify-content: flex-start; } .tp-w { text-align: left; } }
</style>
