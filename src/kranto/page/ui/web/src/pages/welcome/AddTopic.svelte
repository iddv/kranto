<script lang="ts">
  // Add topic (WORKSPACE.md 2.13): the name, the sentence, suggestions and Scout sources, then the
  // scout's proposals as ticked rows and one Watch button, the foot's, which watches what is
  // ticked and goes on. On #/topics/new it is the list pane (its side, TopicAside, is the pane);
  // on #/welcome/topics, onboarding's step 2, the stage's column draws both. Once scouted the
  // words are the topic's: Add another topic starts afresh. The proposals' group is the old
  // module's (proposalBox: a topic's Sources and Today's proposals draw it too), as is watching
  // the ticked ones (watchTicked).
  import FLabel from "../../ui/FLabel.svelte";
  import List from "../../ui/List.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import Proposals from "../topics/Proposals.svelte";
  import { watchTicked } from "../topics/proposals";
  import { plural } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { go, href } from "../../lib/router";
  import { app, ui } from "../../lib/shell.svelte";
  import { flash } from "../../lib/app/data";
  import { free, SETUP_API } from "../settings/keys.svelte";
  import { SOURCES_API } from "../settings/sources.svelte";
  import TopicAside from "./TopicAside.svelte";
  import { PRODUCT, Product } from "../../lib/product";
  import { afkJob, afterTopics, newStep, RESTORE, restoreStep, SUGGEST, takeScouted, TOPIC, type Scouted } from "./welcome.svelte";

  let { view, mode = "page" }: { view: View; mode?: "page" | "welcome" } = $props();
  const welcome = $derived(mode === "welcome");
  const host = $derived(!!ui.facts?.header.host);
  $effect.pre(() => {
    if (!TOPIC.t) TOPIC.t = newStep();
  });
  const T = $derived(TOPIC.t || newStep());
  const locked = $derived(!!T.id);
  // the scout is one model call: with no key it could only fail (QA B13); an older server
  // without /api/setup's key part does not hold it
  const keyed = $derived.by(() => {
    const k = host ? read<{ key?: { set?: boolean } }>(SETUP_API, 30000).data?.key : null;
    return !k || !!k.set;
  });
  const keyHref = $derived(welcome ? "#/welcome" : "#/settings/watching");
  const keyWord = $derived(welcome ? "Finding places needs a model from step 1 ›" : "Finding places needs a model: Settings › Watching ›");
  // what is ticked is read at each draw (a tick does not redraw, as on the old page)
  const pending = $derived.by(() => {
    void view.tick;
    return !!T.id && T.rows.some((p) => T.ticked.has(p.id) && p.review !== "approved");
  });
  let nameEl = $state<HTMLInputElement>();
  let descEl = $state<HTMLTextAreaElement>();
  let scouting = $state<string | null>(null);

  // the name takes the cursor when the form opens (S02: no click to reach it), once the side's
  // reads are in
  let focusing = !TOPIC.t?.id && !TOPIC.t?.name;
  $effect(() => {
    if (!focusing || !host) return;
    if ([read("/api/topics", 20000), read(SOURCES_API, 20000), read(SETUP_API, 30000)].every((c) => c.data || c.error)) {
      focusing = false;
      setTimeout(() => {
        if (nameEl?.isConnected) nameEl.focus();
      }, 0);
    }
  });

  // step 2 after a reload: setup's topic and its proposals read back from the server (a scout
  // still running is waited for again), once a page load, before setup is done
  $effect(() => {
    if (!welcome || !host || RESTORE.tried) return;
    const t = TOPIC.t;
    if (!t) return;
    if (t.id || t.name) {
      RESTORE.tried = true;
      return;
    }
    const s = read<{ done?: boolean; topics?: number }>(SETUP_API, 30000);
    if (!s.data && !s.error) return;
    RESTORE.tried = true;
    const L = app();
    if (!L || !s.data || s.data.done || !(s.data.topics || 0)) return;
    void restoreStep(L, t)
      .then(async (r) => {
        if (!r?.running || !t.id) return;
        scouting = "Finding places to read…";
        const x = await afkJob<Scouted>(L, { job: r.running }, `/api/topics/${t.id}/scout`, "Finding places to read", (w) => (scouting = w));
        takeScouted(t, x);
        L.afkDrop();
      })
      .catch(() => undefined) // nothing read back: the form stays empty, as before
      .finally(() => (scouting = null));
  });

  function pick(n: string, d: string): void {
    T.name = n;
    T.desc = d;
  }
  function another(): void {
    TOPIC.t = newStep();
  }
  /** Scout sources (a topic is made from the words first), then Scout more: the scout's job runs
   * in the background, the button says for how long; new proposals join the rows, a close match
   * ticked */
  function scoutFor(btn: HTMLButtonElement): void {
    const L = app(), t = T;
    if (!L) return;
    const name = t.name.trim(), desc = t.desc.trim();
    if (!name || !desc) {
      (name ? descEl : nameEl)?.focus();
      return;
    }
    scouting = "Finding places to read…";
    void L.act(btn, async () => {
      const first = (t.id ? await L.api(`/api/topics/${t.id}/scout`, {}) : await L.api("/api/topics", { name, description: desc, scout: true })) as { id: number };
      if (!t.id) t.id = first.id;
      const x = await afkJob<Scouted>(L, first, `/api/topics/${t.id}/scout`, "Finding places to read", (w) => (scouting = w));
      takeScouted(t, x);
      L.afkDrop();
    }).finally(() => {
      scouting = null;
      free(btn);
    });
  }
  /** the topic from its words, unscouted (2, Gemini 2: with no model key Continue went on
   * and threw the topic away, and #/topics/new could not make one at all; kranto_topic_add's
   * scout=false always could). Its sources come once a key works, or by hand now. */
  async function saveTopic(t: typeof T): Promise<number | null> {
    const L = app(), name = t.name.trim(), desc = t.desc.trim();
    if (!L || t.id) return t.id ?? null;
    if (!name) return null;
    const r = (await L.api("/api/topics", { name, description: desc || name, scout: false })) as { id: number };
    t.id = r.id;
    L.afkDrop();
    return r.id;
  }
  const SAVED = (name: string) => `Saved “${name}”. Its sources come once a model works (step 1); you can add one by hand now.`;
  /** the foot's one button: watch what is ticked (or save the topic typed, unscouted), then go on */
  function onward(btn: HTMLButtonElement): void {
    const L = app(), t = T, watch = pending, typed = !t.id && !!t.name.trim();
    if (!L) return;
    void L.act(btn, async () => (watch && t.id ? watchTicked(t.id, t.rows, t.ticked) : typed ? saveTopic(t) : 0), () => {
      const id = t.id, name = t.name.trim();
      TOPIC.t = null;
      if (typed) flash(SAVED(name));
      go(welcome ? afterTopics() : "topics/" + id + "/sources");
    }).finally(() => free(btn));
  }
  /** Save the topic (no key, so no scout): on #/topics/new its Sources come next, to add one by hand */
  function saveOnly(btn: HTMLButtonElement): void {
    const L = app(), t = T;
    if (!L) return;
    if (!t.name.trim()) {
      nameEl?.focus();
      return;
    }
    void L.act(btn, () => saveTopic(t), () => {
      const id = t.id, name = t.name.trim();
      TOPIC.t = null;
      flash(SAVED(name));
      go("topics/" + id + "/sources");
    }).finally(() => free(btn));
  }
