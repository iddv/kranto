<script lang="ts">
  // A topic in the pane (WORKSPACE.md 2.7; the old page's paneTopic): its facts (the sources'
  // number links to its Sources), what is rising now; Open the topic (away from its pages), Add source, Scout more (the
  // scout's job, polled; its close matches ticked on the topic's Sources, which it opens), Edit
  // (the sheet: its words, sources and settings;), Pause topic or Resume topic and Archive (with
  // Undo). At most three verbs in the head: on its own pages Edit, Add source and Scout more, the
  // rest under ⋯; on the Topics node, Open the topic, Edit and ⋯. An archived topic says so, with
  // Restore.
  import { scoutMore } from "./scout";
  import Glyph from "../../ui/Glyph.svelte";
  import Loading from "../../ui/Loading.svelte";
  import Pane, { type Sec } from "../../ui/Pane.svelte";
  import Icon from "../../shell/Icon.svelte";
  import { pct, plural, tokText, tokTitle } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { go, href } from "../../lib/router";
  import { app } from "../../lib/shell.svelte";
  import ThemeLine from "../library/ThemeLine.svelte";
  import { archiveTopic, editTopic, pauseTopic, restoreTopic } from "./topicedit";
  import { noTopic, TODAY_API, topicApi, topicSt, type Today, type TopicPage } from "./topics";

  let { view, id }: { view: View; id: string } = $props();
  const c = $derived.by(() => {
    void view.tick; // each draw may find the reads stale
    return read<TopicPage>(topicApi(id), 20000);
  });
  const t = $derived(c.data);
  const nw = $derived.by(() => {
    void view.tick;
    return read<Today>(TODAY_API, 60000).data?.topics.find((x) => String(x.id) === String(t?.id)) || null;
  });
  // on one of the topic's own pages there is no Open the topic
  const here = $derived(!!t && (view.w.node === "topics/" + t.id || (view.w.node || "").startsWith("topics/" + t.id + "/")));
  // its sources are the page's Sources section and the topic's Sources page (the owner's
  // O-2: Best sources retired from the head): here, the Facts tile's number links there
  const secs = $derived.by((): Sec[] => !t ? [] : [{ id: "facts", w: "Facts" },
    ...(t.rising_now.length ? [{ id: "rising", w: "Rising now", n: t.rising_now.length }] : []),
    ...(t.progress && !t.snapshot ? [{ id: "progress", w: "The first map" }] : [])]);
  let scouting = $state<string | null>(null);

  /** Scout more (scout.ts; the Edit sheet has it too): its close matches are ticked on the
   * topic's Sources, which it opens */
  function scout(btn: HTMLElement | null, x: TopicPage): void {
    void scoutMore(btn, x, (w) => (scouting = w));
  }
  /** Pause topic (its sources are not read; nothing is removed), or Resume topic */
  const pause = (btn: HTMLElement | null, x: TopicPage): void => pauseTopic(btn, x);
  function more(anchor: HTMLElement, x: TopicPage, mine: boolean): void {
    app()?.menu(anchor, [
      ...(mine ? [] : [{ label: "Add source", id: "topic-add-source", run: () => go("settings/sources/new", { topic: String(x.id) }) },
        { label: scouting || "Scout more", id: "scout-more", run: () => scout(null, x) }]),
      { label: x.status === "paused" ? "Resume topic" : "Pause topic", id: "pause-topic", run: () => pause(null, x) },
      { label: "Archive", id: "archive-topic", title: "Off your lists and not read; its evidence and ideas stay (Undo brings it back)", run: () => void archiveTopic(null, x) }]);
  }
</script>

