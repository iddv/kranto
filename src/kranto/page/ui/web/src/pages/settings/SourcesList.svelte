<script lang="ts">
  import { SvelteSet } from "svelte/reactivity";
  // Watch › Sources (Settings › Sources until the doors), the list: every source, grouped as the
  // scout and you left them (the accounts they are read with are Settings › Accounts'), with the
  // filters in the toolbar (the old module's filterBar and bulk bar, shared with every list until
  // they move) and Add source as its primary; a row opens the source in the pane, a proposal has
  // Approve. At settings/sources/new the list is Add source's catalog: every kind by site, a
  // filter that hides rows as you type (kept in ?q=, so a redraw agrees), Choose on each kind
  // offered (its form opens in the pane). Without the server, it says so.
  import FilterBar from "../../ui/FilterBar.svelte";
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import Loading from "../../ui/Loading.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Row from "../../ui/Row.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { href, parse } from "../../lib/router";
  import { app, ui } from "../../lib/shell.svelte";
  import { listRoute } from "../data.svelte";
  import SrcLine from "./SrcLine.svelte";
  import { CATALOG_API, filterSources, GROUPS, listGroup, match, presetText, presetWords, SOURCES_API, srcSelects, type Catalog, type Sources } from "./sources.svelte";
  import { shellDoors } from "../../features/shell";
  import RunLine from "../../ui/RunLine.svelte";
  import { readSourcesNow } from "../watch/readnow";

  let { view }: { view: View } = $props();
  // Proposed is the first decision: its first eight rows, then Show all; every other group starts
  // folded to its name and count, opened by its ▸ and remembered
  const FIRST = 8;
  const opened = new SvelteSet<string>();
  const host = $derived(!!ui.facts?.header.host);
  // Sources and Add source are Watch's pages with the doors on (QA B16; SRC D7: the title's
  // crumb says Watch), Settings' without them
  const addCrumb = $derived(shellDoors(host) ? "Watch" : "Settings");
  // every source is All topics' Sources under the doors (WT: a topic's own are its page)
  const allTitle = $derived(shellDoors(host) ? "All topics › Sources" : "Sources");
  const allCrumb = $derived(shellDoors(host) ? null : addCrumb);
  const r = $derived(listRoute(view.w));
  const adding = $derived(r.path[1] === "sources" && r.path[2] === "new");
  const c = $derived.by(() => {
    void view.tick; // each draw may find the reads stale
    return host && !adding ? read<Sources>(SOURCES_API) : null;
  });
  const d = $derived(c?.data || null);
  const xs = $derived(d ? filterSources(d.sources, r.q) : []);
  const sites = $derived(d ? [...new Set(d.sources.map((s) => s.site_name))].sort() : []);
  // the latest grades of the watched and retired rows (the list's JSON does not carry them)
  const G = $derived.by(() => {
    void view.tick;
    return d && d.sources.length ? read<{ grades: Record<string, unknown> }>(`/api/feedback?target=source&ids=${d.sources.map((s) => encodeURIComponent(s.id)).join(",")}`, 30000).data?.grades || {} : {};
  });
  // the toolbar's filters are drawn again only when what they show changed: a redraw never loses a typed word

  const cc = $derived.by(() => {
    void view.tick;
    return host && adding ? read<Catalog>(CATALOG_API, 60000) : null;
  });
  const cat = $derived(cc?.data || null);
  const kinds = $derived(cat ? cat.providers.reduce((a, p) => a + p.presets.length, 0) : 0);
  // opened from a topic (?topic=): its head names it from the first press, the way back is its Sources
  const forTopic = $derived(adding && r.q.topic ? (cat?.topics.find((t) => String(t.id) === String(r.q.topic)) || null) : null);
  const addTitle = $derived(forTopic ? `Add source to ${forTopic.name}` : "Add source");
  // the catalog's filter: typed here and kept in the address (replaceState: no draw), so the next
  // draw reads it from ?q= as a link to the catalog would
  let typed = $state<{ at: number; q: string } | null>(null);
  const qText = $derived(typed && typed.at === view.tick ? typed.q : r.q.q || "");
  function filterCatalog(e: Event & { currentTarget: HTMLInputElement }): void {
    const now = parse();
    typed = { at: view.tick, q: e.currentTarget.value };
    history.replaceState(null, "", href("settings/sources/new", { ...now.q, q: typed.q, sel: now.sel }));
  }

</script>

