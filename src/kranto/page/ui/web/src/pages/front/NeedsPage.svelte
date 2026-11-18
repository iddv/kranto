<script lang="ts">
  // Needs you (D-1, D-2; #/needs, where #/today and g t land): the one inbox.
  // Every row that waits on you, from every source (an assistant's proposals and prepared items,
  // proposed and failing sources, the review queue, the idea cards waiting, the cubs' tickets,
  // messages, an update), grouped by the verb you will press: Answer · Decide · Approve · Review ·
  // Fix · Update. Each row has one verb, a primary only on its group's first; a press on the row
  // opens its sheet. Mark all seen clears the new marks, never an ask.
  import { markSeen } from "./seen";
  import Needs from "./Needs.svelte";
  import PageTitle from "../../ui/PageTitle.svelte";
  import { needsCount, todayCount, todayRead, type Host } from "./needs";
  import type { HomeRow } from "./home";
  import { cubAsks, waitsWords } from "./needstotal";
  import type { View } from "../../lib/pages.svelte";
  import { plural } from "../../lib/format";
  import { app } from "../../lib/shell.svelte";

  let { view }: { view: View } = $props();
  const H = $derived.by(() => {
    void view.tick;
    return (app()?.host() as Host | null | undefined) || null;
  });
  const c = $derived.by(() => {
    void view.tick;
    return todayRead(H);
  });
  const t = $derived(c?.data || null);
  const n = $derived.by(() => {
    void view.tick;
    return todayCount(H);
  });
  // the cubs' asks (their tickets: Confirm), as the home reads them, under each cub's allowance
  const cubs = $derived.by((): HomeRow[] => {
    void view.tick;
    return cubAsks(H);
  });
  // the count the home and the top bar's chip say too (needstotal.ts)
  const all = $derived.by(() => {
    void view.tick;
    return needsCount(H, cubs.length, cubs.map((r) => r.href));
  });

  $effect(() => {
    void view.tick; // the page's keys are set again on every draw
    app()?.pageKey("⇧a", () => void markSeen(null));
  });
</script>

<div class="wl" data-title="Needs you"><PageTitle title="Needs you" facts={waitsWords(all)} lede="Grouped by what you will do. A row opens it; its button acts from the row."
    primary={H ? { label: "Mark all seen", plain: true, id: "mark-seen", title: "Clear the new marks; nothing that asks you goes (⇧a)", run: (b) => void markSeen(b) } : null} />
  <Needs {view} {t} host={H} {n} loading={!!c && !t} byVerb {cubs} />
  {#if !H}<p class="muted small quiet-topics">Proposed sources, messages and what features ask you come from the server, which is not answering.</p>{/if}
</div>
