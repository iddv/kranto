<script lang="ts">
  // The ? sheet, drawn from keys.json: a page's own verbs are greyed where this page has none, a
  // go-to whose page this version lacks says so. Reset layout puts every width back. The marks:
  // what each state glyph means, one glyph per word (UP #10).
  import { KEYMAP, keyLabel, type KeyRow } from "../lib/keys";
  import { layoutReset } from "../lib/shell.svelte";
  import Glyph from "../ui/Glyph.svelte";
  import { SET_LEGEND } from "../ui/settings";

  let { has, hasView, close }: { has: string[]; hasView: (to: string) => boolean; close: () => void } = $props();
  const ROWS = KEYMAP;
  const groups = [...new Set(ROWS.map((m) => m.group))];
  const off = (m: KeyRow): string => m.page && !has.includes(m.keys) ? " (not on this page)" : m.go && m.go !== "topic" && !hasView(m.go) ? " (not in this version yet)" : "";
</script>

<div class="dlg-h" id="dlg-t">Keyboard shortcuts</div>
<div class="dlg-b sheet">
  {#each groups as g (g)}
    <section><h3>{g}</h3><dl>{#each ROWS.filter((m) => m.group === g) as m, j (j)}<dt>{#each m.keys.split(" ") as k, i (i)}{i ? " " : ""}<kbd>{keyLabel(k)}</kbd>{/each}</dt><dd class={off(m) ? "muted" : null}>{m.does + off(m)}</dd>{/each}</dl></section>
  {/each}
  <section id="sheet-marks"><h3>Marks</h3><dl>{#each SET_LEGEND as [st, means] (st[2])}<dt><Glyph name={st[0]} colour={st[1]} word={st[2]} /></dt><dd><strong>{st[2]}</strong>{": " + means}</dd>{/each}</dl></section>
  <p class="muted small">{`Shortcuts never fire while you type in a field. Letters act on pages with rows; a page's own verbs (grades, Later, Pass) on the pages that have them.`}</p>
</div>
<!-- svelte-ignore a11y_autofocus -->
<div class="dlg-f"><button class="btn quiet" id="reset-layout" title="The navigator and the detail pane back to their widths" onclick={() => { layoutReset(); close(); }}>Reset layout</button><button class="btn" autofocus onclick={close}>Close</button></div>
