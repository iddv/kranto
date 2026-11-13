<script lang="ts">
  // The preview's line on the phone: there the status bar gives way to the doors, so
  // this strip above them says what the bar's first cell says wide: "Preview: a copy of your data
  // from 11 November. Nothing is sent." Drawn only on the preview (the server's /api/status
  // `preview`); hidden wide, where StatusBar's #bar-preview says it (base.css).
  import { ui } from "../lib/shell.svelte";

  const line = $derived(ui.facts?.bar?.preview || null);
</script>

{#if line}<div id="preview-strip" role="status">{line}</div>{/if}
