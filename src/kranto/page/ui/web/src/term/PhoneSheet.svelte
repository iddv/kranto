<script lang="ts">
  // The console on a phone: read and approve, not a terminal. "Waiting for your
  // yes": each item an assistant prepared, one row with Review (the decision dialog, unchanged).
  // "What it last said": its newest reply's first lines, with the kranto page it linked, read from
  // its own transcript (the page term/console.py last_reply), or why there is nothing to read.
  // One link opens the terminal full screen anyway. A conversation is started on a wider screen.
  import { onDestroy, onMount } from "svelte";
  import { read } from "../lib/reads.svelte";
  import { PREPARED_API, gone, lineOf, waitingItems, type Prepared } from "../lib/prepared";
  import { openPrepared } from "../ui/prepared.svelte";
  import { ago, dt } from "../lib/format";
  import * as C from "./console.svelte";
  import { ui } from "../lib/shell.svelte";

  let { name = "The assistant", onfull }: { name?: string; onfull: () => void } = $props();
  // the prepared items are the server's: only asked where the server hosts the page (brb alone has none)
  const host = $derived(!!ui.facts?.header.host);
  const items = $derived(host ? waitingItems(read<{ prepared: Prepared[] }>(PREPARED_API, 10000).data?.prepared) : []);
  let said = $state<C.LastSaid | null>(null);
  let timer: ReturnType<typeof setInterval> | null = null;

  async function load(): Promise<void> {
    try {
      said = await C.last();
    } catch {
      said = { harness: null, said: null, why: "it could not be read just now" };
    }
  }
  onMount(() => {
    void load();
    timer = setInterval(() => void load(), 15000);
  });
  onDestroy(() => {
    if (timer) clearInterval(timer);
  });
</script>

<div class="phone-sheet" id="console-phone">
  <section aria-labelledby="ps-wait">
    <h2 id="ps-wait">Waiting for your yes</h2>
    {#if items.length}
      <ul class="ps-rows">
        {#each items as p (p.uuid)}
          <li><span class="ps-title">{lineOf(p)}</span><span class="ps-age">{p.created_at ? ago(dt(p.created_at)) : ""}</span><button type="button" class="btn sm" data-prepared-act={p.uuid} onclick={() => openPrepared(p)}>{gone(p) ? "Dismiss" : "Review"}</button></li>
        {/each}
      </ul>
    {:else}
      <p class="muted">Nothing waits for your yes. What an assistant prepares shows here.</p>
    {/if}
  </section>
  <section aria-labelledby="ps-said">
    <h2 id="ps-said">What it last said</h2>
    {#if said?.said}
      <p class="ps-said">{said.said}</p>
      <p class="muted small">{[name, said.at ? ago(dt(said.at)) : null].filter(Boolean).join(", ")}{#if said.page} · <a href={said.page}>the page it linked</a>{/if}</p>
    {:else}
      <p class="muted">{said ? `Nothing yet: ${said.why || "it has not said anything"}.` : "Reading…"}</p>
    {/if}
  </section>
  <p class="ps-foot muted small">On a phone you can read and approve. Start a conversation on a wider screen. <button type="button" class="linkish" id="console-phone-full" onclick={onfull}>Open the terminal full screen anyway</button></p>
</div>

<style>
  .phone-sheet { padding: 10px 14px 14px; overflow: auto; background: var(--bg); color: var(--text); flex: 1; min-height: 0; }
  h2 { font-size: 13px; font-weight: 700; margin: 8px 0 6px; }
  .ps-rows { list-style: none; margin: 0; padding: 0; }
  .ps-rows li { display: flex; align-items: center; gap: 8px; padding: 6px 0; border-bottom: 1px solid var(--border-2); }
  .ps-title { flex: 1; min-width: 0; font-weight: 600; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; }
  .ps-age { color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; }
  .ps-said { white-space: pre-line; margin: 0 0 4px; line-height: 1.4; }
  .ps-foot { margin-top: 14px; }
  .linkish { all: unset; cursor: pointer; text-decoration: underline; color: var(--link); }
</style>
