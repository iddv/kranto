<script lang="ts">
  // A topic's sources as rows: one component, three doors.
  // - top, the topic page's Sources section: its proposals, then the five watched sources that
  //   keep the most, "All N ›";
  // - all, the topic's Sources page: the proposals with their ticks and Watch these, then Watched,
  //   Wildcards and the rest, each group's meaning beside its heading;
  // - edit, the Edit sheet: every row with Remove visible, Approve and Dismiss on proposals,
  //   then Add a source from your library, Add source and Scout more.
  // A row is SrcLine with the topic: a proposal is approved for it, a shared source says what
  // else it feeds, and ⋯ (or Remove) takes it out of this topic only. Every change is one press
  // with Undo wherever it is made (sourceverbs.ts, proposals.ts): the sheet's Save is for the
  // topic's words and switches.
  import Group from "../../ui/Group.svelte";
  import Proposals from "./Proposals.svelte";
  import { TICKS, watchTicked } from "./proposals";
  import { plural } from "../../lib/format";
  import { read } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { app } from "../../lib/shell.svelte";
  import type { Sources } from "../../api/afk.gen";
  import SrcLine from "../settings/SrcLine.svelte";
  import { addTo } from "../settings/sourceverbs";
  import { GROUPS } from "../settings/sources.svelte";
  import { scoutMore } from "./scout";
  import { topicGroups, topSources, watchedHere, type TopicPage } from "./topics";

  let { t, at = 0, mode = "all", close = undefined }: { t: TopicPage; at?: number; mode?: "top" | "all" | "edit"; close?: () => void } = $props();
  const here = $derived({ id: t.id, name: t.name });
  const proposed = $derived(t.source_rows.filter((s) => s.review === "proposed"));
  const best = $derived(topSources(t.source_rows, t.id));
  const wild = $derived(t.source_rows.filter((s) => s.group === "wildcard" && s.review === "approved" && !watchedHere(s, t.id)).length);
  const groups = $derived(topicGroups(t, GROUPS).filter((g) => g[0] !== "proposed"));
  // the latest grades of its sources (the topic's JSON does not carry them)
  const G = $derived.by(() => {
    void at;
    const ids = (mode === "top" ? [...proposed, ...best] : t.source_rows).map((s) => s.id);
    return ids.length ? read<{ grades: Record<string, unknown> }>(`/api/feedback?target=source&ids=${ids.map((i) => encodeURIComponent(i)).join(",")}`, 30000).data?.grades || {} : {};
  });
  const all = $derived(href(`topics/${t.id}/sources`));
  const NUM = ["no", "one", "two", "three", "four", "five"];
  // the number the topic says everywhere (its Facts, the topic list): what it watches
  const allWord = $derived(t.sources ? `All ${t.sources} ›` : "All ›");
  // edit: the library's other sources, to add to this topic in one press
  const lib = $derived.by(() => {
    void at;
    return mode === "edit" ? read<Sources>("/api/sources", 30000).data : null;
  });
  let q = $state(""), scouting = $state<string | null>(null);
  // read when the sheet opens (lib first), so the list is there by the first letter typed
  const found = $derived(lib && q.trim() ? lib.sources.filter((s) => !t.source_rows.some((x) => x.id === s.id && watchedHere(x, t.id))
    && (s.label + " " + s.kind + " " + s.site_name).toLowerCase().includes(q.trim().toLowerCase())).slice(0, 8) : []);

  /** the proposals ticked for this topic: the close matches until you change them */
  function ticks(): Set<number> {
    return (TICKS[t.id] ||= new Set(t.source_rows.filter((s) => s.pretick).map((s) => s.id)));
  }
  /** Watch these: what is ticked is watched for the topic (a wildcard with no topic) */
  function watchThese(btn: HTMLElement): void {
    const L = app();
    if (!L) return;
    const tk = ticks(), rows = proposed, name = t.name, id = t.id;
    void L.act(btn, async () => {
      const n = await watchTicked(id, rows, tk);
      L.afkDrop();
      return n;
    }, (n) => {
      delete TICKS[id];
      L.say(`Watching ${plural(n as number, "more source")} for ${name}. Their first fetch is the next ingest run.`);
    });
  }
