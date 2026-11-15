<script lang="ts">
  // Settings › Privacy & access, the list: usage reports (the mode, what is sent, today's
  // report, the notice) and every report sent so far, each opening its exact bytes in the pane.
  import Glyph from "../../ui/Glyph.svelte";
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import Loading from "../../ui/Loading.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import Row from "../../ui/Row.svelte";
  import SetRow from "../../ui/SetRow.svelte";
  import { ago, dt } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { ui } from "../../lib/shell.svelte";
  import { SET_ST } from "../../ui/settings";
  import { errorsLine, MODE_WORDS, PRIVACY_API, sendingLine, type Privacy } from "./privacy";

  let { view }: { view: View } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const c = $derived.by(() => {
    void view.tick;
    return host ? read<Privacy>(PRIVACY_API, 30000) : null;
  });
  const d = $derived(c?.data || null);
</script>

{#if !host}
  <List title="Privacy" crumb="Settings"><NeedHost what="Privacy" /></List>
{:else if !d}
  <List title="Privacy" crumb="Settings"><Loading error={c?.error} /></List>
{:else}
  <List title="Privacy" crumb="Settings">
    <Group id="p-set" title="Usage reports" count="3" kind="sets">
      <SetRow key="mode" word="Usage reports" summary={`${MODE_WORDS[d.mode]}: ${d.meaning}` + (d.answered ? "" : " (not answered)")} state={d.mode === "off" || d.mode === "local" ? SET_ST.dflt : SET_ST.set} />
      <SetRow key="today" word="Today's report" summary={`${d.bytes_today} bytes of counters on this machine · ${sendingLine(d)}`} state={SET_ST.dflt} />
      <SetRow key="notice" word="What Kranto sends" summary="The notice and every field a report or an error report may hold" state={SET_ST.dflt} />
    </Group>
    <Group id="p-errors" title="Error reports" count={String((d.error_batches || []).length)} kind="sets">
      <SetRow key="errors" word="Waiting to be sent" summary={errorsLine(d)} state={SET_ST.dflt} />
      {#each d.error_batches || [] as x (x.id)}<Row sel={"esent:" + x.id} title={`${x.at}: ${x.reports} ${x.reports === 1 ? "error report" : "error reports"}, ${x.bytes} bytes`} meta={`HTTP ${x.status} · ${x.tier}`} age={ago(dt(x.at))} stw={x.status >= 200 && x.status < 300 ? SET_ST.ok : SET_ST.warn}>{#snippet st()}<Glyph name={x.status >= 200 && x.status < 300 ? "check" : "warn"} colour={x.status >= 200 && x.status < 300 ? "green" : "amber"} word={x.status >= 200 && x.status < 300 ? "Ok" : "Needs you"} />{/snippet}</Row>{/each}
    </Group>
    <Group id="p-sent" title="Sent from this install" count={String(d.sent.length)} kind="sets">
      {#each d.sent as x (x.day)}<Row sel={"esent:" + x.day} title={`${x.day}: ${x.bytes} bytes (${x.gzip_bytes} gzipped)`} meta={`HTTP ${x.status} · ${x.tier}`} age={ago(dt(x.at))} stw={x.status >= 200 && x.status < 300 ? SET_ST.ok : SET_ST.warn}>{#snippet st()}<Glyph name={x.status >= 200 && x.status < 300 ? "check" : "warn"} colour={x.status >= 200 && x.status < 300 ? "green" : "amber"} word={x.status >= 200 && x.status < 300 ? "Ok" : "Needs you"} />{/snippet}</Row>{/each}
      {#snippet foot()}{#if !d.sent.length}<p class="more">Nothing has been sent from this install.</p>{/if}{/snippet}
    </Group>
  </List>
{/if}
