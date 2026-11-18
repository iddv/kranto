<script lang="ts">
  // Settings › System › Your grades, the pane: how your grades are used (one
  // formula, no model). The cards' and sources' rows open on their own pages.
  import Detail from "../../ui/Detail.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Pane from "../../ui/Pane.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { ui } from "../../lib/shell.svelte";
  import { kindLine } from "../../ui/settings";

  let { view }: { view: View } = $props();
  const host = $derived(!!ui.facts?.header.host);
</script>

<Detail back={view.back}>
  {#if !host}
    <div class="pane-empty"><p class="empty">Your grades need the server, which is not answering.</p></div>
  {:else}
    <Pane title="How your grades are used" sections={[{ id: "cards", w: "Cards" }, { id: "sources", w: "Sources" }, { id: "settings", w: "Settings" }]}>
      {#snippet kind()}<Glyph name="dot" colour="blue" word="Your grades" />{kindLine("system", "your grades")}{/snippet}
      {#snippet section(s)}
        {#if s.id === "cards"}<p>A ▲ on a card or a piece of evidence lifts the cards like it; a ▼ sinks them. "Like" is read from what Kranto already keeps: the same evidence, the same theme, evidence that reads alike, the same topic when there is nothing else to compare. A card you graded yourself stays first (▲) or last (▼). A grade counts half after 90 days. Every card says why it ranks where it does.</p><p class="muted small mt">No model decides any of it: the same grades give the same order.</p>
        {:else if s.id === "sources"}<p>When 3 or more posts of one source were downvoted in 90 days, and at most a quarter as many upvoted, Needs you asks whether to remove it: Remove or Keep. Nothing is removed without your approval; after Keep, only new downvotes count.</p>
        {:else}<p class="muted small">The numbers are settings under <code>grading:</code> in kranto.yaml (help: Grading).</p>{/if}
      {/snippet}
    </Pane>
  {/if}
</Detail>