</script>

{#if mode === "top"}
  {#snippet head()}<a id="ov-sources-all" href={all}>{allWord}</a>{/snippet}
  {#snippet foot()}{#if !proposed.length && !best.length}<p class="more">No source yet: Add source, or Scout more.</p>{:else if best.length && t.sources > best.length}<p class="more muted small">{best.length === 1 ? "The one that keeps the most. " : `The ${NUM[best.length] || best.length} that keep the most. `}<a href={all}>{allWord}</a></p>{/if}{/snippet}
  <Group id="ov-sources" title="Sources" says={[`${t.sources} watched`, wild ? plural(wild, "wildcard") : null, proposed.length ? `${proposed.length} proposed` : null].filter(Boolean).join(" · ")} kind="srcs" right={head} {foot}>
    {#each proposed as s, k (s.id)}<SrcLine {s} approve {here} primary={k === 0} current={G[String(s.id)]} {at} />{/each}
    {#each best as s (s.id)}<SrcLine {s} {here} current={G[String(s.id)]} {at} />{/each}
  </Group>
{:else if mode === "edit"}
  <ul class="lst pl te-src" id="te-sources">
    {#each proposed as s, k (s.id)}<SrcLine {s} approve {here} primary={k === 0} bare {at} />{/each}
    {#each groups as [, , , rows]}{#each rows as s (s.id)}<SrcLine {s} {here} bare remove {at} />{/each}{/each}
  </ul>
  {#if !t.source_rows.length}<p class="muted small">No sources yet.</p>{/if}
  <div class="field te-add"><label for="te-find">Add a source from your library</label><input id="te-find" placeholder="Type a source's name" autocomplete="off" bind:value={q} /></div>
  {#if found.length}
    <ul class="lst pl te-src" id="te-found">
      {#each found as s (s.id)}<li class="te-row"><span class="grow">{s.label}<span class="muted small">{` · ${s.site_name || s.kind}${s.topics.length ? " · feeds " + s.topics.map((x) => x.name).join(", ") : " · no topic"}${s.review && s.review !== "approved" ? " · " + s.review : ""}`}</span></span><button type="button" class="btn sm" data-act="te-add" onclick={(e) => { void addTo(e.currentTarget, { id: s.id, label: s.label, topics: s.topics.length }, here); q = ""; }}>Add</button></li>{/each}
    </ul>
  {:else if q.trim() && lib}<p class="muted small">No source in your library is called that.</p>{/if}
  <p class="muted small" id="te-src-more">A new feed, site or account: <a href={href("settings/sources/new", { topic: t.id })} onclick={close}>Add source</a>{" (it is added to this topic), or "}<button type="button" class="linkish" id="te-scout" onclick={() => { close?.(); void scoutMore(null, t, (w) => (scouting = w)); }}>{scouting || "Scout more"}</button>.</p>
{:else}
  {#if proposed.length}<Proposals title="Proposed" tid={t.id} rows={proposed} ticked={ticks()} approve name={t.name}>{#snippet foot()}<button class="btn sm primary" id="watch-these" onclick={(e) => watchThese(e.currentTarget)}>Watch these</button>{/snippet}</Proposals>{/if}
  {#each groups as [key, title, blurb, rows] (key)}
    <Group id={"src-" + key} {title} says={blurb || null} count={String(rows.length)} kind="srcs" fold={"topic-sources:" + key}>
      {#each rows as s (s.id)}<SrcLine {s} {here} current={G[String(s.id)]} {at} />{/each}
    </Group>
  {/each}
  {#if !t.source_rows.length}<p class="empty">No sources yet.</p>{/if}
{/if}

<style>
  .te-src { margin: 0 0 6px; }
  .te-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; }
  .te-row .grow { flex: 1; min-width: 0; overflow-wrap: anywhere; }
  .te-add { margin-top: 10px; }
  .te-add input { width: 100%; }
</style>
