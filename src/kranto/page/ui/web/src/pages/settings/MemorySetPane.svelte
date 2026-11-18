<script lang="ts">
  // Settings › System › Service › Memory: the memory Kranto's service runs under
  // (service.memory), its use now, Save (applied at once) with Undo, and Auto. The setting is
  // Kranto's own systemd drop-in; nobody edits it by hand any more.
  import Detail from "../../ui/Detail.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Kv from "../../ui/Kv.svelte";
  import Pane from "../../ui/Pane.svelte";
  import SaveBar from "../../ui/SaveBar.svelte";
  import SettingField from "../../ui/SettingField.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { drop, read } from "../../lib/reads.svelte";
  import { app } from "../../lib/shell.svelte";
  import { saveUndo } from "../../ui/save";
  import { kindLine, SET_ST } from "../../ui/settings";
  import { memGb, memoryCaps, memoryDefault, SERVICE_SETTINGS, type ServiceMemory } from "./memoryset";

  let { view }: { view: View } = $props();
  const st = $derived.by(() => {
    void view.tick;
    return read<{ memory: ServiceMemory }>(SERVICE_SETTINGS, 15000);
  });
  let val = $state<string | null>(null);
  function save(btn: HTMLElement, to: number | "auto"): void {
    const L = app(), m = st.data?.memory;
    if (!L || !m) return;
    const old = m.setting;
    void saveUndo(btn, {
      write: () => L.api(SERVICE_SETTINGS, { memory: to }), what: () => `Kranto's memory ${to === "auto" ? "auto" : `${to} GB at most`}`, effect: "now",
      undo: () => L.api(SERVICE_SETTINGS, { memory: old }),
      after: () => {
        val = null;
        drop(SERVICE_SETTINGS, true);
      },
    });
  }
</script>

<Detail back={view.back}>
  {#if st.data}
    {@const m = st.data.memory}
    <Pane title="Memory" lede="The memory Kranto's service may use: above the high mark the system slows kranto down; at the most it ends the biggest process in Kranto's group (never the machine's others).">
      {#snippet kind()}<Glyph name={SET_ST.set[0]} colour={SET_ST.set[1]} word={SET_ST.set[2]} />{kindLine("system", "service-memory")}{/snippet}
      {#snippet top()}
        <Kv rows={[["Now", m.used_mb != null ? `${memGb(m.used_mb)} used` : "–"], ["Caps", memoryCaps(m)], ["Setting", m.setting === "auto" ? "Auto" : `${m.setting} GB at most` + (m.by_hand ? " (written by hand)" : "")]]} />
        {#if m.applies}
          <SettingField id="mem-gb" label="At most, in GB" kind="number" value={val ?? (m.setting === "auto" ? String(Math.round((m.default_max_mb || 0) / 512) / 2) : String(m.setting))} input={(t) => (val = t)} min={m.range_gb[0]} max={m.range_gb[1]} step="0.5" dflt={memoryDefault(m)} />
          <SaveBar id="mem-save" effect="now" disabled={val == null} save={(b) => save(b, Number(val))} />
          {#if m.setting !== "auto"}<p class="small"><button type="button" class="linkish" id="mem-auto" onclick={(e) => save(e.currentTarget as HTMLElement, "auto")}>Back to Auto</button>{` (${memoryDefault(m)})`}</p>{/if}
        {:else}
          <p class="muted small" id="mem-not-here">This Kranto is not running as its service, so its memory is set where it was started. {memoryDefault(m)}.</p>
        {/if}
      {/snippet}
    </Pane>
  {:else}
    <div class="pane-in"><p class="empty">{st.error ? `Could not read it: ${st.error}` : "Loading…"}</p></div>
  {/if}
</Detail>
