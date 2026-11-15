<script lang="ts">
  // Add a cub (the install sheet): a folder on the machine Kranto runs on, or a
  // git URL at a tag, branch or commit. the server fetches it in the background (no request waits
  // on git) and inspects it; the sheet polls the job and, when it waits for you, draws the
  // manifest in Kranto's own words with its findings. Install (in practice) is the house confirm,
  // from this page only; nothing of the cub runs before it is pinned, and nothing it asks for is
  // sent until you turn it live on its page.
  import { onDestroy } from "svelte";
  import { app } from "../../lib/shell.svelte";
  import { confirmThen } from "../../ui/dialog.svelte";
  import { FEATURES_API, trustWord } from "../index";
  import { CANNOT, CUBS_API, cubHref, cubPath, JOB_WORKING, type CubJob } from "../cub";

  let { done, every = 800 }: { done: (id: string | null) => void; every?: number } = $props();
  let source = $state("");
  let ref = $state("");
  let job = $state<CubJob | null>(null);
  let gone = false;
  onDestroy(() => (gone = true));
  const git = $derived(/^(https:\/\/|ssh:\/\/|git@|file:\/\/)/.test(source.trim()));
  const c = $derived(job?.cub || null);
  const STEP: Record<string, string> = { queued: "Waiting to start…", fetching: "Fetching…", fetched: "Reading its manifest…", inspected: "Checking it…",
    placing: "Installing…", placed: "Installing…", pinned: "Installing…" };

  async function poll(): Promise<void> {
    const L = app();
    for (let i = 0; L && job && JOB_WORKING.includes(job.state) && i < 600 && !gone; i++) {
      await new Promise((r) => setTimeout(r, every));
      if (gone) return;
      job = (await L.api(`${CUBS_API}/jobs/${job.id}`)) as CubJob;
    }
  }
  function fetchIt(btn: HTMLElement): void {
    const L = app();
    if (!L || !source.trim()) return;
    void L.act(btn, async () => {
      const r = (await L.api(`${CUBS_API}/fetch`, { source: source.trim(), ...(git && ref.trim() ? { ref: ref.trim() } : {}) })) as { job: CubJob };
      job = r.job;
      void poll();
    }, () => {});
  }
  function cancel(btn: HTMLElement): void {
    const L = app();
    if (!L || !job) return;
    const id = job.id;
    void L.act(btn, () => L.api(`${CUBS_API}/jobs/${id}/cancel`, {}), () => {
      job = null;
      L.say("Not installed: nothing of it was kept.");
    });
  }
  function install(btn: HTMLElement): void {
    const L = app();
    if (!L || !job || !c) return;
    const j = job;
    const cub = c;
    confirmThen(`Install ${cub.title}?`, [
      `${cub.title} ${cub.version}, ${trustWord(cub.trust)}${cub.trust === "unreviewed" ? ": nobody at Kranto has read this code" : ""}.`,
      "It runs in Kranto's sandbox with only what the sheet lists. Everything it asks you to send or post waits for your approval, and is practice (nothing is sent) until you turn on Send for real.",
    ], "Install", () => L.act(btn, () => L.api(cubPath(cub.id, "install"), { job: j.id, confirm: true }), () => {
      L.afkStale(FEATURES_API);
      L.afkStale(CUBS_API);
      L.say(`${cub.title} is installed, in practice: nothing is sent until you turn on Send for real.`);
      done(cub.id);
    }));
  }
</script>

<div id="cub-add">
  {#if !job}
    <label for="cub-source">A folder on this machine, or a git URL</label>
    <input id="cub-source" bind:value={source} placeholder="~/cubs/my-cub or https://github.com/you/my-cub" autocomplete="off" spellcheck="false" />
    {#if git}<label for="cub-ref">Tag, branch or commit</label><input id="cub-ref" bind:value={ref} placeholder="v1.0.0 (empty: its default branch)" autocomplete="off" spellcheck="false" />{/if}
    <p class="muted small">{git ? "From a git URL a cub is unreviewed: nobody at Kranto has read it. Kranto fetches it without any credential of yours." : "From a folder a cub is yours. Kranto copies it; edit it there and Update to take a change."}</p>
    <p class="foot"><span class="muted small">kranto reads it and shows you what it may do; nothing runs or installs yet.</span><button class="btn primary" id="cub-fetch" disabled={!source.trim()} onclick={(e) => fetchIt(e.currentTarget)}>Read it</button></p>
  {:else if JOB_WORKING.includes(job.state)}
    <p class="muted" id="cub-job" role="status">{STEP[job.state] || job.state}</p>
  {:else if job.state === "awaiting_confirm" && c}
    <h3>{c.title} <span class={"htag t-" + c.trust}>{trustWord(c.trust)}</span></h3>
    <p class="lede">{`${c.id} ${c.version}${c.sha ? " · commit " + c.sha.slice(0, 12) : ""} · ${c.inventory.files} files · licence ${c.inventory.licence}`}</p>
    {#if c.trust === "unreviewed"}<p class="flash amber small"><b>Nobody at Kranto has read this code.</b> It runs in the sandbox like every cub, with only what is listed here.</p>{/if}
    <dl class="perm" id="cub-words">{#each c.words as [k, w], i (i)}<dt>{k}</dt><dd>{w}</dd>{/each}</dl>
    {#if c.inventory.findings.length}
      <p class="about-k">What Kranto found in its code</p>
      <ul class="findings" id="cub-findings">{#each c.inventory.findings as x, i (i)}<li><b>{x.text}</b></li>{/each}</ul>
    {/if}
    <p class="muted small">{CANNOT}</p>
    <p class="foot"><button class="btn quiet" id="cub-cancel" onclick={(e) => cancel(e.currentTarget)}>Cancel</button><button class="btn primary" id="cub-install" onclick={(e) => install(e.currentTarget)}>Install</button></p>
  {:else}
    <p class="flash red small" id="cub-job-error">{job.error || `The job is ${job.state}.`}</p>
    {#if job.state === "cancelled" && job.error === "up to date" && c}<p><a href={cubHref(c.id)}>{c.title}</a> is up to date.</p>{/if}
    <p class="foot"><button class="btn" id="cub-again" onclick={() => (job = null)}>Try again</button></p>
  {/if}
</div>

<style>
  #cub-add input { width: 100%; margin-bottom: 8px; }
  #cub-add label { font-weight: 600; display: block; margin-top: 8px; }
  .foot { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; justify-content: space-between; margin-top: 12px; }
  .perm { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 6px 14px; margin: 10px 0; }
  .perm dt { font-size: 11px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; color: var(--muted); }
  .about-k { font: 600 10.5px var(--mono); text-transform: uppercase; letter-spacing: .05em; color: var(--muted); margin: 14px 0 4px; }
  .findings { margin: 0 0 8px 18px; }
  .lede { color: var(--muted); max-width: 70ch; margin-bottom: 8px; }
  .htag { display: inline-block; font: 500 10.5px/16px var(--sans); padding: 0 7px; border-radius: 8px; color: var(--text); background: var(--subtle); border: 1px solid var(--border-2); white-space: nowrap; }
  .t-owner { background: var(--violet-wash); } .t-unreviewed { background: var(--amber-wash); }
  @media (max-width: 700px) { .perm { grid-template-columns: 1fr; gap: 2px; } }
</style>
