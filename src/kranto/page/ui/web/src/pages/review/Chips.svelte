<script lang="ts">
  // The why chips of a queue item, in the pane under it (the old page's chipRow, which only Review
  // drew): the server's vocabulary for its kind, each with its letter (a–f press it), disabled until
  // the item is graded; + note. A press keeps or takes off its chip (grades.svelte.ts).
  import { app } from "../../lib/shell.svelte";
  import { chipsOf, gkey, gradeOf, noteDialog, toggleChip, type GradeOpts } from "../../ui/grades.svelte";

  let { target, id, o }: { target: string; id: number | string; o: GradeOpts } = $props();
  const cs = $derived(app()?.host() ? chipsOf(target) : []);
  const g = $derived(gradeOf(target, id, null));
</script>

{#if cs.length}<div class="chips why" data-chips={gkey(target, id)} role="group" aria-label="Why"><span class="muted small">Why?</span>{#each cs as c (c.key)}<button type="button" class="chip" data-chip={c.key} disabled={!g} title={g ? null : "Grade first"} aria-pressed={g && (g.reasons || []).includes(c.key) ? "true" : "false"} onclick={() => void toggleChip(target, id, c.key, o)}><kbd>{c.letter}</kbd>{c.label}</button>{/each}<button type="button" class="linkish small" onclick={() => noteDialog(target, id, o)}>+ note</button></div>{/if}