{#snippet addBtn()}<a class="btn sm primary" id="add-source" href="#/settings/sources/new">Add source</a>{/snippet}

{#if adding}
  {#if !host}
    <List title="Add source" crumb={addCrumb}><NeedHost what="Add source" /></List>
  {:else if !cat}
    <List title="Add source" crumb={addCrumb}><Loading error={cc?.error} /></List>
  {:else}
    <List title={addTitle} crumb={addCrumb === "Watch" ? "Watch › Sources" : addCrumb} sub="Pick a kind, give it an address or a search, Preview, then Add.">
      {#snippet tools()}<span class="tbn"><input type="search" id="search" class="tb-q" placeholder="Filter the catalog  ( / )" aria-label="Filter the catalog" value={qText} oninput={filterCatalog} /><span class="grow"></span><span>{`${kinds} kinds on ${cat.providers.length} sites`}</span>{#if forTopic}<a class="btn sm" id="add-back" href={href("watch/sources", { topic: String(forTopic.id) })}>{`All sources of ${forTopic.name}`}</a>{:else}<a class="btn sm" id="add-back" href="#/settings/sources">All sources</a>{/if}</span>{/snippet}
      {#each cat.providers as p (p.key)}
        <Group id={"cat-" + p.key} title={p.name} count={String(p.presets.length)} kind="catalog" fold={"catalog:" + p.key} hidden={!p.presets.some((s) => match(qText, presetText(p, s)))}>
          {#each p.presets as s (s.key)}
            {@const w = presetWords(s, cat)}
            {#snippet choose()}<a class="btn sm" href={href("settings/sources/new", { topic: r.q.topic, sel: "epreset:" + s.key })} title="Choose">Choose</a>{/snippet}
            <Row sel={s.available ? "epreset:" + s.key : null} title={s.name} meta={w.meta} end={s.available ? choose : undefined} off={!s.available}
              text={presetText(p, s)} hidden={!match(qText, presetText(p, s))} stw={w.st}>{#snippet st()}<Glyph name={w.st[0]} colour={w.st[1]} word={w.st[2]} />{/snippet}</Row>
          {/each}
        </Group>
      {/each}
    </List>
  {/if}
{:else if !host}
  <List title={allTitle} crumb={allCrumb}><NeedHost what="Sources" /></List>
{:else if !d}
  <List title={allTitle} crumb={allCrumb}>
    {#snippet tools()}<span class="tbn"><span class="grow"></span>{@render addBtn()}</span>{/snippet}
    <Loading error={c?.error} />
  </List>
{:else}
  <!-- with the doors on Add source is the head's primary, Read sources now under
       its ⋯ and the ingest's line the head's; the toolbar keeps the filter -->
  <List title={allTitle} crumb={allCrumb} head={ui.headOn ? { primary: { label: "Add source", id: "add-source", href: "#/settings/sources/new" },
    more: [{ label: "Read sources now", id: "sources-read-now", title: "Read every source now (it spends: model calls)", run: (b) => readSourcesNow(b) }],
    line: "kind:ingest", lineId: "sources-run-line" } : null}>
    {#snippet tools()}<span class="tbn filters"><FilterBar r={{ path: ["settings", "sources"], q: r.q, sel: null }} base="settings/sources" placeholder="Filter sources" selects={srcSelects(sites) as never} /><span class="grow"></span><span class="muted">{`${xs.length} of ${d.sources.length}`}</span>{#if !ui.headOn}{#if shellDoors(host)}<button type="button" class="btn sm" id="sources-read-now" title="Read every source now (it spends: model calls)" onclick={(e) => readSourcesNow(e.currentTarget)}>Read sources now</button>{/if}{@render addBtn()}{/if}</span>{/snippet}
    {#if shellDoors(host) && !ui.headOn}<RunLine subject="kind:ingest" tick={view.tick} id="sources-run-line" />{/if}
    {#each GROUPS as [key, title, blurb] (key)}
      {@const g = xs.filter((s) => listGroup(s) === key)}
      {#if g.length}
        {@const rows = opened.has(key) || g.length <= FIRST ? g : g.slice(0, FIRST)}
        {#snippet more()}{#if rows.length < g.length}<div class="more"><button type="button" class="linkish" data-show-all={key} onclick={() => opened.add(key)}>{`Show all ${g.length}`}</button></div>{/if}{/snippet}
        <Group id={"src-" + key} {title} says={blurb || null} count={String(g.length)} kind={"srcs" + (g.some((x) => x.review === "proposed") ? " asks" : "")} fold={"sources:" + key} start={key !== "proposed"} foot={more}>
          {#each rows as s (s.id)}<SrcLine {s} approve primary={false} current={G[String(s.id)]} at={view.tick} />{/each}
        </Group>
      {/if}
    {/each}
    {#if !xs.length}<p class="empty">{d.sources.length ? "No sources match." : "No sources yet."}</p>{/if}
    <!-- the accounts sources are read with are Settings › Accounts' (the owner's O1, 2026-10-22);
         Add source says "Connect it first" for a kind that needs one -->
    <p class="topic-only foot">The logins some sources are read with are under <a href="#/settings/watching">Settings › Watching</a>.</p>
  </List>
{/if}
