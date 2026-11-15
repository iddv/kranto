<script lang="ts">
  // A topic's Overview (WORKSPACE.md 8, W3): a digest of its pages, each group with its "all"
  // link: its sources first (proposals, then the five that keep the most; TopicSourceRows,
  // which the topic's Sources page draws too), its themes (rising first), the ideas waiting, the top evidence by signal (new since your
  // visit when there is any). The toolbar says what is new and links the proposals waiting for
  // you. The idea cards are one read (pages/ideas/cards.ts's topicWork); an idea's row is Ideas'
  // card row (CardLine). With the doors on, the page's one head is the topic's:
  // its name and state, its facts in one line, its description, Edit the primary, Add source,
  // Scout more, Pause and Archive under ⋯, its Activity line, one flash (paused, or proposals
  // waiting).
  import { topicWork } from "../ideas/cards";
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import Loading from "../../ui/Loading.svelte";
  import RunLine from "../../ui/RunLine.svelte";
  import Icon from "../../shell/Icon.svelte";
  import { plural } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { ui } from "../../lib/shell.svelte";
  import CardLine from "../ideas/CardLine.svelte";
  import type { CardX } from "../ideas/ideas";
  import ObsLine from "../library/ObsLine.svelte";
  import ThemeLine from "../library/ThemeLine.svelte";
  import { gradesPath, type FeedbackGrades, type Observations, type ObsRow } from "../library/library";
  import { TODAY_API, topThemes, type Today, type TopicPage } from "./topics";
  import TopicSourceRows from "./TopicSourceRows.svelte";
  import TopicStart from "./TopicStart.svelte";
  import { go } from "../../lib/router";
  import type { HeadDecl } from "../../lib/app/heads";
  import { archiveTopic, editTopic, pauseTopic, restoreTopic } from "./topicedit";
  import { scoutMore } from "./scout";
  import { tokText } from "../../lib/format";

  let { view, t }: { view: View; t: TopicPage } = $props();
  const base = $derived("topics/" + t.id);
  // what is new since your visit, from Today's read (the navigator's "N new" is the same)
  const nw = $derived.by(() => {
    void view.tick;
    return read<Today>(TODAY_API, 60000).data?.topics.find((x) => String(x.id) === String(t.id)) || null;
  });
  const fresh = $derived(!!nw?.new_kept);
  const themes = $derived(topThemes(t.themes_list));
  const work = $derived.by(() => {
    void view.tick;
    return topicWork(t);
  });
  const ideas = $derived(work?.ideas ?? null);
  const open = $derived(ideas && work ? ideas.filter((x) => ["open", "waiting"].includes(work.status(x))).slice(0, 3) : []);
  // its five best observations, by signal (new since your visit when there are new ones)
  const ec = $derived.by(() => {
    void view.tick;
    return read<Observations>("/api/observations?" + new URLSearchParams({ topic: String(t.id), ...(fresh ? { since: "last" } : {}), sort: "signal", limit: "5" }), 60000);
  });
  const ev = $derived(ec.data ? ec.data.results : null);
  const G = $derived.by(() => {
    void view.tick;
    return ev && ev.length ? read<FeedbackGrades>(gradesPath(ev.map((o) => o.id)), 30000).data?.grades || {} : {};
  });
  const gradeOf = (o: ObsRow, k: number) => ({ current: G[String(o.id)] || o.grade, position: k + 1 });
  // the new frame's door head names the topic above this list (the classic frame has its crumb only)
  const doorsFrame = $derived(!!ui.facts?.door && !ui.facts.door.crumbOnly);
  let scouting = $state<string | null>(null);
  const tokens = $derived(t.tokens_month ? tokText(t.tokens_month) : null);
  /** the topic's head (the shell draws it): its words, its verbs, its line and its one flash */
  const head = $derived.by((): Partial<HeadDecl> => {
    const archived = t.status === "archived";
    return {
      tags: t.status === "active" ? null : [{ w: t.status, cls: "amber" }],
      facts: [nw && nw.new_kept ? `${nw.new_kept} new since your visit` : null, plural(t.sources, "source"), `${t.kept_per_day} kept a day of ${t.items_per_day}`,
        tokens ? `${tokens} this month` : null].filter(Boolean).join(" · "),
      lede: t.description || null,
      primary: archived ? { label: "Restore", id: "restore-topic", run: (b) => void restoreTopic(b, t) } : { label: "Edit", id: "topic-edit", title: "Its name, description, sources and settings", run: () => editTopic(t.id) },
      more: archived ? [{ label: "Edit", id: "topic-edit-more", run: () => editTopic(t.id) }] : [
        { label: "Add source", id: "topic-add-source", run: () => go("settings/sources/new", { topic: String(t.id) }) },
        { label: scouting || "Scout more", id: "scout-more", run: (b) => void scoutMore(b, t, (w) => (scouting = w)) },
        { label: t.status === "paused" ? "Resume topic" : "Pause topic", id: "pause-topic", run: (b) => pauseTopic(b, t) },
        { label: "Archive", id: "archive-topic", title: "Off your lists and not read; its evidence and ideas stay (Undo brings it back)", run: (b) => void archiveTopic(b, t) }],
      line: "topic:" + t.id, lineId: "topic-run-line",
      flash: t.status === "paused" ? { kind: "amber", text: "Paused: this topic's sources are not read. Its evidence, themes and ideas stay.", link: null }
        : t.proposed ? { kind: "amber", text: `${plural(t.proposed, "source")} proposed, waiting for you.`, link: { href: href(`topics/${t.id}/sources`), w: "Review ›" } } : null,
    };
  });
