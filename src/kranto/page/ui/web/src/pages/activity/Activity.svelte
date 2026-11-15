<script lang="ts">
  // What Kranto is doing (#/activity, g a; the top bar's indicator opens it, in
  // both layouts and on the phone): Running now (each run's stage, elapsed, spend, who started it,
  // Watch › and Stop), Waiting on you (the verb to its press), Failing (a kind that failed twice
  // in a row or for two days: Run again or Try again, Dismiss, Send this error), Next (each scheduled kind that is
  // on, soonest first, a failing one in red), Recent (the last day: done, failed with the reason,
  // skipped with why, the hourly re-checks folded to a line a kind; Show every row). The foot says
  // how long the runs' marks are kept, set under Settings › System. Every word is the read's; a press goes through the server's own routes.
  import Group from "../../ui/Group.svelte";
  import PageTitle from "../../ui/PageTitle.svelte";
  import Row from "../../ui/Row.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import type { Activity, ActivityFail, ActivityRun } from "../../api/types.gen";
  import type { View } from "../../lib/pages.svelte";
  import { ACT_PATH, foldSame, markActivitySeen, runMeta } from "../../lib/activity";
  import { read, stale } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { ACTIVITY_SETTINGS, activityWords, type ActivitySettings } from "../settings/activityset";
  import { ago, dt, nextRead, plural, stamp } from "../../lib/format";
  import RowMore from "../../ui/RowMore.svelte";
  import { app } from "../../lib/shell.svelte";
  import { cubsOf, features } from "../../features/index";
  import { sendError } from "../../ui/sendFeedback";

  let { view }: { view: View } = $props();
  let all = $state(false);
  const path = $derived(all ? `${ACT_PATH}?all=1&limit=200` : ACT_PATH);
  const r = $derived.by(() => {
    void view.tick;
    return read<Activity>(path, 5000);
  });
  const a = $derived(r.data);
  const fixFor = $derived.by(() => {
    void view.tick;
    return new URLSearchParams(location.hash.split("?")[1] || "").get("fix");
  });
  const st = $derived.by(() => {
    void view.tick;
    return app()?.host() ? read<ActivitySettings>(ACTIVITY_SETTINGS, 60000) : null;
  });
  const STATE: Record<string, [string, string, string]> = {
    running: ["running", "blue", "Running"], waiting: ["waiting", "amber", "Waits on you"], ok: ["check", "green", "Done"],
    degraded: ["warn", "amber", "Done with problems"], failed: ["x", "red", "Failed"], skipped: ["open", "grey", "Skipped"],
    stopped: ["held", "grey", "Stopped"],
  };
  const glyph = (s: string): [string, string, string] => STATE[s] || ["open", "grey", s];

  // opening Activity is seeing it: the indicator's red dot goes
  $effect(() => {
    if (a) markActivitySeen();
  });

  function again(): void {
    stale(ACT_PATH);
    app()?.render();
  }
  /** Stop, with Undo for 9 s before it is asked (undo beats confirm) */
  function stop(btn: HTMLElement, x: ActivityRun): void {
    const L = app();
    if (!L) return;
    let undone = false;
    L.toast(`${x.title}: stopping at its next step…`, () => {
      undone = true;
      L.toast(`${x.title} goes on.`);
    });
    btn.setAttribute("disabled", "");
    setTimeout(() => {
      if (undone) {
        btn.removeAttribute("disabled");
        return;
      }
      void L.act(btn, () => L.api("api/activity/stop", { id: x.id }), (y) => {
        L.toast(((y as { words?: string }) || {}).words || "Stopping it.");
        again();
      });
    }, 9000);
  }
  /** the failing kind's verb: Try again (the update check), Run again (a job, a cub's job) */
  function runAgain(btn: HTMLElement, f: ActivityFail): void {
    const L = app();
    if (!L) return;
    // a cub's job (Kranto's own features are first-party: their jobs are the scheduler's)
    const cub = cubsOf(features(!!L.host())).find((x) => x.trust !== "first-party" && f.kind.startsWith(x.id + "."));
    const call = f.kind === "update" ? () => L.api("/api/update/check", {})
      : cub ? () => L.api(`/api/cubs/${encodeURIComponent(cub.id)}/run`, { job: f.kind, confirm: true })
      : () => L.api(`/run/${encodeURIComponent(f.kind)}`, {});
    void L.act(btn, call, () => {
      L.toast(`${f.title}: started again. Its row goes at its next good run.`);
      again();
    });
  }
  function dismiss(btn: HTMLElement, f: ActivityFail): void {
    const L = app();
    if (!L) return;
    void L.act(btn, () => L.api("/api/activity/dismiss", { kind: f.kind }), () => {
      L.toast(`${f.title}: put away until it fails again.`);
      again();
    });
  }
  const lede = $derived.by((): string => {
    if (!a) return r.error ? `The activity could not be read: ${r.error}` : "Reading what Kranto is doing…";
    const parts = [
      a.running.length ? `${plural(a.running.length, "run")} now.` : a.quiet || "Nothing is running.",
      a.waiting.length ? `${a.waiting.length === 1 ? "One stopped" : `${a.waiting.length} stopped`} for you.` : null,
      a.failing.length ? `${plural(a.failing.length, "job")} failing.` : null,
    ];
    return parts.filter(Boolean).join(" ");
  });
</script>

