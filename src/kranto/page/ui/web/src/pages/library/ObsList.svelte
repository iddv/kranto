<script lang="ts">
  // Library › Observations, the list (WORKSPACE.md 1.4, 1.5): one 31 px row each with its tick and
  // grade, the filters in the toolbar (the search, Filter ▾, the sort: the old module's filterBar,
  // shared with every list until they move), the rows grouped by their new flag ("New since your
  // last visit", "Seen before"), the top-20 cut in the group's foot and the pager under it. A search
  // by meaning is one group, best first, with the compacted weeks that match. An observation open
  // in the pane that is not on this page is pinned at the top. Without the server, it says so.
  // A topic's Evidence is this list with its topic fixed (topic): no Topic filter, its own sources
  // in Source's, no notes about the library and no compacted weeks. Under the doors it is Watch's
  // Evidence: "Robotics › Evidence" (#/watch/topic/<id>/evidence), or "All topics › Evidence"
  // (#/watch/evidence), the aggregate, which you choose.
  import { markSeen } from "../front/seen";
  import FilterBar from "../../ui/FilterBar.svelte";
  import PageTitle from "../../ui/PageTitle.svelte";
  import { untrack } from "svelte";
  import Group from "../../ui/Group.svelte";
  import Loading from "../../ui/Loading.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import Icon from "../../shell/Icon.svelte";
  import { dt, plural } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { shellDoors } from "../../features/shell";
  import { href } from "../../lib/router";
  import { app, ui } from "../../lib/shell.svelte";
  import { listRoute } from "../data.svelte";
  import ObsLine from "./ObsLine.svelte";
  import Pager from "./Pager.svelte";
  import RollupLine from "./RollupLine.svelte";
  import { ARCHIVE_THEMES, archiveName, type ArchiveThemes } from "./map.svelte";
  import { byWords, filtered, gradesPath, n2, obsQuery, obsSelects, visitWord, type EvidenceOf, type FeedbackGrades, type ObservationPage, type ObsRow, type Observations, type Status } from "./library";

  let { view, topic = null }: { view: View; topic?: EvidenceOf | null } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const doors = $derived(shellDoors(host));
  const base = $derived(doors ? (topic ? `watch/topic/${topic.id}/evidence` : "watch/evidence") : topic ? `topics/${topic.id}/evidence` : "library");
  // named as the subnav names it: Evidence under the doors, Observations in the Library (QA B21);
  // under the doors the title says whose (WT): a topic's, or All topics
  const allWord = $derived(doors ? "Evidence" : "Observations");
  const title = $derived(doors ? `${topic ? topic.name : "All topics"} › Evidence` : topic ? "Evidence" : allWord);
  const r = $derived(listRoute(view.w));
  const qq = $derived.by(() => {
    void view.tick; // a since= filter is a time: each draw works it out again, as the old page did
    return obsQuery(topic ? { ...r.q, topic: String(topic.id) } : r.q);
  });
  const c = $derived.by(() => {
    void view.tick; // each draw may find the reads stale
    return host ? read<Observations>(qq.path, 60000) : null;
  });
  const d = $derived(c?.data || null);
  const H = $derived.by(() => {
    void view.tick;
    return (app()?.host() as Status | null) || null;
  });
  const selects = $derived(H ? obsSelects(H, qq.meaning, topic) : []);
  const placeholder = $derived(qq.meaning || !r.q.q ? (topic ? "Ask this topic's evidence" : "Ask the library") : "Find words");
  // the toolbar's filters are drawn again only when what they show changed: a redraw never loses a typed word
  const narrowed = $derived(filtered(r.q, !!topic));
  // the latest grades of the page's rows (its JSON does not carry them)
  const G = $derived.by(() => {
    void view.tick;
    return d && d.results.length ? read<FeedbackGrades>(gradesPath(d.results.map((o) => o.id)), 30000).data?.grades || {} : {};
  });
  // the observation open in the pane, pinned when it is not on this page
  const pin = $derived(view.w.object === "observation" && view.w.obj ? String(view.w.obj[2]) : null);
  const pc = $derived.by(() => {
    void view.tick;
    return d && pin && !d.results.some((o) => String(o.id) === pin) ? read<ObservationPage>(`/api/observations/${encodeURIComponent(pin)}?k=12`, 60000) : null;
  });
  const fresh = $derived(!d || qq.meaning ? [] : d.results.filter((o) => o.new));
  const seen = $derived(!d ? [] : qq.meaning ? d.results : d.results.filter((o) => !o.new));
  const marked = $derived(!qq.meaning && (r.q.sort || "new") === "new" && !r.q.since && !narrowed);
  const by = $derived(byWords(r.q.sort));
  const cut = $derived(!!d && !!qq.top && d.total > d.results.length);
  const pages = $derived(!d || qq.top ? 1 : Math.max(1, Math.ceil(d.total / qq.size)));
  // one Parallax theme (?theme=): its name, from the archive's themes once they are read
  const themeName = $derived.by(() => {
    void view.tick;
    return r.q.theme && !topic ? archiveName(read<ArchiveThemes>(ARCHIVE_THEMES, 600000).data, r.q.theme) : "";
  });

  // Mark all seen (⇧a): the last-visit marker moves to now, with Undo
  $effect(() => {
    void view.tick; // the page's keys are set again on every draw
    if (host) app()?.pageKey("⇧a", () => void markSeen(null));
  });
  const gradeOf = (o: ObsRow, k: number) => ({ current: G[String(o.id)] || o.grade, position: k + 1 });
