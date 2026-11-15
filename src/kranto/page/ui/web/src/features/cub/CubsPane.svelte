<script lang="ts">
  // Cubs' sheet (D6: the shell's one sheet, the pane in Classic): Add a cub
  // (sel=add: a folder or a git URL, read by the server, its manifest in words, Install, in practice)
  // with Check a manifest as a fold; Check alone (sel=check) without the cub runtime: a pasted
  // cub.yaml read by Kranto's one validator, nothing installed or run.
  import Detail from "../../ui/Detail.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { app, ui } from "../../lib/shell.svelte";
  import { trustWord } from "../index";
  import { CANNOT, CUBS_API, cubHref, permissionWords, type CubsList } from "../cub";
  import AddCub from "./AddCub.svelte";

  interface Checked { ok: boolean; error?: string; trust?: string; manifest?: Record<string, unknown>; why?: string; hash?: string }
  let { view }: { view: View } = $props();
  const H = $derived(!!ui.facts?.header.host);
  const sel = $derived(view.w.r.sel || "");
  const lines = $derived.by(() => {
    void view.tick;
    return H ? read<CubsList>(CUBS_API, 20000).data || null : null;
  });
  let text = $state("");
  let checked = $state<Checked | null>(null);
  function check(btn: HTMLElement): void {
    const L = app();
    if (!L) return;
    void L.act(btn, async () => {
      try {
        checked = (await L.api("/api/cubs/check", { text })) as Checked;
      } catch (e) {
        checked = { ok: false, error: (e as Error).message };
      }
    }, () => {});
  }
</script>

{#snippet tag(word: string, tone: string)}<span class={"htag t-" + tone.replace(/[^a-z-]/g, "")}>{word}</span>{/snippet}

{#snippet checkForm()}
  {#if !checked || !checked.ok}
    <label for="cub-yaml">Paste the cub's manifest</label>
    <textarea id="cub-yaml" rows="10" bind:value={text}></textarea>
    {#if checked && checked.error}<p class="flash red small" id="cub-check-error">{checked.error}</p>{/if}
    <p class="foot"><span class="muted small">Checked by Kranto's one validator; nothing is installed or run.</span><button class="btn primary" id="cub-check" onclick={(e) => check(e.currentTarget)}>Check</button></p>
  {:else}
    {@const m = checked.manifest || {}}
    <h3>{String(m.title || m.id)} {@render tag(trustWord(checked.trust || "unreviewed"), checked.trust || "unreviewed")}</h3>
    <p class="lede">{`${String(m.id)} ${String(m.version)} · speaks ${String(m.api)}.`} <b>Nobody at Kranto has read this code.</b> It would run in the sandbox like every cub, in practice (nothing sent) until you say otherwise.</p>
    <p class="lede">{String(m.says || "")}</p>
    <p class="about-k">This cub will</p>
    <dl class="perm" id="cub-will">{#each permissionWords(m) as [k, w] (k)}<dt>{k}</dt><dd>{w}</dd>{/each}</dl>
    <p class="muted small">{CANNOT}</p>
    <p class="about-k">After install</p>
    <p class="small muted">Pinned at its manifest's hash; an update that adds no permission applies by itself, any other shows the diff and each new permission first. A tile appears on your home under Cubs; it may not add rows to Needs you until you allow it on its Settings page. Its widgets wait in the library until you add them.</p>
    <p class="foot"><button class="btn quiet" onclick={() => (checked = null)}>Check another</button><span class="flash amber small" id="cub-install-later">{checked.why}</span></p>
  {/if}
{/snippet}

<Detail back={view.back}>
  {#if lines && (sel === "add" || sel === "check")}
    <div class="pane-in cubs-sheet" id="cubs-sheet" data-title="Add a cub">
      <p class="dk mono">Add a cub · in practice</p>
      <AddCub done={(cid) => (location.hash = cid ? cubHref(cid) : href("cubs"))} />
      <details class="fold" id="cub-check-fold" open={sel === "check"}><summary>Check a manifest first: paste a cub.yaml, nothing is installed</summary>{@render checkForm()}</details>
    </div>
  {:else if sel === "check"}
    <div class="pane-in cubs-sheet" id="cubs-sheet" data-title="Check a manifest">
      <p class="dk mono">Check · the manifest, in words</p>
      {@render checkForm()}
    </div>
  {:else}
    <div class="pane-empty"><p class="empty">{sel ? "Nothing to show here." : "Nothing selected."}</p></div>
  {/if}
</Detail>

<style>
  .cubs-sheet .dk { color: var(--muted); font-size: 12.5px; margin: 0 0 8px; }
  .cubs-sheet h3 { font-size: 16px; font-weight: 650; margin-bottom: 6px; }
  textarea { width: 100%; min-height: 76px; resize: vertical; }
  .perm { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 6px 14px; margin: 10px 0; }
  .perm dt { font-size: 11px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; color: var(--muted); }
  .foot { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; justify-content: space-between; margin-top: 12px; }
  .foot .flash { margin: 0; }
  .about-k { font: 600 10.5px var(--mono); text-transform: uppercase; letter-spacing: .05em; color: var(--muted); margin: 14px 0 4px; }
  .fold { margin-top: 18px; border-top: 1px solid var(--border-2); padding-top: 10px; }
  .fold summary { cursor: pointer; color: var(--muted); font-size: 12.5px; }
  .lede { color: var(--muted); max-width: 70ch; margin-bottom: 8px; }
  @media (max-width: 700px) { .perm { grid-template-columns: 1fr; gap: 2px; } }
</style>
