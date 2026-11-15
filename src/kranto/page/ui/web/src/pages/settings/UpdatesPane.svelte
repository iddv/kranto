<script lang="ts">
  // Settings › System › Updates, the pane: the version, what is on offer, the state of an update and its
  // log, Restart to update (Cancel while it waits; Roll back),
  // what's new; automatic updates and the channel, each saved with its own Save into the
  // update: section of kranto.yaml. What is typed is kept until Save, across redraws.
  import Detail from "../../ui/Detail.svelte";
  import FLabel from "../../ui/FLabel.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Pane, { type Sec } from "../../ui/Pane.svelte";
  import Tip from "../../ui/Tip.svelte";
  import { plural, rel } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { put, read } from "../../lib/reads.svelte";
  import { app, ui } from "../../lib/shell.svelte";
  import { groupOf, kindLine, SET_ST, type St } from "../../ui/settings";
  import { AUTO_WORDS, badOf, buildLine, busyOf, CHANNEL_HINT, CHANNEL_WORDS, channelReadback, latestLine, secs, UPD_API, UPD_BUSY, type UpdateState } from "./updates";
  import SaveBar from "../../ui/SaveBar.svelte";
  import VersionCheck from "./VersionCheck.svelte";
  import { saveUndo } from "../../ui/save";

  let { view }: { view: View } = $props();
  const id = $derived(groupOf(view.w) || "");
  const c = $derived.by(() => {
    void view.tick;
    return ui.facts?.header.host ? read<UpdateState>(UPD_API, 30000) : null; // the server's alone
  });
  const d = $derived(c?.data || null);
  // what is typed, by setting, kept until Save
  let form = $state<Record<string, string>>({});
  const val = (k: "auto" | "quiet_window" | "channel"): string => (k in form ? (form[k] as string) : d ? d.settings[k] : "");

  function save(btn: HTMLElement, keys: ("auto" | "quiet_window" | "channel")[]): void {
    const L = app();
    if (!L || !d) return;
    const body: Record<string, string> = {}, before: Record<string, string> = {};
    for (const k of keys) {
      body[k] = val(k);
      before[k] = d.settings[k];
    }
    const write = async (b: Record<string, string>) => {
      const r = (await L.api(UPD_API + "/settings", b)) as UpdateState;
      put(UPD_API, r);
      await L.loadHost();
      return r;
    };
    void saveUndo(btn, {
      write: () => write(body),
      undo: () => write(before),
      what: (x) => {
        const r = x as UpdateState;
        return `automatic updates ${r.settings.auto === "idle" ? "when idle, " + r.settings.quiet_window : "off"}; ${channelReadback(r.settings.channel, r.installed)}`;
      },
      effect: "check",
      after: () => {
        for (const k of keys) delete form[k];
      },
    });
  }
  const homeSt = (x: UpdateState): St => (badOf(x.apply) ? ["warn", "red", "Rolled back"] : x.available ? SET_ST.warn : SET_ST.ok);
  function stateLine(x: UpdateState): string {
    const a = x.apply || {};
    if (busyOf(a)) return `Updating to ${a.to}: ${UPD_BUSY[a.state || ""]}${a.detail ? " (" + a.detail + ")" : ""}.`;
    if (badOf(a)) return `The update to ${a.to} ${(a.state || "").replace("_", " ")}: ${a.reason || "see the log"}.` + (a.state === "failed" && a.detail ? " " + a.detail : "");
    return a.state === "done" ? `Updated to ${a.to} ${a.finished ? rel(secs(a.finished)) : ""}.` : "No update running.";
  }
  const homeSecs = (x: UpdateState): Sec[] =>
    [{ id: "state", w: "State" }, ...(x.latest?.version ? [{ id: "new", w: `What's new in ${x.latest.version}`, n: (x.latest.notes || []).length || null }] : [])];
</script>

