<script lang="ts">
  // An installed cub's state on its Settings sheet: each kind it may ask
  // for, for real or in practice (for real is the house confirm, here only; practice is a click, and kranto cub dry from
  // a terminal); Stop and Resume; Update (Kranto fetches its source again and shows the files'
  // change and what it may now do, before anything is applied); Remove. The server's own features
  // (built-in) have none of this: they are not installed.
  import { app } from "../../lib/shell.svelte";
  import { read } from "../../lib/reads.svelte";
  import { confirmThen } from "../../ui/dialog.svelte";
  import type { RequestSchema } from "../index";
  import { CUBS_API, cubPath, JOB_WORKING, type CubDetail, type CubJob } from "../cub";
  import { cubFresh as fresh, cubLive, cubPost, cubStop } from "../cubverbs";

  // part: "about" on its Settings page, where its live switches are rows of On
  // and off: the cub's state, Look for an update, Update to…, Remove
  let { id, title, schemas = {}, every = 800, part = "all" }: { id: string; title: string; schemas?: Record<string, RequestSchema>; every?: number; part?: "all" | "about" } = $props();
  const d = $derived(read<CubDetail>(cubPath(id), 20000));
  const cub = $derived(d.data || null);
  const kinds = $derived(cub?.grants?.requests || []);
  let update = $state<CubJob | null>(null);
  // an update staged already (by Look for an update, or kranto cub update in a terminal): its job,
  // read on load, so Update to X… is here without a press
  let staged = "";
  $effect(() => {
    const job = cub?.update?.job;
    const L = app();
    if (!job || !L || update || staged === job) return;
    staged = job;
    void (L.api(`${CUBS_API}/jobs/${job}`) as Promise<CubJob>).then((j) => {
      if (!update && j && j.state === "awaiting_confirm") update = j;
    }, () => {});
  });

  const post = (btn: HTMLElement | null, verb: string, body: Record<string, unknown>, said: string): void => cubPost(id, btn, verb, body, said);
  const live = (kind: string, on: boolean, btn: HTMLElement): void => cubLive(id, title, kind, on, schemas, btn);
  const stop = (btn: HTMLElement): void => cubStop(id, title, btn);
  async function poll(L: NonNullable<ReturnType<typeof app>>): Promise<void> {
    for (let i = 0; update && JOB_WORKING.includes(update.state) && i < 600; i++) {
      await new Promise((r) => setTimeout(r, every));
      update = (await L.api(`${CUBS_API}/jobs/${update.id}`)) as CubJob;
    }
  }
  function lookForUpdate(btn: HTMLElement): void {
    const L = app();
    if (!L) return;
    void L.act(btn, async () => {
      update = ((await L.api(cubPath(id, "update"), {})) as { job: CubJob }).job;
      await poll(L);
    }, () => {
      if (update && update.state === "cancelled") {
        // "up to date", or the same update is staged already: its job is read again on load
        const why = update.error;
        update = null;
        staged = "";
        L.say(why && why !== "up to date" ? `${title}: ${why}.` : `${title} is up to date.`);
      }
      fresh();
    });
  }
  function apply(btn: HTMLElement): void {
    const L = app();
    const j = update;
    if (!L || !j || !j.cub) return;
    const delta = j.cub.delta;
    const lines = [`${title} ${j.cub.version}: ${j.cub.diff ? `${j.cub.diff.counts.changed} files changed, ${j.cub.diff.counts.added} added, ${j.cub.diff.counts.removed} removed` : "its files changed"}.`];
    for (const [block, items] of Object.entries(delta?.added || {})) lines.push(`It may now: ${block}: ${items.join(", ")}.`);
    for (const [block, items] of Object.entries(delta?.removed || {})) lines.push(`No longer: ${block}: ${items.join(", ")}.`);
    if (delta?.grown) lines.push("Because it may do more, everything it asks for goes back to practice.");
    confirmThen(`Update ${title}?`, lines, "Update", () => L.act(btn, () => L.api(cubPath(id, "apply_update"), { job: j.id, confirm: true }), () => {
      update = null;
      fresh();
      L.say(`${title} is updated to ${j.cub!.version}.`);
    }));
  }
  function remove(btn: HTMLElement): void {
    const L = app();
    if (!L) return;
    confirmThen(`Remove ${title}?`, ["Its process ends and what it asks you is closed.", "Its history, runs and calls stay in your library; its folder is kept 30 days; its settings stay, so adding it again finds them."],
      "Remove", () => L.act(btn, () => L.api(cubPath(id, "remove"), { confirm: true }), () => {
        fresh();
        L.flash(`${title} is removed.`);
        location.hash = "#/post";
      }), "danger");
  }
</script>

{#if cub}
  <div id="cub-controls">
    {#if part === "all"}
      <h3 class="box-h">What it may ask you</h3>
      {#each kinds as k (k)}{@const on = cub.live.includes(k)}
        <div class="field" data-kind={k}><label for={"live-" + k}>{schemas[k]?.title || k}</label>
          <span class="hint">{on ? "for real: your approval does it" : "practice: your approval sends nothing"}</span>
          <span class="ctl"><button class="btn sm sw" role="switch" id={"live-" + k} aria-checked={on ? "true" : "false"} onclick={(e) => live(k, !on, e.currentTarget)}>{on ? "For real" : "Practice"}</button></span></div>
      {/each}
      {#if !kinds.length}<p class="muted small">It asks you for nothing.</p>{/if}
      <h3 class="box-h">The feature</h3>
    {/if}
    <p class="small" id="cub-state">{cub.state === "paused" ? `Paused: ${cub.paused?.note || "by the core"}.` : "Running when it is due."}{cub.tree_ok ? "" : " Its files no longer match what you approved."}</p>
    {#if cub.source_gone}<p class="small c-amber" id="cub-source-gone">{cub.source_gone.words}</p>{/if}
    <p class="acts">
      {#if cub.state === "paused"}<button class="btn sm" id="cub-resume" onclick={(e) => post(e.currentTarget, "resume", {}, `${title} runs again.`)}>Resume</button>
      {:else}<button class="btn sm" id="cub-stop" onclick={(e) => stop(e.currentTarget)}>Stop</button>{/if}
      {#if update && update.state === "awaiting_confirm"}<button class="btn sm primary" id="cub-apply" onclick={(e) => apply(e.currentTarget)}>{`Update to ${update.cub?.version}`}</button>
      {:else}<button class="btn sm" id="cub-update" onclick={(e) => lookForUpdate(e.currentTarget)}>Look for an update</button>{/if}
      <button class="btn sm danger" id="cub-remove" onclick={(e) => remove(e.currentTarget)}>Remove</button>
    </p>
    {#if update && update.state === "failed"}<p class="flash red small" id="cub-update-error">{update.error}</p>{/if}
  </div>
{/if}

<style>
  .box-h { font-size: 12.5px; font-weight: 700; margin: 14px 0 4px; }
  .field { padding: 9px 0; border-top: 1px solid var(--border-2); display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 2px 16px; align-items: center; }
  .field label { margin: 0; font-weight: 500; }
  .field .hint { grid-column: 1; color: var(--muted); font-size: 11.5px; }
  .field .ctl { grid-column: 2; grid-row: 1 / span 2; display: flex; gap: 4px; align-items: center; justify-content: flex-end; }
  .acts { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
  .btn.danger { border-color: var(--red); color: var(--red); }
</style>
