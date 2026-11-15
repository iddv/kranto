<script lang="ts">
  // Settings › System › Activity, the sheet: the days the runs' marks are kept and the most kept,
  // Save with Undo (the eight pages' way,).
  import Detail from "../../ui/Detail.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Pane from "../../ui/Pane.svelte";
  import SaveBar from "../../ui/SaveBar.svelte";
  import SettingField from "../../ui/SettingField.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { drop, read } from "../../lib/reads.svelte";
  import { app } from "../../lib/shell.svelte";
  import { saveUndo } from "../../ui/save";
  import { kindLine, SET_ST } from "../../ui/settings";
  import { ACTIVITY_SETTINGS, activityWords, type ActivitySettings } from "./activityset";

  let { view }: { view: View } = $props();
  const st = $derived.by(() => {
    void view.tick;
    return read<ActivitySettings>(ACTIVITY_SETTINGS, 60000);
  });
  let days = $state<string | null>(null);
  let rows = $state<string | null>(null);
  function save(btn: HTMLElement): void {
    const L = app(), d = st.data;
    if (!L || !d) return;
    const body = { keep_days: Number(days ?? d.keep_days), max_rows: Number(rows ?? d.max_rows) };
    const old = { keep_days: d.keep_days, max_rows: d.max_rows };
    void saveUndo(btn, {
      write: () => L.api(ACTIVITY_SETTINGS, body), what: () => `runs' marks kept ${activityWords(body)}`, effect: "run",
      undo: () => L.api(ACTIVITY_SETTINGS, old),
      after: () => {
        days = null;
        rows = null;
        drop(ACTIVITY_SETTINGS, true);
      },
    });
  }
</script>

<Detail back={view.back}>
  {#if st.data}
    {@const d = st.data}
    <Pane title="Runs' marks are kept" lede="What Kranto is doing keeps a mark for each run and step; the oldest go first, at compaction. The runs themselves are kept as before.">
      {#snippet kind()}<Glyph name={SET_ST.set[0]} colour={SET_ST.set[1]} word={SET_ST.set[2]} />{kindLine("system", "activity")}{/snippet}
      {#snippet top()}
        <SettingField id="act-keep-days" label="Days kept" kind="number" value={days ?? String(d.keep_days)} input={(t) => (days = t)} min={1} max={365} dflt="30" />
        <SettingField id="act-max-rows" label="Marks at most" kind="number" value={rows ?? String(d.max_rows)} input={(t) => (rows = t)} min={1000} max={1000000} step="1000" dflt="20000" now={`${d.rows.toLocaleString("en-GB")} now`} />
        <SaveBar id="act-save" effect="run" disabled={days == null && rows == null} save={(b) => save(b)} />
      {/snippet}
    </Pane>
  {:else}
    <div class="pane-in"><p class="empty">{st.error ? `Could not read it: ${st.error}` : "Loading…"}</p></div>
  {/if}
</Detail>
