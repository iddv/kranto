<script lang="ts">
  // Edit a topic (topicedit.ts): its name and description, its sources (the topic's own rows,
  // TopicSourceRows, Remove from this topic, Approve or Dismiss a proposal, add one from
  // your library, Add source or Scout more, each at once with Undo), the settings it has
  // (Paused, and News's brief when News is on) and Archive. Save
  // writes what changed of its words and switches, with one Undo; Archive takes it off your
  // lists, with Undo. The topic's
  // words are what items are compared with before any model call, and what the pitch and the
  // brief of an idea from it read (CON D-2).
  import Loading from "../../ui/Loading.svelte";
  import { features } from "../../features/index";
  import { ROWS as NEWS_ROWS, type TopicRows } from "../../features/news/news";
  import { read } from "../../lib/reads.svelte";
  import { ui } from "../../lib/shell.svelte";
  import { archiveTopic, changeWords, saveTopic, type TopicDraft } from "./topicedit";
  import { topicApi, type TopicPage } from "./topics";
  import TopicSourceRows from "./TopicSourceRows.svelte";

  let { id, close }: { id: number; close: () => void } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const c = $derived(read<TopicPage>(topicApi(id), 20000));
  const t = $derived(c.data);
  const fx = $derived((features(host)?.features || []).filter((x) => x.enabled).map((x) => x.id));
  const newsOn = $derived(fx.includes("news"));
  const news = $derived(newsOn ? read<TopicRows>(NEWS_ROWS, 30000).data : null);
  const newsNow = $derived(news?.topics.find((x) => x.id === id)?.news.enabled ?? null);

  // the sheet's own copy, filled once the topic arrives
  // the words as the fields were filled: what Save compares with (a read that refreshes meanwhile
  // never makes Save write old words back)
  let name = $state(""), description = $state(""), filled = $state(false), orig = $state({ name: "", description: "" });
  let paused = $state<boolean | null>(null), brief = $state<boolean | null>(null);
  $effect(() => {
    if (t && !filled) {
      name = t.name;
      description = t.description;
      orig = { name: t.name, description: t.description };
      paused = t.status === "paused";
      filled = true;
    }
  });
  $effect(() => {
    if (brief === null && newsNow !== null) brief = newsNow;
  });

  // its sources change at once, with Undo, in the rows themselves (TopicSourceRows): Save is for
  // its words and its switches
  const draft = $derived.by((): TopicDraft | null => !t ? null : {
    id, name: t.name,
    before: { ...orig },
    words: { name: name.trim().replace(/\s+/g, " "), description: description.trim() },
    add: [], remove: [], was: {},
    status: paused !== null && paused !== (t.status === "paused") && t.status !== "archived" ? { from: t.status, to: paused ? "paused" : "active" } : null,
    news: brief !== null && newsNow !== null && brief !== newsNow ? { from: newsNow, to: brief } : null,
  });
  const said = $derived(draft ? changeWords(draft) : []);
  const bad = $derived(!name.trim() ? "A topic needs a name." : !description.trim() ? "A topic needs a description: it is what items are compared with." : null);

  const last = $derived(t?.history?.[0] ?? null);
</script>

<div class="dlg-h" id="dlg-t">{t ? `Edit ${t.name}` : "Edit topic"}</div>
<div class="dlg-b topic-edit">
  {#if !t}
    <Loading error={c.error} />
  {:else}
    {#if t.kind !== "user"}<p class="note c-amber" role="status">This topic is a project's: its words follow the project. Its sources and settings can change here.</p>{/if}
    <div class="field"><label for="te-name">Name</label><input id="te-name" maxlength="120" bind:value={name} disabled={t.kind !== "user"} /></div>
    <div class="field">
      <label for="te-desc">Description</label>
      <textarea id="te-desc" rows="4" maxlength="2000" bind:value={description} disabled={t.kind !== "user"}></textarea>
      <p class="muted small" id="te-desc-says">Your own words for what this topic is about. Every item is compared with them before any model call, and the idea cards written from this topic read them.</p>
    </div>

    <!-- its sources are the topic's own rows: each change is one press with
         Undo, as on its page and its Sources; Remove takes one out of this topic only -->
    <h3 class="te-h">Sources <span class="muted small">{`${t.sources} watched · each change is made at once, with Undo`}</span></h3>
    <TopicSourceRows {t} mode="edit" {close} />
    <p class="muted small">Remove takes a source out of this topic only; its evidence stays. A source left with no topic is retired (not read), never read for everything.</p>

    <h3 class="te-h">Settings</h3>
    <ul class="lst pl te-set">
      {#if t.status !== "archived"}<li class="te-row"><span class="grow">Paused<span class="muted small"> · its sources are not read; nothing is removed</span></span><button type="button" class="btn sm sw" role="switch" aria-checked={paused ? "true" : "false"} aria-label={`Pause ${t.name}`} data-act="te-pause" onclick={() => (paused = !paused)}>{paused ? "On" : "Off"}</button></li>{/if}
      {#if newsOn && brief !== null}<li class="te-row"><span class="grow">News brief<span class="muted small"> · a brief of what it kept, on News's schedule</span></span><button type="button" class="btn sm sw" role="switch" aria-checked={brief ? "true" : "false"} aria-label={`News for ${t.name}`} data-act="te-news" onclick={() => (brief = !brief)}>{brief ? "On" : "Off"}</button></li>{/if}
    </ul>
    {#if last}<p class="muted small" id="te-last">{`Last change: ${last.at.slice(0, 16).replace("T", " ")}${last.by ? ", from " + (last.by === "ui" ? "this page" : last.by) : ""}.`}</p>{/if}
    <p class="small" id="te-says" role="status">{bad || (said.length ? "Save: " + said.join(", ") + "." : "Nothing changed yet.")}</p>
  {/if}
</div>
<!-- svelte-ignore a11y_autofocus -->
<div class="dlg-f">{#if t && t.status !== "archived"}<button type="button" class="btn quiet" id="te-archive" title="Off your lists and not read; its evidence, themes and ideas stay. Undo brings it back." onclick={(e) => void archiveTopic(e.currentTarget, t, close)}>Archive</button>{/if}<span class="grow"></span><button class="btn" autofocus onclick={close}>Cancel</button><button class="btn primary" id="dlg-ok" disabled={!draft || !!bad} onclick={(e) => draft && void saveTopic(e.currentTarget, draft, close)}>Save</button></div>

<style>
  .topic-edit textarea { width: 100%; }
  .topic-edit input:not([type]) { width: 100%; }
  .te-h { font-size: 14px; font-weight: 650; margin: 16px 0 6px; color: var(--text); }
  .te-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; }
  .te-row .grow { flex: 1; min-width: 0; overflow-wrap: anywhere; }
  .dlg-f .grow { flex: 1; }
</style>
