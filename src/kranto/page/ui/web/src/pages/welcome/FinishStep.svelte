<script lang="ts">
  // Welcome's third step (#/welcome/finish; mock `ready`): four lines
  // and a button, inside the first screen at 1400 × 900 and on a phone. The first brief: when it
  // comes. What it costs, by provider (the server's words: a key's dollars, or the Claude plan's
  // usage on the login). The console: Claude Code ready, and that it asks once whether to trust
  // Kranto's folder (Kranto never answers it: D1); or how to get it, since Kranto works without it.
  // Usage reports: off until the person turns them on (nothing is sent before an
  // answer), the three choices under "What they hold". **Start reading** (the primary) marks
  // setup done, starts the first read and opens How you write while kranto reads (F-13).
  import Loading from "../../ui/Loading.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { go } from "../../lib/router";
  import { app } from "../../lib/shell.svelte";
  import UsageChoice from "../settings/UsageChoice.svelte";
  import { PRIVACY_API, type Privacy } from "../settings/privacy";
  import { free, SETUP_API, type Setup } from "../settings/keys.svelte";
  import { afterReady, CONSOLE_INSTALL, STARTED, TOPIC } from "./welcome.svelte";
  import { PRODUCT, PRODUCTS } from "../../lib/product";
  import { consoleWaits } from "../../term/console.svelte";

  let { view }: { view: View } = $props();
  const c = $derived.by(() => {
    void view.tick; // each draw may find the reads stale
    return read<Setup>(SETUP_API, 15000);
  });
  const s = $derived(c.data);
  const pc = $derived.by(() => {
    void view.tick;
    return read<Privacy>(PRIVACY_API, 30000);
  });
  const p = $derived(pc.data || null);
  const keyed = $derived(!s || !s.key || !!s.key.set);
  const cc = $derived(s?.logins?.claude || null);
  const minutes = $derived(s?.first_brief_minutes ?? 5);
  /** the usage line: off until chosen; DO_NOT_TRACK says itself (fix 15) */
  const usage = $derived(!p ? "" : p.why === "DO_NOT_TRACK" ? "Off: DO_NOT_TRACK is set on this machine."
    : p.answered && p.mode !== "off" && p.mode !== "local" ? `${p.meaning.replace(/^./, (x) => x.toUpperCase())}.`
      : "Off. Nothing leaves this machine unless you turn them on.");

  let checking = $state(false);
  /** Check again: the server asks `claude auth status` now (POST /api/setup/check) */
  function again(btn: HTMLButtonElement): void {
    const L = app();
    if (!L) return;
    checking = true;
    void L.act(btn, () => L.api("/api/setup/check", {}), () => {
      L.afkStale(SETUP_API);
      L.render();
    }).finally(() => (checking = false));
  }
  function start(btn: HTMLButtonElement): void {
    const L = app();
    if (!L) return;
    void L.act(btn, async () => {
      const x = await L.api("/api/setup/finish", {});
      L.afkDrop();
      await L.loadHost(); // the topic made a step ago is in the server's status now
      return x;
    }, (x) => {
      consoleWaits(false); // setup is done: the console may follow its setting again (F-11)
      TOPIC.t = null;
      go(afterReady());
      L.say(STARTED[(x as { ingest?: string }).ingest || ""] || "Set up.");
    }).finally(() => free(btn));
  }
</script>

{#if !s}
  <Loading error={c.error} />
{:else}
  <div class="narrow"><div class="ph"><h1>Ready</h1></div>
    <ul class="ready-lines">
      <li id="ready-brief"><strong>The first brief</strong> {`In about ${minutes} minutes.`}</li>
      <!-- the cost's words are the server's (/api/setup's cost): the page holds no price of its own -->
      {#if s.cost}<li id="ready-cost"><strong>What it costs</strong> <span id="cost-line">{s.cost}</span> <a href="#/settings/spend">Spend ›</a></li>{/if}
      <li id="ready-claude"><strong>The console</strong> <span id="claude-state">{#if !cc || cc.ok}{`Claude Code is ready. It asks once whether to trust ${PRODUCTS} folder; that is expected.`}{:else if cc.installed === false}{`Not installed; ${PRODUCT} works without it. To add it: `}<code>{CONSOLE_INSTALL}</code>, then run <code>claude</code> once.{:else}{`Installed, not signed in; ${PRODUCT} works without it. Run `}<code>claude</code> once to sign in.{/if}</span>{#if cc && !cc.ok} <button type="button" class="btn sm" id="check-again" disabled={checking} onclick={(e) => again(e.currentTarget)}>{checking ? "Checking…" : "Check again"}</button>{/if}</li>
      {#if p}<li id="usage-reports"><strong>Usage reports</strong> <span id="usage-line">{usage}</span> <details class="inline-more"><summary>What they hold ›</summary><UsageChoice {p} /></details></li>{/if}
    </ul>
    <div class="inline wizard-foot"><a class="btn" href="#/welcome/topics">Back</a><span class="grow"></span>{#if !keyed}<a class="small" id="finish-needs-key" href="#/welcome">Start reading needs a model from step 1 ›</a>{/if}<button class="btn primary" id="finish" disabled={!keyed} title={keyed ? undefined : "Needs a model from step 1"} onclick={(e) => start(e.currentTarget)}>Start reading</button></div>
  </div>
{/if}
