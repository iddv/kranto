<script lang="ts">
  // The line about a press (the flash: 8 s, or while its Undo is offered; a red one offers Tell
  // us). a line about a press made in a sheet is drawn in that sheet, never
  // half under it; with no sheet open ListHead draws it in the list's head, as before; while one
  // is, App's #detail draws it here.
  import Icon from "./Icon.svelte";
  import { ui } from "../lib/shell.svelte";
  import { tellUs } from "../ui/sendFeedback";

  const f = $derived(ui.facts?.head?.flash || null);
</script>

{#if f && ui.sheet}<div class={"flash in-sheet " + f.kind} role="status" id="sheet-flash"><Icon name={f.kind === "red" ? "x" : f.kind === "amber" ? "warn" : "check"} /><div class="grow">{f.text}{#if f.undo}{@const u = f.undo}{" · "}<button type="button" class="linkish" id="undo" onclick={(e) => u.run(e.currentTarget)}>Undo</button>{/if}{#if f.kind === "red"}{" · "}<button type="button" class="linkish" id="flash-tell" title="Send feedback about this, with these words in it" onclick={() => tellUs(f.text)}>Tell us</button>{/if}</div></div>{/if}

<style>
  .in-sheet { margin: 0 0 8px; }
</style>
