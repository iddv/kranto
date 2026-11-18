<script lang="ts">
  // What a cub asks you, one line each: the draft's title, where it stands ("ready", "needs a
  // newsletter account", "practice: nothing is sent") and the action's own button, which opens its
  // dialog (AskDialog; a draft offered again is asked for again by that click). The top of the
  // cub's page, and Cubs › Approvals with every cub's (cub: null). The server's GET /api/asks says
  // them: an ask that ran out of time with a newer draft since, or one already answered, is gone.
  import { read } from "../../lib/reads.svelte";
  import { ago, dt } from "../../lib/format";
  import { ASKS_API, type AskRow } from "../ask";
  import { openAsk } from "../cubverbs";

  let { cub = null, tick = 0, titles = {} }: { cub?: string | null; tick?: number; titles?: Record<string, string> } = $props();
  const rows = $derived.by(() => {
    void tick;
    return read<{ asks: AskRow[] }>(cub ? `${ASKS_API}?cub=${encodeURIComponent(cub)}` : ASKS_API, 15000).data?.asks || [];
  });
</script>

{#each rows as r, i (r.cub + ":" + r.id)}
  <div class="ask-row" data-ask={r.cub + ":" + r.id}>
    <span class="grow" title={r.title}>{#if !cub && titles[r.cub]}<span class="muted">{titles[r.cub] + " · "}</span>{/if}{r.title}<span class="muted">{" · " + r.meta}{r.at ? " · " + ago(dt(r.at)) : ""}</span></span>
    <button type="button" class={"btn sm" + (i === 0 ? " primary" : "")} data-act="ask-open" onclick={(e) => openAsk({ cub: r.cub, ticket: r.ticket, again: r.again }, e.currentTarget)}>{r.verb}</button>
  </div>
{/each}

<style>
  .ask-row { display: flex; align-items: center; gap: 10px; margin: 6px 0; padding: 7px 12px; border: 1px solid var(--line); border-left: 4px solid var(--amber); border-radius: 8px; font-size: 13px; }
  .grow { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