</script>

{#snippet empty(text: string)}<p class="more">{text}</p>{/snippet}

<!-- with the doors on, the topic's head is the shell's (its declaration, above): these are its sections -->
{#snippet tools()}<span class="tbn twrap"><span>{[nw ? `${nw.new_kept} new since your visit` : null, plural(t.sources, "source"), `${t.kept_per_day} kept a day`].filter(Boolean).join(" · ")}</span><span class="grow"></span>{#if t.proposed}<a class="btn sm primary" id="proposed-link" href={href(`topics/${t.id}/sources`)}>{`${t.proposed} proposed, waiting for you`}</a>{/if}</span>{/snippet}
<List title={ui.headOn ? t.name : doorsFrame ? "In this topic" : "Overview"} label={t.name} crumb={ui.headOn || doorsFrame ? null : t.name} head={ui.headOn ? head : null} tools={ui.headOn ? undefined : tools}>
  {#if !ui.headOn && t.status === "paused"}<div class="flash amber" role="status"><Icon name="paused" /><div>Paused: this topic's sources are not read. Its evidence, themes and ideas stay. Resume it from the topic's pane.</div></div>{/if}
  <!-- a new topic's first hour: the four rows, until its first idea card -->
  {#if t.status !== "archived"}<TopicStart tid={t.id} at={view.tick} />{/if}
  <!-- what runs for this topic now (its sources' reading, its brief),
       or stopped for you -->
  {#if !ui.headOn}<RunLine subject={"topic:" + t.id} tick={view.tick} id="topic-run-line" />{/if}
  <TopicSourceRows {t} at={view.tick} mode="top" />
  <Group id="ov-themes" title={t.rising ? "Rising themes" : "Themes"} count={String(t.themes)} kind="themes">
    {#snippet right()}{#if t.themes}<a href={href(base + "/themes")}>{`All ${t.themes}`}</a>{/if}{/snippet}
    {#each themes as c (c.cluster)}<ThemeLine {c} {t} at={view.tick} />{/each}
    {#snippet foot()}{#if !themes.length}{@render empty(t.snapshot ? "No cluster in the latest map comes mostly from this topic yet." : "No map yet, so no themes.")}{/if}{/snippet}
  </Group>
  <Group id="ov-ideas" title="Ideas waiting" count={String(open.length)} kind="ideas">
    {#snippet right()}{#if ideas && ideas.length}<a href={href(base + "/ideas")}>{`All ${ideas.length}`}</a>{/if}{/snippet}
    {#each open as x (x.number)}<CardLine x={x as unknown as CardX} {t} />{/each}
    {#snippet foot()}{#if ideas == null}<div class="more"><Loading /></div>{:else if !open.length}{@render empty("No open ideas from this topic.")}{/if}{/snippet}
  </Group>
  <Group id="ov-ev" title={fresh ? "Top evidence, new since your visit" : "Top evidence"} count={fresh && nw ? String(nw.new_kept) : String(t.observations)} kind="obs">
    {#snippet right()}<a href={href(base + "/evidence", fresh ? { since: "last", sort: "signal" } : { sort: "signal" })}>All, by signal</a>{/snippet}
    {#each ev || [] as o, k (o.id)}<ObsLine {o} mute tick isNew={!!o.new} grade={gradeOf(o, k)} />{/each}
    {#snippet foot()}{#if !ev}<div class="more"><Loading error={ec.error} /></div>{:else if !ev.length}{@render empty("Nothing kept from this topic yet.")}{/if}{/snippet}
  </Group>
</List>

<style>
  /* its verbs wrap under the facts rather than push the list sideways */
  .tbn.twrap { flex-wrap: wrap; row-gap: 4px; }
</style>
