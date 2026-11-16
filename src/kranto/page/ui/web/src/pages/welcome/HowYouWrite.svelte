<script lang="ts">
  // Welcome's "How you write" (#/welcome/voice; F-13, mock
  // `voice`): the screen Start reading opens, so it fills the wait for the first brief and adds
  // nothing to the time to it. One line on top says the read as it goes (the server's /api/home
  // `first`). Paste a few things you wrote (prose.voice's samples_add); the four switches (length,
  // register, opinions, emoji: prose.voice's switches); Show my voice card drafts one from the
  // samples (POST /api/prose/voice/draft: one short model call, nothing kept until Save). Skip for
  // now and Save how I write both land on the home's first hour; skipped, the writer uses the
  // shipped floor and plain words. Reading your own posts from a connected feed is not offered
  // yet (no server route reads them: the deferred table).
  import Loading from "../../ui/Loading.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { go } from "../../lib/router";
  import { app } from "../../lib/shell.svelte";
  import { HOME_API, type HomeAnswer } from "../../features/home";
  import { free } from "../settings/keys.svelte";
  import { PRODUCT } from "../../lib/product";
  import { firstLine, PROSE_API, SWITCH_SHOWN, samplesLine, splitSamples, switchLabel, type Prose } from "./voice";

  let { view }: { view: View } = $props();
  const pc = $derived.by(() => {
    void view.tick;
    return read<Prose>(PROSE_API, 60000);
  });
  const p = $derived(pc.data);
  const home = $derived.by(() => {
    void view.tick;
    return read<HomeAnswer>(HOME_API, 8000).data;
  });
  const progress = $derived(firstLine(home?.first ?? null));
  let text = $state("");
  let chosen = $state<Record<string, string>>({});
  let card = $state<string | null>(null);
  let drafting = $state(false);
  const samples = $derived(splitSamples(text));
  const now = (k: string): string => chosen[k] ?? String(p?.switches?.[k] ?? "");

  // the line on top moves while the read goes on
  $effect(() => {
    const t = setInterval(() => app()?.render(), 8000);
    return () => clearInterval(t);
  });

  function draft(btn: HTMLButtonElement): void {
    const L = app();
    if (!L || !samples.length) return;
    drafting = true;
    void L.act(btn, () => L.api("/api/prose/voice/draft", { samples }), (x) => {
      card = (x as { voice?: string }).voice || null;
    }).finally(() => {
      drafting = false;
      free(btn);
    });
  }
  function save(btn: HTMLButtonElement): void {
    const L = app();
    if (!L) return;
    const body: Record<string, unknown> = {};
    if (samples.length) body.samples_add = samples.map((t) => ({ text: t, site: null }));
    const sw = Object.fromEntries(Object.entries(chosen).filter(([k, v]) => v && String(p?.switches?.[k] ?? "") !== v));
    if (Object.keys(sw).length) body.switches = sw;
    if (card) body.voice = card;
    if (!Object.keys(body).length) {
      go("home");
      return;
    }
    void L.act(btn, () => L.api("/api/prose/voice", body), (x) => {
      L.afkStale(PROSE_API);
      go("home");
      L.say((x as { say?: string }).say || `Saved how you write. Every post ${PRODUCT} drafts follows it; Settings › Posting › Voice changes it.`);
    }).finally(() => free(btn));
  }
</script>

<div class="narrow" id="how-you-write"><div class="ph"><h1>How you write</h1></div>
  {#if progress}<p class="read-line muted small" id="voice-reading" role="status">{progress}</p>{/if}
  <p class="ph-meta">{`The posts ${PRODUCT} drafts for you should sound like you. Paste a few things you wrote, and set four switches. You can skip this and do it later.`}</p>
  {#if !p}<Loading error={pc.error} />{:else}
    <section class="box"><div class="box-b">
      <div class="field"><label for="voice-samples">Things you wrote <span class="muted small">(posts, a page, emails; put <code>---</code> on a line between them)</span></label><textarea id="voice-samples" style="min-height:120px;width:100%" value={text} oninput={(e) => { text = e.currentTarget.value; card = null; }}></textarea><p class="muted small">{samplesLine(text)}</p></div>
      <div class="voice-switches">{#each SWITCH_SHOWN as k (k)}<label class="field" for={"voice-" + k}><span class="lbl">{switchLabel(k)}</span><select id={"voice-" + k} value={now(k)} onchange={(e) => { chosen = { ...chosen, [k]: e.currentTarget.value }; }}>{#each p.switch_choices[k] || [] as v (String(v))}<option value={String(v)}>{String(v) === "mine" ? "only mine" : String(v) === "suggest" ? "suggest one for me" : String(v)}</option>{/each}</select></label>{/each}</div>
      <div class="inline"><button type="button" class="btn" id="voice-draft" disabled={!samples.length || drafting} onclick={(e) => draft(e.currentTarget)}>{drafting ? "Reading them…" : card ? "Try again" : "Show my voice card"}</button><span class="muted small">One short model call; nothing is kept until you save.</span></div>
      {#if card}<blockquote class="voice-card" id="voice-card">{card}</blockquote>{/if}
    </div></section>
  {/if}
  <div class="inline wizard-foot"><span class="grow"></span><a class="btn" id="voice-skip" href="#/home">Skip for now</a><button class="btn primary" id="voice-save" onclick={(e) => save(e.currentTarget)}>Save how I write</button></div>
</div>
