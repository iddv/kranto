<script lang="ts">
  // The why chips of one grade, in the popover that whyPop() opens (after a grade, and on why ▾):
  // The server's chips, each with its letter (a–f press it), pressed while the grade carries it; a
  // press keeps or takes off its chip. + note asks for a few words kept with the grade.
  import { chipsOf, gkey, gradeOf, noteDialog, toggleChip, WHYCUR, type GradeOpts } from "./grades.svelte";
  import { app } from "../lib/shell.svelte";

  let { target, id, o = {} }: { target: string; id: number | string; o?: GradeOpts } = $props();
  const k = $derived(gkey(target, id));
  const g = $derived(gradeOf(target, id, WHYCUR[k]));
  const cur = () => gradeOf(target, id, WHYCUR[k]);
  function note(): void {
    app()?.closePop(false);
    noteDialog(target, id, { ...o, current: cur() });
  }
</script>

<div class="pop-h">Why?</div><div class="chips" data-chips={k}>{#each chipsOf(target) as c (c.key)}<button type="button" class="chip" data-chip={c.key} aria-pressed={(g?.reasons || []).includes(c.key) ? "true" : "false"} onclick={() => void toggleChip(target, id, c.key, { ...o, current: cur() })}><kbd>{c.letter}</kbd>{" " + c.label}</button>{/each}</div><button type="button" class="linkish small" onclick={note}>+ note</button>