{#snippet fact(k: string, v: import("svelte").Snippet, small: import("svelte").Snippet | string | null)}<div class="fact"><dt>{k}</dt><dd>{@render v()}</dd>{#if small}<small>{#if typeof small === "string"}{small}{:else}{@render small()}{/if}</small>{/if}</div>{/snippet}

{#if !t}
  <div class="pane-in" data-title="Topic">{#if noTopic(c.error)}<p class="empty">{`No topic ${id}.`}</p>{:else}<Loading error={c.error} />{/if}</div>
{:else}
  {@const m = topicSt(t.status)}
  {@const x = t}
  <Pane title={t.name} lede={t.description} sections={secs}>
    {#snippet kind()}<Glyph name={m[0]} colour={m[1]} word={m[2]} />{" topic · " + m[2].toLowerCase()}{/snippet}
    {#snippet acts()}{#if x.status === "archived"}<button class="btn sm primary" id="restore-topic" onclick={(e) => void restoreTopic(e.currentTarget, x)}>Restore</button><button class="btn sm" id="topic-edit" title="Its name, description, sources and settings" onclick={() => editTopic(x.id)}>Edit</button>{:else}{#if !here}<a class="btn sm primary" href={href("topics/" + x.id)}>Open the topic</a>{/if}<button class={"btn sm" + (here ? " primary" : "")} id="topic-edit" title="Its name, description, sources and settings" onclick={() => editTopic(x.id)}>Edit</button>{#if here}<a class="btn sm" id="topic-add-source" href={href("settings/sources/new", { topic: x.id })}>Add source</a><button class="btn sm" id="scout-more" onclick={(e) => scout(e.currentTarget, x)}>{scouting || "Scout more"}</button>{/if}<button type="button" class="btn sm more" aria-haspopup="menu" aria-label="More actions" title="More actions (.)" onclick={(e) => more(e.currentTarget, x, here)}>⋯</button>{/if}{/snippet}
    {#snippet top()}{#if x.status === "paused"}<div class="note c-amber" role="status"><Icon name="paused" /><div>Paused: this topic's sources are not read. Its evidence, themes and ideas stay. Click Resume topic to read again.</div></div>{:else if x.status === "archived"}<div class="note c-amber" role="status"><Icon name="paused" /><div>Archived: not read, and off your lists. Its evidence, themes and ideas stay. Restore brings it back.</div></div>{/if}{/snippet}
    {#snippet section(s)}
      {#if s.id === "facts"}
        {#snippet fresh()}{nw ? String(nw.new_kept) : "–"}{/snippet}
        {#snippet kept()}{#if nw}<a href={href(`topics/${x.id}/evidence`, { since: "last" })}>kept</a>{x.rising ? ` · ${plural(x.rising, "rising theme")}` : ""}{:else}reading…{/if}{/snippet}
        {#snippet srcs()}<a id="topic-sources-link" href={href(`topics/${x.id}/sources`)} title={`Sources of ${x.name}`}>{String(x.sources)}</a>{/snippet}
        {#snippet waiting()}{#if x.proposed}<a href={href(`topics/${x.id}/sources`)}>{`${x.proposed} proposed, waiting for you`}</a>{:else}watched · <a href={href(`topics/${x.id}/sources`)}>{`all ${x.sources} ›`}</a>{/if}{/snippet}
        {#snippet perDay()}{String(x.kept_per_day)}{/snippet}
        {#snippet toks()}{#if x.tokens_month}<span class="tok" title={tokTitle(x.tokens_month)}>{tokText(x.tokens_month)}</span>{:else}none yet{/if}{/snippet}
        <dl class="facts">{@render fact("New since your visit", fresh, kept)}{@render fact("Sources", srcs, waiting)}{@render fact("Kept a day", perDay, x.items_per_day ? `of ${x.items_per_day} fetched · ${pct(x.kept_per_day / x.items_per_day)} kept` : "nothing fetched in 7 days")}{@render fact("Tokens this month", toks, "judging this topic's items")}</dl>
      {:else if s.id === "rising"}
        <ul class="lst pl themes">{#each x.rising_now as c (c.cluster)}<ThemeLine {c} t={x} at={view.tick} />{/each}</ul>
      {:else}
        <p class="muted">{x.progress}</p>
      {/if}
    {/snippet}
  </Pane>
{/if}
