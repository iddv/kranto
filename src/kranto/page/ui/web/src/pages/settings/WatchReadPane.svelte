<script lang="ts">
  // Settings › Watching › Reading, a row's pane: how often sources are read and whether deep
  // dives run, each a field and Save (UP #3: once set by hand only), written by the server's
  // POST /api/settings/reading. The toast says when it takes effect and offers Undo.
  import Detail from "../../ui/Detail.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Loading from "../../ui/Loading.svelte";
  import Pane from "../../ui/Pane.svelte";
  import SaveBar from "../../ui/SaveBar.svelte";
  import SettingField from "../../ui/SettingField.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { drop, put, read } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { app } from "../../lib/shell.svelte";
  import { saveUndo } from "../../ui/save";
  import { groupOf, kindLine, SET_ST } from "../../ui/settings";
  import { SETUP_API } from "./keys.svelte";
  import { READING, type Reading } from "./spend.svelte";

  let { view }: { view: View } = $props();
  const id = $derived(groupOf(view.w));
  const r = $derived.by(() => {
    void view.tick;
    return read<Reading>(READING, 30000);
  });
  let hours = $state<string | null>(null);
  let dive = $state<string | null>(null);

  /* one field through the server's writer; Undo writes the value it replaced */
  function save(btn: HTMLElement, body: Record<string, unknown>, before: Record<string, unknown>, what: string, effect: "restart" | "run"): void {
    const L = app();
    if (!L) return;
    const write = async (b: Record<string, unknown>) => {
      const x = (await L.api(READING, b)) as Reading;
      put(READING, x);
      drop(SETUP_API);
      return x;
    };
    void saveUndo(btn, { write: () => write(body), undo: () => write(before), what: () => what, effect,
      after: () => {
        hours = null;
        dive = null;
      } });
  }
</script>

<Detail back={view.back}>
  {#if !r.data}
    <div class="pane-in"><Loading error={r.error} what="how sources are read" /></div>
  {:else if id === "read:every"}
    {@const d = r.data}
    {@const cur = hours ?? String(d.every_hours)}
    {@const st = d.every_hours !== 3 ? SET_ST.set : SET_ST.dflt}
    <Pane title="How often sources are read" lede="Every source of an active topic is read on this cadence; a read that finds nothing new costs nothing." right={`every ${d.every_hours} h`} sections={[{ id: "value", w: "Every" }]}>
      {#snippet kind()}<Glyph name={st[0]} colour={st[1]} word={st[2]} />{kindLine("watching", "reading")}{/snippet}
      {#snippet section()}
        <SettingField id="read-every" label="Hours between reads" kind="number" value={cur} input={(t) => (hours = t)} dflt="3" min={0.5} max={168} step="0.5" />
        <SaveBar id="save-read-every" effect="restart" disabled={hours == null}
          save={(b) => save(b, { every_hours: Number(cur) }, { every_hours: d.every_hours }, `sources are read every ${Number(cur)} h`, "restart")} />
        <p class="muted small mt"><code>ingest.every_hours</code> in your settings ({d.config}). The top bar says when the next read is.</p>
      {/snippet}
    </Pane>
  {:else if id === "read:dive"}
    {@const d = r.data}
    {@const on = d.deep_dive.enabled}
    {@const cur = dive ?? String(on)}
    <Pane title="Deep dives" lede="Reading what is one step away from a strong observation: its discussion, its links." right={on ? "on" : "off"} sections={[{ id: "value", w: "On or off" }]}>
      {#snippet kind()}<Glyph name={(on ? SET_ST.ok : SET_ST.off)[0]} colour={(on ? SET_ST.ok : SET_ST.off)[1]} word={(on ? SET_ST.ok : SET_ST.off)[2]} />{kindLine("watching", "reading")}{/snippet}
      {#snippet section()}
        <SettingField id="read-dive" label="Deep dives" kind="bool" value={cur} input={(t) => (dive = t)} dflt="false" />
        <SaveBar id="save-read-dive" effect="run" disabled={dive == null}
          save={(b) => save(b, { deep_dive_enabled: cur === "true" }, { deep_dive_enabled: on }, `deep dives are ${cur === "true" ? "on" : "off"}`, "run")} />
        <p class="small mt"><code>deep_dive.enabled</code> in your settings. Their cap: <a href={href("settings/spend", { sel: "ecap:dive" })}>Settings › Spend › Deep dives a day</a>.</p>
      {/snippet}
    </Pane>
  {:else}
    <div class="pane-empty"><p class="empty">No such setting.</p></div>
  {/if}
</Detail>
