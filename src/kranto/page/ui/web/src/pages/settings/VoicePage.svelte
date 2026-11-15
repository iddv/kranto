<script lang="ts">
  // Settings › Posting › How you write (the fine-tuning of the
  // prose profile; #/settings/posting/voice). In the order a person tunes it: the voice card
  // (plain words, editable; Draft it from my samples writes one for you to read), the four
  // switches (length, register, opinions, emoji), "What do you think?" on Write a post, and the
  // samples (add one, remove one). Under Advanced, folded: the other switches (hashtags, links,
  // reading level), the checker's strictness and its rules, the never, keep and always lists,
  // the guides each site follows, and disclosure for each site. One primary, Save, which sends
  // what changed as one prose.voice; adding or removing a sample is its own small press. The
  // contents and the API are the server's (docs/prose.md, GET /api/prose); this page draws them.
  import Loading from "../../ui/Loading.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import Page from "../Page.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { afkDropPrefix } from "../../lib/app/data";
  import { app, ui } from "../../lib/shell.svelte";
  import { PROSE, SITE_WORDS, SWITCH_LABELS, MAIN_SWITCHES, MORE_SWITCHES, choiceWords, linesOf, listDiff, type Prose } from "./voice";

  let { view }: { view: View } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const c = $derived.by(() => {
    void view.tick;
    return host ? read<Prose>(PROSE, 30000) : null;
  });
  const p = $derived(c?.data || null);
  // the form: what the person has typed, over what the profile holds (null: not touched)
  let voice = $state<string | null>(null);
  let switches = $state<Record<string, string | number>>({});
  let take = $state<boolean | null>(null);
  let strictness = $state<string | null>(null);
  let off = $state<Record<string, boolean>>({});
  let lists = $state<Record<"never" | "keep" | "always", string | null>>({ never: null, keep: null, always: null });
  let guides = $state<Record<string, string[]>>({});
  let disclosure = $state<Record<string, string>>({});
  const LISTS: ["never" | "keep" | "always", string][] = [["never", "Never use (a word, or /a pattern/, a line each)"], ["keep", "Your phrases the checker leaves alone"], ["always", "Every post keeps (a sign-off)"]];
  let sample = $state("");
  let drafting = $state(false);

  const sw = (k: string): string | number => switches[k] ?? p?.switches[k] ?? "";
  const changes = $derived.by((): Record<string, unknown> => {
    if (!p) return {};
    const out: Record<string, unknown> = {};
    if (voice != null && voice !== p.voice) out.voice = voice;
    const s = Object.fromEntries(Object.entries(switches).filter(([k, v]) => p.switches[k] !== v));
    if (Object.keys(s).length) out.switches = s;
    if (take != null && take !== p.take) out.take = take;
    if (strictness != null && strictness !== p.strictness) out.strictness = strictness;
    const rulesOff = p.rules.filter((r) => off[r.id] ?? !r.on).map((r) => r.id);
    if (rulesOff.join() !== p.rules.filter((r) => !r.on).map((r) => r.id).join()) out.rules_off = rulesOff;
    for (const k of ["never", "keep", "always"] as const) {
      const v = lists[k];
      if (v == null) continue;
      const d = listDiff(p[k], linesOf(v));
      if (d.add.length) out[`${k}_add`] = d.add;
      if (d.remove.length) out[`${k}_remove`] = d.remove;
    }
    const g = Object.fromEntries(Object.entries(guides).filter(([site, names]) => names.join() !== (p.sites.find((x) => x.site === site)?.guides || []).join()));
    if (Object.keys(g).length) out.guides = g;
    const dd = Object.fromEntries(Object.entries(disclosure).filter(([site, line]) => line !== (p.sites.find((x) => x.site === site)?.disclosure || "")));
    if (Object.keys(dd).length) out.disclosure = dd;
    return out;
  });
  const dirty = $derived(Object.keys(changes).length > 0);

  function reset(): void {
    voice = null; switches = {}; take = null; strictness = null; off = {};
    lists = { never: null, keep: null, always: null }; guides = {}; disclosure = {};
  }
  function save(btn: HTMLElement | null): void {
    const L = app();
    if (!L || !dirty) return;
    void L.act(btn, () => L.api("/api/prose/voice", changes), (r) => {
      afkDropPrefix(PROSE);
      reset();
      L.say((r as { say?: string }).say || "Saved: the next posts are written this way.");
    });
  }
  function addSample(btn: HTMLElement | null): void {
    const L = app();
    const text = sample.trim();
    if (!L || !text) return;
    void L.act(btn, () => L.api("/api/prose/voice", { samples_add: [{ text }] }), () => {
      afkDropPrefix(PROSE);
      sample = "";
      L.say("Added: the closest samples go in as examples for each post.");
    });
  }
  function removeSample(btn: HTMLElement | null, id: string): void {
    const L = app();
    if (!L) return;
    void L.act(btn, () => L.api("/api/prose/voice", { samples_remove: [id] }), () => {
      afkDropPrefix(PROSE);
      L.say("Removed.");
    });
  }
  async function draftVoice(btn: HTMLElement | null): Promise<void> {
    const L = app();
    if (!L) return;
    drafting = true;
    await L.act(btn, () => L.api("/api/prose/voice/draft", {}), (r) => {
      const v = (r as { voice?: string }).voice;
      if (typeof v === "string" && v.trim()) voice = v;
      L.say("A voice card from your samples, in the box: read it, change it, then Save.");
    });
    drafting = false;
  }
  const guidesOf = (site: string): string[] => guides[site] ?? p?.sites.find((x) => x.site === site)?.guides ?? [];
  function toggleGuide(site: string, name: string, on: boolean): void {
    const now = guidesOf(site).filter((g) => g !== name);
    guides = { ...guides, [site]: on ? [...now, name] : now };
  }