<Detail back={view.back}>
  {#if !d}
    <div class="pane-in"><p class="empty">{c?.error ? `Could not read the server: ${c.error}` : "Loading…"}</p></div>
  {:else if !id || id === "version" || id.startsWith("hist:")}
    {@const a = d.apply || {}}
    {@const inst = d.installed}
    {@const busy = d.busy || {}}
    {@const st = homeSt(d)}
    <Pane title={d.available ? `Update ${inst.version} → ${d.available}` : `Kranto ${inst.version}`} right={inst.channel} sections={homeSecs(d)}>
      {#snippet kind()}<Glyph name={st[0]} colour={st[1]} word={st[2]} />{kindLine("system", "updates")}{/snippet}
      {#snippet lede()}{buildLine(inst.version) ? buildLine(inst.version) + " · " : ""}{latestLine(d)}<Tip id="updates" about="updates" />{/snippet}
      {#snippet acts()}
        {#if busyOf(a)}
          {#if a.state === "draining" && d.can_apply}<button class="btn sm" id="upd-cancel" onclick={(e) => app()?.updCancel(e.currentTarget)}>Cancel</button>{/if}
        {:else}
          <!-- the version, pressable here too: the New layout's System page opens this sheet from its Version row -->
          {#if !d.available}<VersionCheck id="upd-pane-version" />{/if}
          {#if d.available}{#if d.can_apply}<button class="btn sm primary" id="upd-apply" onclick={(e) => app()?.updApply(e.currentTarget)}>Restart to update</button>{:else}<a class="btn sm primary" href="#/settings/updates" title="This Kranto updates from the command line: kranto update">How to update</a>{/if}{/if}{#if d.can_apply && d.previous?.version}{@const to = d.previous.version}<button class="btn sm quiet" id="upd-rollback" onclick={(e) => app()?.updRollback(e.currentTarget, to)}>{`Roll back to ${to}`}</button>{/if}
        {/if}
      {/snippet}
      {#snippet section(s)}
        {#if s.id === "state"}<p class="small">{stateLine(d)}</p>{#if busy.job}<p class="muted small">{`the server is running ${busy.job}: Restart to update waits for it.`}</p>{/if}{#if a.log}<details class="fold"><summary class="small">Log</summary><p class="muted small"><code>{a.log}</code>{" (also journalctl --user -u " + (a.unit || "kranto-update") + ")"}</p></details>{/if}{#if !d.can_apply}<p class="muted small"><code>kranto update</code><Tip id={{ text: "This page cannot apply an update here: run kranto update on the machine Kranto runs on." }} about="updating" /></p>{/if}
        {:else}<ul class="lst pl notes">{#each d.latest?.notes || [] as n, i (i)}<li class="row">{n.replace(/^- /, "")}</li>{/each}</ul>{#if d.latest?.notes_url}<p class="small"><a href={d.latest.notes_url} rel="noopener noreferrer" target="_blank">All the notes ↗</a></p>{/if}{/if}
      {/snippet}
    </Pane>
  {:else if id === "auto"}
    {@const st = d.settings.auto === "idle" ? SET_ST.ok : SET_ST.dflt}
    <Pane title="Automatic updates" lede="Off by default: an update restarts Kranto, so you click Restart to update. When idle, a stable release updates by itself at night; never a nightly release." sections={[{ id: "form", w: "Settings" }]}>
      {#snippet kind()}<Glyph name={st[0]} colour={st[1]} word={st[2]} />{kindLine("system", "automatic updates")}{/snippet}
      {#snippet section()}<div class="field" role="radiogroup" aria-label="Automatic updates">{#each ["off", "idle"] as v (v)}<label class="radio"><input type="radio" name="upd-auto" id={"upd-auto-" + v} value={v} checked={val("auto") === v} onchange={() => (form.auto = v)} />{" " + AUTO_WORDS[v]}</label>{/each}</div><div class="field"><FLabel forId="upd-window" text="Quiet window (this machine's time)" hint="When idle: only inside this window, only when no job runs, never a nightly release, at most once a day, and never a version that was rolled back this week." /><input id="upd-window" value={val("quiet_window")} placeholder="03:00-06:00" style="width:9em" oninput={(e) => (form.quiet_window = e.currentTarget.value)} /></div><SaveBar id="save-update" effect="check" save={(b) => save(b, ["auto", "quiet_window"])} />{/snippet}
    </Pane>
  {:else if id === "channel"}
    {@const st = d.settings.channel === "stable" ? SET_ST.dflt : SET_ST.set}
    <Pane title="Channel" lede="Which line of releases you are on: stable or nightly." sections={[{ id: "form", w: "Settings" }]}>
      {#snippet kind()}<Glyph name={st[0]} colour={st[1]} word={st[2]} />{kindLine("system", "channel")}{/snippet}
      {#snippet section()}<div class="field"><FLabel forId="upd-channel" text="Channel" hint={CHANNEL_HINT} /><select id="upd-channel" onchange={(e) => (form.channel = e.currentTarget.value)}>{#each Object.entries(CHANNEL_WORDS) as [v, t] (v)}<option value={v} selected={val("channel") === v}>{t}</option>{/each}</select></div><SaveBar id="save-update" effect="check" save={(b) => save(b, ["channel"])} />{/snippet}
    </Pane>
  {:else}
    <div class="pane-empty"><p class="empty">Nothing to show here.</p></div>
  {/if}
</Detail>
