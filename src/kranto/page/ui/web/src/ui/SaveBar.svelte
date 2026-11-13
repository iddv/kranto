<script lang="ts">
  // One Save row for every settings form: Save, Back to the default where the
  // setting has one, and the sentence that says when the change takes effect (words.ts EFFECT).
  // The press is the page's own (ui/save.ts saveUndo: the toast with Undo).
  import { EFFECT, type Effect } from "../lib/words";

  let { id, effect, save, dflt = null, disabled = false, label = "Save", note = null, dfltTitle = null, saveAct = "save", dfltAct = "default" }: {
    id: string; effect: Effect; save: (btn: HTMLButtonElement) => void; dflt?: ((btn: HTMLButtonElement) => void) | null;
    disabled?: boolean; label?: string; note?: string | null; dfltTitle?: string | null; saveAct?: string; dfltAct?: string;
  } = $props();
</script>

<div class="inline savebar"><button class="btn primary" {id} data-act={saveAct} {disabled} onclick={(e) => save(e.currentTarget)}>{label}</button>{#if dflt}<button class="btn" data-act={dfltAct} title={dfltTitle} onclick={(e) => dflt(e.currentTarget)}>Back to the default</button>{/if}<span class="muted small">{(note ? note + " " : "") + EFFECT[effect]}</span></div>
