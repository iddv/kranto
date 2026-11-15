<script lang="ts">
  // A dialog whose body is nodes (the pages that still build one; ui/dialog.svelte.ts's
  // nodeDialog): the frame, the nodes as they were made, the main button's press as given.
  import DialogFrame from "./DialogFrame.svelte";

  let { title, body, okText, onOk, okClass = "", close }: {
    title: string; body: Node[]; okText: string; onOk: (ok: HTMLElement, close: () => void) => unknown; okClass?: string; close: () => void;
  } = $props();
</script>

<DialogFrame {title} {okText} {okClass} {close} ok={(btn) => onOk(btn, close)}>
  <div class="nodes" {@attach (el) => { el.replaceChildren(...body); }}></div>
</DialogFrame>

<style>
  .nodes {
    display: contents;
  }
</style>
