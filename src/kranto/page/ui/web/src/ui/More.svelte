<script lang="ts">
  // ⋯: a pane's verbs past its primary row, in the one menu (ui/popover.ts:
  // arrow keys move, enter runs, esc closes and the focus comes back; a verb not on now is
  // greyed with its why). The . key presses it on a pane (#dscroll .dh .btn.more). items: each
  // verb as the menu's item, the same verb its key and ⌘K run.
  import type { MenuItem } from "../lib/app";
  import { app } from "../lib/shell.svelte";

  let { items }: { items: MenuItem[] } = $props();
</script>

<button type="button" class="btn sm more" aria-haspopup="menu" aria-label="More actions" title="More actions (.)" onclick={(e) => app()?.menu(e.currentTarget, items)}>⋯</button>
