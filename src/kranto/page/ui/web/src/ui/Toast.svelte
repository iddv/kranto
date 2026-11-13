<script lang="ts">
  // The toast at the foot (toast.svelte.ts): its words, Undo while it is offered, Tell us on a red
  // one (Feedback, prefilled with its words), and ✕.
  import { TOAST } from "./toast.svelte";
  import { tellUs } from "./sendFeedback";
</script>

{#if TOAST.shown}<div id="toast" class={"toast" + (TOAST.kind ? " " + TOAST.kind : "")} role="status" aria-live="polite" hidden={TOAST.hidden}><span class="grow">{TOAST.text}</span>{#if TOAST.undo}{@const undo = TOAST.undo}<button type="button" class="linkish" id="toast-undo" onclick={() => { TOAST.hidden = true; undo(); }}>Undo</button>{/if}{#if TOAST.kind === "red"}{@const said = TOAST.text}<button type="button" class="linkish" id="toast-tell" title="Send feedback about this, with these words in it" onclick={() => { TOAST.hidden = true; tellUs(said); }}>Tell us</button>{/if}<button type="button" class="linkish x" aria-label="Dismiss" onclick={() => { TOAST.hidden = true; }}>✕</button></div>{/if}
