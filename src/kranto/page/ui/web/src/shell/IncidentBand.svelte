<script lang="ts">
  // A blocking incident: a model key refused stops reading, idea cards and the cubs'
  // model calls at once, so it is said above everything on the home and at the head of Needs you,
  // in every layout and on the phone, in red, with the one press that fixes it (Renew the key).
  // It goes when it is fixed (a later good call to the provider, a passing key test), and the owner
  // may put it away: Dismiss, which the server keeps until it happens again (#488; never a ✕ that
  // does nothing). Drawn once a page: Needs you draws none, its Fix row says it. Drawn from
  // api/activity's incidents (the server's activity/incidents.py says the words): Kranto's own only
  // (lib/activity.ts bandOf); no feature or cub raises it, theirs are Needs you rows. In about
  // fifteen words: its title and what stopped since when (bandWords); the
  // long form is its tooltip, kranto_incidents' and the trace's.
  import type { ActivityIncident } from "../api/types.gen";
  import { bandWords, isBand } from "../lib/activity";
  import { dismissIncident } from "./incidents";

  let { incidents }: { incidents: ActivityIncident[] } = $props();
  // enforced here too: whatever a caller passes, a feature's incident never draws the band
  const own = $derived(incidents.filter(isBand));
</script>

{#if own.length}
<section class="incident" id="incident-band" role="alert" aria-label="What stops Kranto">
  {#each own as i (i.id)}
    <div class="inc" class:amber={i.tone === "amber"} data-incident={i.id}>
      <div class="body" title={i.words}><b class="title">{i.title}</b><span class="words">{bandWords(i)}</span></div>
      <a class="btn sm primary" href={i.href} title={i.verb}>{i.verb}</a>
      {#if i.dismiss}<button type="button" class="btn sm quiet" data-dismiss={i.id} title="Put it away until it happens again" onclick={(e) => dismissIncident(i.id, e.currentTarget)}>Dismiss</button>{/if}
    </div>
  {/each}
</section>
{/if}

<style>
  .incident { display: flex; flex-direction: column; gap: 6px; margin: 0 0 14px; position: relative; z-index: 6; }
  .inc { display: flex; align-items: center; gap: 12px; padding: 10px 14px; border: 1px solid var(--red); border-left-width: 4px; border-radius: 8px; background: var(--red-wash); color: var(--text); }
  .inc.amber { border-color: var(--amber); background: var(--amber-wash); }
  .body { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; }
  .title { font-weight: 650; }
  .words { font-size: 13px; }
  @media (max-width: 700px) {
    .inc { flex-wrap: wrap; }
    .inc .btn { min-height: 44px; }
    /* the console's sheet covers the lower 70% of a phone (Console.svelte): with it open, the band
       rides just above the sheet's edge, over the page, so the console never hides it */
    :global(body.con-open:not(.con-full)) .incident { position: fixed; left: 8px; right: 8px; bottom: calc(70vh + 6px); z-index: 31; margin: 0; }
    :global(body.con-open:not(.con-full)) .inc { padding: 8px 10px; gap: 8px; }
    :global(body.con-open:not(.con-full)) .words { display: none; }
  }
</style>
