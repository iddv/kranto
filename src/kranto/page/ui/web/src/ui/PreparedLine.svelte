<script lang="ts">
  // An action an assistant prepared for this page, as one line under
  // the page's head (it carried the whole body of an issue, about 20 lines): "✦ Claude Code
  // prepared: Turn usage reports off · 5 min ago", the action's own button (its dialog reads it back
  // once; only that dialog's button acts) and Dismiss. Nothing happens until the owner approves it.
  // Needs you and the home list every prepared item as a row of their own, so none draws here
  // (lib/prepared.ts LISTED_ON). From the server's GET /api/prepared (none where the server does not
  // host the page).
  import { landOf } from "../lib/app/route";
  import { read } from "../lib/reads.svelte";
  import { ui } from "../lib/shell.svelte";
  import { ago, dt } from "../lib/format";
  import { buttonOf, gone, lineOf, PREPARED_API, preparedHere, selOf, whoOf, type Prepared } from "../lib/prepared";
  import { actPrepared, openPrepared, refusedPrepared } from "./prepared.svelte";
  import { toggleConsole } from "../term/console.svelte";

  // inSheet: drawn in the selection's sheet (App's #detail). While a sheet is open the page under
  // it is dimmed and takes no click, so an item for the selected object waits in the sheet, and
  // the page's head keeps the others (PAR: a source's Retire waited under the sheet, unclickable)
  let { inSheet = false }: { inSheet?: boolean } = $props();
  const host = $derived(!!ui.facts?.header?.host);
  const rows = $derived.by(() => {
    void ui.drawn;
    if (!host) return [];
    const here = preparedHere(read<{ prepared: Prepared[] }>(PREPARED_API, 10000).data?.prepared, location.hash, (h) => landOf(h));
    const forSel = (p: Prepared) => !!selOf(landOf(p.page || ""));
    return here.filter((p) => (ui.sheet && forSel(p)) === inSheet);
  });
</script>

{#each rows as p (p.uuid)}
  <div class="prepared" role="status" data-prepared={p.uuid} id={"prepared-" + p.uuid}>
    <span class="mark" aria-hidden="true">✦</span>
    <span class="grow" title={lineOf(p)}>{`${whoOf(p)} prepared: ${lineOf(p)}`}{#if p.created_at}<span class="muted">{" · " + ago(dt(p.created_at))}</span>{/if}</span>
    {#if !gone(p)}<button type="button" class="btn sm primary" onclick={() => openPrepared(p)}>{buttonOf(p)}</button>{/if}
    <button type="button" class="btn sm quiet" onclick={() => void actPrepared(p, "dismiss")}>Dismiss</button>
  </div>
  {#if refusedPrepared[p.uuid]}
    <div class="refused" role="alert" data-refused={p.uuid}>
      <span class="grow">{refusedPrepared[p.uuid]}{" Dismiss it, or ask the assistant in the console to prepare it again with this fixed."}</span>
      <button type="button" class="btn sm" onclick={() => toggleConsole()}>Open the console</button>
    </div>
  {/if}
{/each}

<style>
  .prepared { display: flex; align-items: center; gap: 10px; margin: 8px 0 4px; padding: 7px 12px; border: 1px solid var(--violet); border-left-width: 4px; border-radius: 8px; background: var(--violet-wash); font-size: 13px; }
  .mark { color: var(--violet); }
  .refused { display: flex; align-items: center; gap: 10px; margin: 0 0 4px; padding: 7px 12px; border-radius: 8px; background: var(--amber-wash); font-size: 13px; }
  .grow { flex: 1; min-width: 0; }
  .prepared .grow { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
