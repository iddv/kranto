<script lang="ts">
  // #dlg: the dialog openDialog() shows, drawn here until it closes (ui/dialog.svelte.ts).
  import { closeDialog, closed, dlg, moved } from "./dialog.svelte";
</script>

<svelte:window onhashchange={moved} />

<dialog id="dlg" aria-labelledby="dlg-t" class:wide={!!dlg.now?.wide} onclose={closed}>
  {#if dlg.now}
    {@const C = dlg.now.comp}
    {#key dlg.now.n}<C {...dlg.now.props} close={closeDialog} />{/key}
  {/if}
</dialog>