</script>

{#snippet row(o: ObsRow, k: number)}<ObsLine {o} mute tick isNew={!!o.new} grade={gradeOf(o, k)} />{/snippet}
{#snippet cutLine()}{#if d && cut}<div class="more cut">{`The top ${d.results.length} of ${d.total}, ${by}. `}<a id="show-all" href={href(base, { ...r.q, top: "" })}>{`Show all ${d.total}`}</a></div>{/if}{/snippet}

{#if !host}
  <div data-title="Library"><NeedHost what="The library" verb="needs" /></div>
{:else}
  <div class="wl" data-title={doors ? title : topic ? topic.name + " · Evidence" : allWord}><PageTitle {title} facts={doors ? null : topic ? topic.name : "All topics"} /><div class="tb"><span class="tbn filters"><FilterBar r={{ path: base.split("/"), q: r.q, sel: null }} base={base} placeholder={placeholder} selects={selects as never} /><span class="grow"></span><button class="btn sm" id="mark-seen" title="Mark everything seen (⇧a)" onclick={(e) => void markSeen(e.currentTarget)}>Mark all seen</button></span></div>
    {#if !d}
      <Loading error={c?.error} />
    {:else}
      {#if !topic}
        {#if r.q.cluster}<div class="flash blue" role="status"><Icon name="dot" /><div class="grow">{"One cluster from the latest map: "}<strong>{d.cluster_label || "cluster " + r.q.cluster}</strong>{". "}<a href={href("library/clusters/" + r.q.cluster)}>About this cluster</a>{" · "}<a href={href("library", { ...r.q, cluster: "" })}>Show everything</a></div></div>{/if}
        {#if r.q.theme}<div class="flash blue" role="status"><Icon name="dot" /><div class="grow">{"One Parallax theme, as Parallax last clustered it: "}<strong>{themeName}</strong>{". "}<a href={href("library/clusters")}>All Parallax themes</a>{" · "}<a href={href("library", { ...r.q, theme: "" })}>Show everything</a></div></div>{/if}
        {#if r.q.source === "parallax" && !r.q.theme}<p class="quiet-topics">The Parallax archive: what Parallax's interns kept from April to June 2026, imported with the time each was observed, so none of it is new here. Kept forever: compaction never removes it.</p>{/if}
        {#if d.progress}<div class="flash blue" role="status"><Icon name="dot" /><div>{d.progress + " Until then the library is browsable and searchable here."}</div></div>{/if}
        {#if qq.meaning && d.closest != null}<div class="flash amber" role="status"><Icon name="warn" /><div>{`The library may not cover this: the closest observation scores ${n2(d.closest)}, below ${n2(d.off_topic_below)}, which is as close as queries about unrelated subjects get. The nearest observations are shown anyway.`}</div></div>{/if}
        {#if qq.meaning}<p class="quiet-topics">{`The ${plural(d.total, "observation")} that best match "${d.query}". Observations more than ${n2(d.cutoff)} less similar than the closest are left out.`}</p>
        {:else if d.compacted && d.compacted.n}<p class="quiet-topics">{"Older ones were compacted: "}{plural(d.compacted.replaced, "observation")}{" live on as "}<a href="#/library/rollups">{plural(d.compacted.n, "weekly rollup")}</a>.</p>{/if}
      {/if}
      {#if pc?.data}
        <Group id="ev-pin" title="Open in the pane" kind="obs">{@render row(pc.data, -1)}</Group>
      {/if}
      {#if d.results.length}
        {#if fresh.length}
          <Group id="ev-new" title="New since your last visit" count={String(marked ? d.new_total : fresh.length)} kind="obs">
            {#snippet right()}<span class="muted">{d.seen_at ? `since ${visitWord(dt(d.seen_at))}` : "in the last 24 hours"}</span>{/snippet}
            {#each fresh as o (o.id)}{@render row(o, d.results.indexOf(o))}{/each}
            {#snippet foot()}{#if !seen.length}{@render cutLine()}{/if}{/snippet}
          </Group>
        {/if}
        {#if seen.length}
          <Group id="ev-seen" title={qq.meaning ? "Best matches" : "Seen before"} count={String(marked ? d.total - d.new_total : seen.length)} kind="obs">
            {#snippet right()}<span class="muted">{qq.meaning ? "by meaning and by the words used" : cut ? `the top ${d.results.length}, ${by}` : by}</span>{/snippet}
            {#each seen as o (o.id)}{@render row(o, d.results.indexOf(o))}{/each}
            {#snippet foot()}{@render cutLine()}{/snippet}
          </Group>
        {/if}
      {:else}
        <p class="empty">{narrowed ? "Nothing matches." : topic ? "Nothing kept from this topic yet." : "Nothing here yet."}</p>
      {/if}
      {#if !topic && qq.meaning && (d.rollups || []).length}
        <Group id="ev-rollups" title="Compacted weeks" count={String((d.rollups || []).length)} kind="rollups">
          {#snippet right()}<a href={href("library/rollups", { q: d.query })}>All matching rollups</a>{/snippet}
          {#each d.rollups || [] as x (x.id)}<RollupLine {x} {base} q={r.q} />{/each}
        </Group>
      {/if}
      <Pager {base} q={r.q} at={qq.at} {pages} />
    {/if}
  </div>
{/if}