</script>

{#if !host}
  <div data-title="How you write"><NeedHost what="How you write" verb="needs" /></div>
{:else if !p}
  <Page head={{ title: "How you write", crumb: [{ to: "settings/posting", w: "Posting" }] }}>{#snippet body()}<Loading error={c?.error} what="how you write" />{/snippet}</Page>
{:else}
  <Page head={{ title: "How you write", label: "How you write", crumb: [{ to: "settings/posting", w: "Posting" }, { to: "settings/posting/voice", w: "How you write" }],
      facts: `${p.samples.length} ${p.samples.length === 1 ? "sample" : "samples"} · checker ${p.strictness}`,
      primary: { label: "Save", id: "voice-save", run: () => save(document.getElementById("voice-save")), title: dirty ? "Save what you changed" : "Nothing changed yet" } }}
    sections={[{ id: "card", w: "Your voice" }, { id: "switches", w: "Switches" }, { id: "samples", w: "Samples", n: p.samples.length }, { id: "advanced", w: "Advanced" }]}>
    {#snippet section(s)}
      {#if s.id === "card"}
        <p class="muted small">How you write, in plain words. Every post follows it.</p>
        <textarea id="voice-card" class="wide" rows="7" maxlength="2000" value={voice ?? p.voice} oninput={(e) => (voice = e.currentTarget.value)}></textarea>
        <p class="acts"><button type="button" class="btn sm" id="voice-draft" disabled={drafting || !p.samples.length} title={p.samples.length ? "One model call; nothing is kept until you Save" : "Add a sample first"} onclick={(e) => void draftVoice(e.currentTarget)}>Draft it from my samples</button>{#if dirty}<span class="muted small">{" Not saved yet."}</span>{/if}</p>
      {:else if s.id === "switches"}
        <dl class="kv" id="voice-switches">
          {#each MAIN_SWITCHES as k (k)}
            <dt><label for={"voice-sw-" + k}>{SWITCH_LABELS[k]}</label></dt>
            <dd><select id={"voice-sw-" + k} value={String(sw(k))} onchange={(e) => (switches = { ...switches, [k]: e.currentTarget.value })}>{#each p.switch_choices[k] || [] as v (v)}<option value={String(v)}>{choiceWords(k, String(v))}</option>{/each}</select></dd>
          {/each}
          <dt><label for="voice-take">What do you think?</label></dt>
          <dd><label class="inline"><input id="voice-take" type="checkbox" checked={take ?? p.take} onchange={(e) => (take = e.currentTarget.checked)} /> Ask for my own line on Write a post</label></dd>
        </dl>
      {:else if s.id === "samples"}
        <ul class="voice-samples small" id="voice-samples">
          {#each p.samples as x (x.id)}<li><span class="muted">{`${x.site ? SITE_WORDS[x.site] || x.site : "any site"} · ${x.words} words · `}</span>{x.start}{" "}<button type="button" class="linkish small" onclick={(e) => removeSample(e.currentTarget, x.id)}>Remove</button></li>
          {:else}<li class="muted">No samples yet: paste three to five things you wrote.</li>{/each}
        </ul>
        <textarea id="voice-sample" class="wide" rows="4" placeholder="Paste something you wrote" bind:value={sample}></textarea>
        <p class="acts"><button type="button" class="btn sm" id="voice-sample-add" disabled={!sample.trim()} onclick={(e) => addSample(e.currentTarget)}>Add this sample</button></p>
      {:else}
        <details id="voice-advanced"><summary class="small">The other switches, the checker, your lists, guides and disclosure</summary>
          <dl class="kv small">
            {#each MORE_SWITCHES as k (k)}
              <dt><label for={"voice-sw-" + k}>{SWITCH_LABELS[k]}</label></dt>
              <dd>{#if k === "grade"}<input id="voice-sw-grade" type="number" min="3" max="16" value={String(sw("grade"))} onchange={(e) => (switches = { ...switches, grade: Number(e.currentTarget.value) })} />{:else}<select id={"voice-sw-" + k} value={String(sw(k))} onchange={(e) => (switches = { ...switches, [k]: e.currentTarget.value })}>{#each p.switch_choices[k] || [] as v (v)}<option value={String(v)}>{choiceWords(k, String(v))}</option>{/each}</select>{/if}</dd>
            {/each}
            <dt><label for="voice-strict">The checker</label></dt>
            <dd><select id="voice-strict" value={strictness ?? p.strictness} onchange={(e) => (strictness = e.currentTarget.value)}><option value="off">off</option><option value="light">light</option><option value="strict">strict</option></select></dd>
          </dl>
          <details class="small"><summary>{`What the checker looks for (${p.rules.length})`}</summary>
            <ul class="voice-rules">{#each p.rules as r (r.id)}<li><label class="inline"><input type="checkbox" checked={!(off[r.id] ?? !r.on)} onchange={(e) => (off = { ...off, [r.id]: !e.currentTarget.checked })} /> {r.words}</label></li>{/each}</ul>
          </details>
          {#each LISTS as [k, w] (k)}
            <label class="small" for={"voice-list-" + k}>{w}</label>
            <textarea id={"voice-list-" + k} class="wide" rows="3" value={lists[k] ?? p[k].join("\n")} oninput={(e) => (lists = { ...lists, [k]: e.currentTarget.value })}></textarea>
          {/each}
          <details class="small"><summary>Guides and disclosure for each site</summary>
            {#each p.sites as x (x.site)}
              <fieldset class="voice-site"><legend>{SITE_WORDS[x.site] || x.site}</legend>
                {#each p.guides.filter((g) => !g.always) as g (g.name)}<label class="inline"><input type="checkbox" checked={guidesOf(x.site).includes(g.name)} onchange={(e) => toggleGuide(x.site, g.name, e.currentTarget.checked)} /> {g.title}</label>{" "}{/each}
                <label class="inline">Disclosure <input type="text" class="wide" placeholder={`off (or: ${p.disclosure_line})`} value={disclosure[x.site] ?? x.disclosure} oninput={(e) => (disclosure = { ...disclosure, [x.site]: e.currentTarget.value })} /></label>
              </fieldset>
            {/each}
          </details>
        </details>
      {/if}
    {/snippet}
  </Page>
{/if}

<style>
  .voice-samples { padding-left: 18px; }
  .voice-rules { columns: 2; padding-left: 0; list-style: none; }
  .voice-site { border: 1px solid var(--border); border-radius: 6px; margin: 6px 0; padding: 6px 10px; }
  @media (max-width: 640px) { .voice-rules { columns: 1; } }
</style>