</script>

{#snippet form()}
  <section class="box"><div class="box-h"><h2>{locked ? "Topic" : "Add a topic"}</h2></div><div class="box-b">
    <div class="field"><label for="topic-name">Name</label><input id="topic-name" style="width:100%" value={T.name} placeholder="A short name" disabled={locked} bind:this={nameEl} oninput={(e) => { T.name = e.currentTarget.value; }} /></div>
    <div class="field"><FLabel forId="topic-desc" text="What it covers, in one sentence" tipId="topics.sentence" /><textarea id="topic-desc" style="min-height:72px" disabled={locked} placeholder="One sentence: what it covers, for a reader who has never heard of it." value={T.desc} bind:this={descEl} oninput={(e) => { T.desc = e.currentTarget.value; }}></textarea></div>
    {#if !locked}<div class="field"><div class="lbl">{"Suggestions "}<span class="muted small">(optional; edit anything you pick)</span></div><div class="chips">{#each SUGGEST as [n, d] (n)}<button class="chip" type="button" aria-pressed={T.name === n ? "true" : "false"} onclick={() => pick(n, d)}>{n}</button>{/each}</div></div>{/if}
    <div class="inline"><button class={"btn" + (T.rows.length ? "" : " primary")} id="scout" disabled={!keyed} title={keyed ? undefined : "Needs a model"} onclick={(e) => scoutFor(e.currentTarget)}>{scouting || (T.rows.length ? "Find more" : "Find places to read")}</button>{#if keyed}<span class="muted small">One model call. Every place is test-read; nothing is watched until you tick it.</span>{:else}{#if !welcome && !locked}<button class="btn primary" id="topic-save" onclick={(e) => saveOnly(e.currentTarget)}>Save the topic</button>{/if}<a class="small" id="scout-needs-key" href={keyHref}>{keyWord}</a>{/if}{#if locked}<span class="grow"></span><button class="btn" onclick={another}>Add another topic</button>{/if}</div>
    {#if T.message && !scouting}<p class="muted small mt" id="scout-said">{`${plural(T.rows.length, "place")} found.` + (T.invalid ? ` ${T.invalid} could not be read and ${T.invalid === 1 ? "is" : "are"} not shown.` : "")}</p>{/if}
  </div></section>
{/snippet}
<!-- while the scout runs, what it is doing and how long it takes; "found nothing" only once it
     has ended (fix 3, mock `scout`) -->
{#snippet finding()}<section class="box" id="scout-state" role="status" aria-live="polite"><div class="box-h"><h2>Finding places to read</h2><span class="grow"></span><span class="muted small">about 2 minutes</span></div><div class="box-b"><p>Searching the web, Hacker News, GitHub and arXiv, then test-reading each place it finds.</p><p class="muted small" id="scout-elapsed">{scouting}</p></div></section>{/snippet}
{#snippet props()}{#if T.id}<Proposals title={`Proposed for “${T.name.trim()}”`} tid={T.id} rows={T.rows} ticked={T.ticked} busy={!!scouting} plain={welcome} />{/if}{/snippet}

{#if welcome}
  <div><div class="ph"><h1>What topics are you interested in?</h1></div>
    {#if scouting && !T.rows.length}{@render finding()}
    {:else}<p class="ph-meta">{`A topic is a name and one sentence in your own words. ${Product} asks it of every item it reads, finds places to read for it, and watches nothing until you tick it.`}</p>
      <div class="cols"><div>{@render form()}{@render props()}</div><aside><TopicAside {view} welcome /></aside></div>{/if}
    <div class="inline wizard-foot sticky"><a class="btn" href="#/welcome">Back</a><span class="grow"></span>{#if !scouting}<a class="btn" href={"#/" + afterTopics()}>Skip for now</a><button class="btn primary" id="watch-continue" onclick={(e) => onward(e.currentTarget)}>{pending ? "Watch these and continue" : "Continue"}</button>{/if}</div>
  </div>
{:else if !host}
  <div data-title="Add topic"><NeedHost what="Topics" /></div>
{:else}
  <List title="Add topic" crumb="Topics" sub={`A name and one sentence; ${PRODUCT} finds places to read.`}>
    {@render form()}{#if scouting && !T.rows.length}{@render finding()}{/if}{@render props()}
    {#if T.id}<div class="inline wizard-foot"><a class="btn" href={href("topics/" + T.id)}>Open the topic</a><span class="grow"></span><button class="btn primary" onclick={(e) => onward(e.currentTarget)}>{pending ? "Watch these and open the topic" : "Done"}</button></div>{/if}
  </List>
{/if}
