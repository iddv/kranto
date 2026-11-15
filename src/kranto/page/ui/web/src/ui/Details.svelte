<script lang="ts">
  // The Details drawer: the record behind a row, the one thing or a dialog, at
  // the right (420 px; the whole width on a phone). Its title, short groups of facts (What · Who,
  // when · The rules it meets · Evidence · The run · Log), the page it opens on, and a last line
  // that names the console's call for the same record (kranto_details): the drawer and the tool
  // read one function (src/kranto/page/ui/details.py), so they never disagree. No word budget: it is the
  // record for the owner who asks; its words stay plain (keys only as code).
  import { read } from "../lib/reads.svelte";
  import { landOf } from "../lib/app/route";
  import { closeDetails, DETAILS, detailsPath, type DetailsRecord } from "./details.svelte";

  /** whether a record's page is the page open now, where it lands (#/ideas/card:1 lands on
   * #/ideas?sel=i1: its Open its page closed the drawer and came back to the same card) */
  function here(page: string): boolean {
    const now = location.hash;
    const at = (() => { try { return landOf(page); } catch { return page; } })();
    return [page, at].some((p) => now === p || now.startsWith(p + "?") || now.startsWith(p + "/"));
  }

  const r = $derived(DETAILS.sel ? read<DetailsRecord>(detailsPath(DETAILS.sel), 15000) : null);
  const d = $derived(r?.data || null);
  function key(e: KeyboardEvent): void {
    if (e.key === "Escape" && DETAILS.sel) {
      e.stopPropagation();
      closeDetails();
    }
  }
</script>

<svelte:window onkeydown={key} />

{#if DETAILS.sel}
  <aside class="details" id="details" aria-labelledby="details-h" data-sel={DETAILS.sel}>
    <div class="dh"><h2 id="details-h">{d ? d.title : "Details"}</h2><button type="button" class="btn sm quiet" id="details-close" aria-label="Close Details" onclick={closeDetails}>✕</button></div>
    <div class="db">
      {#if !d}<p class="muted">{r?.error ? `Could not read it: ${r.error}` : "Reading…"}</p>
      {:else}
        {#each d.groups as g (g.h)}
          <h3>{g.h}</h3>
          <dl>{#each g.rows as [k, v], i (k + i)}<dt>{k}</dt><dd>{#if v.startsWith("#/")}<a href={v} onclick={closeDetails}>{v}</a>{:else if /^https?:\/\//.test(v)}<a href={v} target="_blank" rel="noopener noreferrer">{v}</a>{:else}{v}{/if}</dd>{/each}</dl>
        {/each}
        <!-- its page, unless it is the page open now (11, Codex 5: it reopened the same sheet) -->
        {#if d.page && !here(d.page)}<p class="page"><a href={d.page} onclick={closeDetails}>Open its page ›</a></p>{/if}
        <p class="tools">The console reads the same record: <code>{d.tool}</code></p>
      {/if}
    </div>
  </aside>
{/if}

<style>
  .details { position: fixed; top: 40px; right: 0; bottom: 24px; width: min(420px, 100%); z-index: 60; display: flex; flex-direction: column;
    background: var(--box); border-left: 1px solid var(--border); }
  .dh { display: flex; align-items: center; gap: 10px; padding: 10px 16px; border-bottom: 1px solid var(--border-2); }
  .dh h2 { flex: 1; min-width: 0; font-size: 14px; font-weight: 600; margin: 0; overflow-wrap: anywhere; }
  .db { flex: 1; min-height: 0; overflow: auto; padding: 12px 16px 24px; font-size: 12.5px; }
  h3 { font-size: 12px; font-weight: 600; color: var(--muted); margin: 14px 0 4px; }
  h3:first-child { margin-top: 0; }
  /* a label as wide as it needs, up to a third: a claim's long source name never squeezes it */
  dl { display: grid; grid-template-columns: minmax(0, max-content) minmax(0, 1fr); gap: 2px 12px; margin: 0; }
  dt { color: var(--muted); max-width: 9.5em; overflow-wrap: anywhere; }
  dd { margin: 0; overflow-wrap: anywhere; }
  .page { margin-top: 14px; }
  .tools { margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--border-2); color: var(--muted); }
  .tools code { font-size: 11.5px; }
</style>
