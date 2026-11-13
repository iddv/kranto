<script lang="ts">
  // Settings › System › Updates, the list: what was checked last with Check for updates, the three settings
  // (the version, automatic updates, the channel), and the recent updates.
  import Glyph from "../../ui/Glyph.svelte";
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import Loading from "../../ui/Loading.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import Row from "../../ui/Row.svelte";
  import RunLine from "../../ui/RunLine.svelte";
  import SetRow from "../../ui/SetRow.svelte";
  import { ago } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { put, read } from "../../lib/reads.svelte";
  import { app, ui } from "../../lib/shell.svelte";
  import { SET_ST } from "../../ui/settings";
  import { answerOf } from "./checkupdates";
  import { badOf, busyOf, CHANNEL_WORDS, latestLine, secs, UPD_API, UPD_BUSY, type UpdateState } from "./updates";

  let { view }: { view: View } = $props();
  // drawn inside Settings › System, its reports start folded to their names and counts
  // (R4: the hundred runs were most of System's words); on its own page, open
  const inSystem = $derived(view.w.r.path[1] === "system");
  const host = $derived(!!ui.facts?.header.host);
  const c = $derived.by(() => {
    void view.tick;
    return host ? read<UpdateState>(UPD_API, 30000) : null;
  });
  const d = $derived(c?.data || null);

  function check(btn: HTMLElement): void {
    const L = app();
    if (!L) return;
    void L.act(btn, async () => {
      const r = (await L.api(UPD_API + "/check", {})) as UpdateState & { installed: { version: string } };
      put(UPD_API, r);
      await L.loadHost();
      return r;
    }, (x) => {
      const a = answerOf(x as UpdateState);
      L.say(a.text + (a.next && !a.next.restart ? ` · ${a.next.word}` : ""), a.tone === "red" ? "red" : undefined);
    });
  }
</script>

{#if !host}
  <List title="Updates" crumb="Settings"><NeedHost what="Updates" /></List>
{:else if !d}
  <List title="Updates" crumb="Settings"><Loading error={c?.error} /></List>
{:else}
  {@const a = d.apply || {}}
  {@const inst = d.installed || { version: "", channel: "" }}
  {@const s = d.settings}
  {@const hist = d.history || []}
  <List title="Updates" crumb="Settings">
    {#snippet tools()}<span class="tbn"><span>{latestLine(d)}</span><span class="grow"></span><button class="btn sm" id="upd-check" onclick={(e) => check(e.currentTarget)}>Check for updates</button></span>{/snippet}
    <!-- the check running now, or failing run after run, with what to do -->
    <RunLine subject="kind:update" tick={view.tick} id="upd-run-line" />
    <Group id="u-set" title="Updates" count="3" kind="sets"><!-- 17 (Gemini 17): it read "Settings 3" -->
      {#snippet right()}<span class="muted">{`Kranto ${inst.version}`}</span>{/snippet}
      <SetRow key="version" word="Version" state={badOf(a) ? ["warn", "red", "Rolled back"] : d.available ? SET_ST.warn : d.ok ? SET_ST.ok : SET_ST.warn}
        summary={[`${inst.version} (${inst.channel})`, latestLine(d), busyOf(a) ? "updating: " + UPD_BUSY[a.state || ""] : badOf(a) ? `the update to ${a.to} ${(a.state || "").replace("_", " ")}` : null].filter(Boolean).join(" · ")} />
      <SetRow key="auto" word="Automatic updates" summary={s.auto === "idle" ? `when idle, ${s.quiet_window}` : "off: you click Restart to update"} state={s.auto === "idle" ? SET_ST.ok : SET_ST.dflt} />
      <SetRow key="channel" word="Channel" summary={CHANNEL_WORDS[s.channel] || s.channel} state={s.channel === "stable" ? SET_ST.dflt : SET_ST.set} />
    </Group>
    <Group id="u-hist" fold="system:u-hist" start={inSystem} title="Recent updates" count={String(hist.length)} kind="sets">
      {#each hist as x, i (i)}<Row sel={"ehist:" + i} title={`${x.from} → ${x.to}: ${String(x.state).replace("_", " ")}`} meta={x.reason || x.detail || null} age={x.finished ? ago(secs(x.finished)) : null}>{#snippet st()}{#if x.state === "done"}<Glyph name="check" colour="green" word="Done" />{:else}<Glyph name="warn" colour={x.state === "rolled_back" ? "amber" : "red"} word={x.state} />{/if}{/snippet}</Row>{/each}
      {#snippet foot()}{#if !hist.length}<p class="more">No update yet.</p>{/if}{/snippet}
    </Group>
  </List>
{/if}