{#snippet runRow(x: ActivityRun, n = 1)}
  {@const g = glyph(x.state)}
  {#snippet end()}
    {#if x.state === "running" && x.trace}<a class="btn sm" href={x.trace + "?follow=1"} title="Its trace, at the running step">Watch ›</a>{/if}
    {#if x.state === "running" && x.stoppable}<button class="btn sm quiet" title={`Stop ${x.title} at its next step`} onclick={(e) => stop(e.currentTarget, x)} disabled={x.stopping}>{x.stopping ? "Stopping…" : "Stop"}</button>{/if}
    {#if x.state === "waiting" && x.needs?.href}<a class="btn sm" href={"#/" + x.needs.href.replace(/^#?\/?/, "")} title={x.needs.words || x.needs.verb || "Open"}>{x.needs.verb || "Open"}</a>{/if}
    {#if x.state !== "running" && x.state !== "waiting" && x.trace}<a class="btn sm quiet" href={x.trace + (x.state === "failed" ? "?failed=1" : "")} title="Its trace">Trace ›</a>{/if}
  {/snippet}
  <Row title={n > 1 ? `${n} runs of ${x.title} failed` : x.state === "waiting" ? x.words || x.title : x.title} href={x.trace} meta={runMeta(x)} age={x.finished ? stamp(x.finished).slice(11) : null} {end}>
    {#snippet st()}<Glyph name={g[0]} colour={g[1]} word={g[2]} />{/snippet}
  </Row>
{/snippet}

<div class="wl act" data-title="Activity">
  <PageTitle title="What Kranto is doing" label="Activity" {lede} ledeId="act-lede" flash={a?.afk_error ? { kind: "amber", text: a.afk_error } : null} />
  {#if a}
    <Group id="act-running" title="Running now" count={String(a.running.length)}>
      {#each a.running as x (x.id)}{@render runRow(x)}{/each}
      {#if !a.running.length}<li class="gempty"><span class="muted">{a.quiet || "Nothing is running."}</span></li>{/if}
    </Group>
    {#if a.waiting.length}
      <Group id="act-waiting" title="Waiting on you" count={String(a.waiting.length)}>
        {#snippet right()}<a href="#/needs">Needs you ›</a>{/snippet}
        {#each a.waiting as x (x.id)}{@render runRow(x)}{/each}
      </Group>
    {/if}
    {#if a.failing.length}
      <Group id="act-failing" title="Failing" count={String(a.failing.length)} about="activity.failing">
        {#each a.failing as f (f.id)}
          <!-- one verb and ⋯ (R1): the title opens what happened (its trace); Dismiss and Send
               this error are the ⋯'s -->
          {#snippet end()}<button class="btn sm" onclick={(e) => runAgain(e.currentTarget, f)}>{f.verb}</button><RowMore label={`${f.title}: more`} items={[{ label: "Dismiss", title: "Put it away until it fails again", run: (b) => dismiss(b as HTMLElement, f) },
            ...(f.error_id ? [{ label: "Send this error", title: `Feedback with this failure's report, shown before anything is sent`, run: () => sendError(f.error_id!, `${f.title} is failing`) }] : [])]} />{/snippet}
          <Row title={`${f.title} is failing`} href={f.trace ? f.trace + "?failed=1" : null} cur={fixFor === f.kind} meta={f.error || null} age={f.since ? ago(dt(f.since)) : null} {end}>
            {#snippet st()}<Glyph name="x" colour="red" word="Failing" />{/snippet}
          </Row>
        {/each}
      </Group>
    {/if}
    <Group id="act-next" title="Next" count={String(a.next.length)}>
      {#each a.next as n (n.kind)}
        {@const fail = !!n.failing_since}
        <Row title={n.title} meta={fail ? "failing" : n.last && n.last.state === "skipped" && n.last.why ? n.last.why : n.every_words} age={nextRead(n.at)}>
          {#snippet st()}<Glyph name={fail ? "x" : "open"} colour={fail ? "red" : "grey"} word={fail ? "Failing" : "Next"} />{/snippet}
        </Row>
      {/each}
      {#if !a.next.length}<li class="gempty"><span class="muted">{a.scheduler ? "Nothing is scheduled." : "Nothing is scheduled: Kranto runs with the scheduler off (kranto serve --no-scheduler)."}</span></li>{/if}
    </Group>
    <Group id="act-recent" title="Recent" count={String(a.recent.length)} about="activity.recent">
      {#snippet right()}<button class="btn sm quiet" id="act-all" onclick={() => { all = !all; }}>{all ? "Fold them" : "Show every row"}</button>{/snippet}
      {#each foldSame(a.recent) as f (f.x.id)}{@render runRow(f.x, f.n)}{/each}
      {#if !all}{#each a.folded as f (f.kind + f.state)}
        <Row title={f.line} meta={f.last ? `last ${stamp(f.last).slice(11)}` : null}>
          {#snippet st()}<Glyph name={f.state === "skipped" ? "open" : "check"} colour="grey" word={f.state === "skipped" ? "Skipped" : "Done"} />{/snippet}
        </Row>
      {/each}{/if}
      {#if !a.recent.length && !a.folded.length}<li class="gempty"><span class="muted">Nothing ran in the last day.</span></li>{/if}
    </Group>
    {#if st?.data}
      <!-- its settings are on Settings › System: the page says them and where -->
      <p class="act-settings small" id="act-settings">{`Runs' marks are kept ${activityWords(st.data)}`}{" · "}<a href={href("settings/system", { sel: "eactivity" })}>Settings ›</a></p>
    {/if}
  {/if}
</div>

<style>
  .act-settings { margin: 16px 0 8px; color: var(--muted); }
</style>
