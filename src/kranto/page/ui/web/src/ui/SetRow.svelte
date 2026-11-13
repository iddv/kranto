<script lang="ts">
  // A setting group as one row (WORKSPACE.md 1.5, 2.12): its state, its name and its current
  // value in one line, the state's word first (UP #10); its form is in the pane when it is selected (sel=e<key>).
  import Glyph from "./Glyph.svelte";
  import Row from "./Row.svelte";
  import { SET_ST, type St } from "./settings";

  let { key, word, summary = null, state = SET_ST.set }: { key: string; word: string; summary?: string | null; state?: St } = $props();
</script>

<Row sel={"e" + key} title={word} meta={summary || null} stw={state}>{#snippet st()}<Glyph name={state[0]} colour={state[1]} word={state[2]} />{/snippet}</Row>
