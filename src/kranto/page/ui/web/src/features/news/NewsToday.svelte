<script lang="ts">
  // News › Today (#/news with the doors on): one edition a topic a day, scanned
  // as one line a story and read in place. The head says how much there is ("Wednesday 11 November
  // · 5 stories in Robotics · about a minute"). One group a topic, in the owner's order: its name,
  // when it was written, and its waiting ideas. One line a story (its number, headline, first
  // outlet, "full story · 2 min" when it has one); the background folds under "2 from earlier".
  // One story is open at a time (the first topic's first when the page opens; a click, or j/k and
  // enter, opens another in place): what happened, Why it matters, the outlets and days, its idea
  // (chosen by rule from stored rows), and three plain buttons (News has no primary): Read
  // the story or Write the full story, Write a post, Idea from this. The address keeps the open
  // story (?s=<brief>.<n>). A topic with no brief yet is one quiet line with its reason.
  import Loading from "../../ui/Loading.svelte";
  import Empty from "../../ui/Empty.svelte";
  import PageTitle from "../../ui/PageTitle.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import MarkEmpty from "../../ui/MarkEmpty.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { ui } from "../../lib/shell.svelte";
  import { writePost } from "../post/post";
  import { IDEAS_API } from "../../pages/ideas/cards";
  import { HOME_API, type HomeAnswer } from "../home";
  import type { Snippet } from "svelte";
  import { LATEST, ROWS, briefPagePath, clock, earlyWords, deepDive, ideaFromThis, ideaHref, longDay, minutesWords, okArticle, outletsDays, outletsLine, storyHref, storyKey, storyWords, whyNothingRuns, type Brief, type BriefItem, type Latest, type TopicRows } from "./news";

  // bid: one brief's own day (#/news/b/<id>,), drawn in Today's layout
  let { view, bid = "", details }: { view: View; bid?: string; details?: Snippet<[Brief]> } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const rows = $derived.by(() => {
    void view.tick;
    return host ? read<TopicRows>(ROWS, 30000) : null;
  });
  const one = $derived.by(() => {
    void view.tick;
    return host && bid ? read<Brief>(briefPagePath(bid), 60000) : null;
  });
  const latest = $derived.by((): { data: Latest | null; error?: string | null } | null => {
    void view.tick; // each draw may find the reads stale
    if (!host) return null;
    if (!bid) return read<Latest>(LATEST, 30000);
    const b = one?.data;
    if (!b) return { data: null, error: one?.error };
    const name = (rows?.data?.topics || []).find((t) => t.id === b.topic_id)?.name || `topic ${b.topic_id}`;
    return { data: { topics: [{ topic: { id: b.topic_id, name }, brief: b }] } };
  });
  type CardLite = { id: number; state: string; topic: { id: number } | null };
  const ideas = $derived.by(() => {
    void view.tick;
    return host ? read<{ ideas: CardLite[] }>(IDEAS_API, 60000) : null;
  });
  const all = $derived((latest?.data?.topics || []).filter((t) => t.brief && t.brief.status === "ok"));
  const quiet = $derived((latest?.data?.topics || []).filter((t) => t.brief && t.brief.status !== "ok"));
  const title = $derived(bid ? (all[0] || quiet[0])?.topic.name || "A day's stories" : "Today");
  const only = $derived(view.w.r.q.topic || null);
  const shown = $derived(only ? all.filter((t) => String(t.topic.id) === only) : all);
  const stuck = $derived.by(() => {
    void view.tick;
    return whyNothingRuns();
  });
  // the first hour's read, as the home has it: "reading for the first
  // time, 9 kept of 41. The first brief is written as soon as 8 are kept."
  const firstRead = $derived.by(() => {
    void view.tick;
    return host && !bid ? read<HomeAnswer>(HOME_API, 15000).data?.first ?? null : null;
  });
  function firstReading(id: number, name: string): string {
    const f = firstRead && firstRead.topic && firstRead.topic.id === id ? firstRead : null;
    const n = f?.early_kept ?? 8;
    if (f?.read) return `${name}: reading for the first time, ${f.read.kept} kept of ${f.read.judged}. The first brief is written as soon as ${n} are kept.`;
    return `The first brief for ${name} is written as soon as ${n} items are kept in its first read.`;
  }
  // the topics News is on for that have had no brief yet: their first is on its way
  const coming = $derived.by(() => {
    const had = new Set((latest?.data?.topics || []).filter((t) => t.brief).map((t) => String(t.topic.id)));
    return (rows?.data?.topics || []).filter((t) => t.news.enabled && t.status === "active" && !had.has(String(t.id)) && (!only || String(t.id) === only));
  });
  const fresh = (b: Brief): { x: BriefItem; n: number }[] => b.items.map((x, n) => ({ x, n })).filter((s) => !s.x.background);
  const older = (b: Brief): { x: BriefItem; n: number }[] => b.items.map((x, n) => ({ x, n })).filter((s) => s.x.background);
  /** every story in the page's order, for j/k */
  const order = $derived(shown.flatMap((t) => [...fresh(t.brief!), ...older(t.brief!)].map((s) => storyKey(t.brief!.id, s.n))));
  const stories = $derived(shown.reduce((k, t) => k + fresh(t.brief!).length, 0));
  const words = $derived(shown.reduce((k, t) => k + fresh(t.brief!).reduce((w, s) => w + storyWords(s.x), 0), 0));
  const head = $derived(shown[0] || null);
  const day = $derived(head?.brief ? longDay(head.brief.created_at) : "");
  const facts = $derived(!head ? "" : shown.length === 1 ? `${day} · ${stories} ${stories === 1 ? "story" : "stories"} in ${head.topic.name} · ${minutesWords(words)}` : `${day} · ${stories} stories in ${shown.length} topics · ${minutesWords(words)}`);
  // the open story: the address's, else the first topic's first
  let picked = $state<string | null>(null);
  const asked = $derived(String(view.w.r.q.s || ""));
  const open = $derived(picked ?? (order.includes(asked) ? asked : order[0]) ?? null);
  function pick(key: string): void {
    picked = key;
    const q = { ...view.w.r.q, s: key };
    history.replaceState(history.state, "", href(bid ? `news/b/${bid}` : "news", q));
    queueMicrotask(() => document.getElementById("story-" + key.replace(".", "-"))?.scrollIntoView?.({ block: "nearest" }));
  }
  function keys(e: KeyboardEvent): void {
    const t = e.target as HTMLElement | null;
    if (e.metaKey || e.ctrlKey || e.altKey || (t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) || t?.isContentEditable || document.querySelector("dialog[open], .dialog[open], [role=dialog]")) return;
    if (!order.length || !open) return;
    const i = order.indexOf(open);
    const to = e.key === "j" ? order[i + 1] : e.key === "k" && i > 0 ? order[i - 1] : undefined;
    if (to) pick(to);
    else if (e.key === "Enter" && t?.closest?.(".story-row, a, button") == null) {
      const [b, n] = open.split(".");
      location.hash = storyHref(b || "", Number(n));
    } else return;
    e.preventDefault();
  }
  const waiting = (topic: number): number => (ideas?.data?.ideas || []).filter((c) => c.state === "waiting" && c.topic?.id === topic).length;
  const shortName = (s: string): string => (s.length > 60 ? s.slice(0, 59) + "…" : s);
</script>

<svelte:window onkeydown={keys} />

{#snippet story(b: Brief, x: BriefItem, n: number)}
  {@const key = storyKey(b.id, n)}
  {@const art = okArticle(b, n)}
  {@const s = b.stories?.[String(n)]}
  {@const isOpen = open === key}
  <li class={"story" + (isOpen ? " open" : "")} id={"story-" + b.id + "-" + n} data-item={String(n)} data-story={key}>
    {#if !isOpen}
      <button type="button" class="story-row" aria-expanded="false" onclick={() => pick(key)}>
        <span class="st-n">{n + 1}</span><span class="st-h">{x.headline}</span><span class="st-o muted small">{outletsLine(x.sources)}</span>{#if art}<span class="st-full small">{`full story · ${art.minutes} min`}</span>{/if}
      </button>
    {:else}
      <div class="story-open" aria-label={x.headline}>
        <h3><span class="st-n">{n + 1}</span><a href={storyHref(b.id, n)}>{x.headline}</a></h3>
        <p class="st-body">{x.body}</p>
        {#if x.why}<p class="why"><strong>Why it matters ·</strong> {x.why}</p>{/if}
        <p class="muted small st-src">{outletsDays(x.sources)}</p>
        {#if s?.idea}<p class="small st-idea">Idea · <a href={ideaHref(s.idea.id)}>{`#${s.idea.id} ${shortName(s.idea.title)}`}</a>{s.idea.state ? ` · ${s.idea.state}` : ""}{#if s.idea.more}{" · "}<a href={href("ideas", { topic: String(b.topic_id) })}>{`and ${s.idea.more} more ›`}</a>{/if}</p>{/if}
        <p class="acts st-verbs">
          {#if art}<a class="btn sm" href={storyHref(b.id, n)} data-act="read">{`Read the story · ${art.minutes} min`}</a>{:else if (x.observation_ids || []).length}<button type="button" class="btn sm" data-act="full-story" onclick={(e) => deepDive(e.currentTarget, b.id, n, x.headline)}>Write the full story</button>{/if}
          <button type="button" class="btn sm" data-act="write" onclick={() => writePost({ brief: b.id, n, title: x.headline, sources: x.sources.filter((q) => q.url).length })}>Write a post</button>
          {#if !s?.idea && s?.theme}<button type="button" class="btn sm" data-act="idea" onclick={(e) => ideaFromThis(e.currentTarget, s, x.headline)}>Idea from this</button>{/if}
        </p>
      </div>
    {/if}
  </li>
{/snippet}

{#if !host}
  <div data-title="News"><NeedHost what="News" verb="needs" /></div>
{:else}
  <div class="wl news-today" data-title="News"><PageTitle {title} facts={facts || null} />
    {#if !latest?.data}
      <Loading error={latest?.error} />
    {:else if rows?.data && !rows.data.enabled}
      <Empty text="News is off: it writes no brief until it is on." link={{ href: "#/settings/news", w: "Settings › News ›" }} />
    {:else if !shown.length && !coming.length && !quiet.length}
      <MarkEmpty text="No brief yet. A new topic's first brief is written right after its first read." />
    {:else}
      {#each shown as t (t.topic.id)}
        {@const b = t.brief!}
        {@const w = waiting(t.topic.id)}
        {@const bg = older(b)}
        <section class="brief day" aria-labelledby={"brief-" + b.id} data-brief={String(b.id)}>
          <h2 id={"brief-" + b.id}>{t.topic.name}<span class="muted small">{` · written at ${clock(b.created_at)}`}</span>{#if w}<a class="small day-ideas" href={href("ideas", { topic: String(t.topic.id) })}>{`${w} ${w === 1 ? "idea" : "ideas"} from ${t.topic.name} ${w === 1 ? "waits" : "wait"} ›`}</a>{/if}</h2>
          {#if b.trigger === "first_read"}<p class="muted small first-read">From the first read. Tomorrow's covers a day.</p>{:else if b.trigger === "first_early"}<p class="muted small first-read">{earlyWords(b)}</p>{/if}
          <ol class="stories">{#each fresh(b) as s (s.n)}{@render story(b, s.x, s.n)}{/each}</ol>
          {#if bg.length}<details class="earlier-stories" open={bg.some((s) => open === storyKey(b.id, s.n))}><summary class="small muted">{`${bg.length} from earlier ▾`}</summary><ol class="stories">{#each bg as s (s.n)}{@render story(b, s.x, s.n)}{/each}</ol></details>{/if}
        </section>
      {/each}
      {#each quiet as t (t.topic.id)}<p class="muted small quiet-topic" data-topic={String(t.topic.id)}>{t.brief!.status === "quiet" ? `${t.topic.name}: a quiet day. ${t.brief!.quiet || ""}` : `${t.topic.name}'s brief could not be written. `}{#if t.brief!.status !== "quiet"}<a href={href("news/topics")}>News › Topics ›</a>{/if}</p>{/each}
      {#if bid && one?.data && details}{@render details(one.data)}{/if}
      {#each bid ? [] : coming as t (t.id)}{#if stuck}<p class="muted small first-brief" data-topic={String(t.id)}>{`No brief for ${t.name} yet. ${stuck.text} `}{#if stuck.link}<a href={stuck.link.href}>{stuck.link.w}</a>{/if}</p>{:else}<p class="muted small first-brief" data-topic={String(t.id)}>{firstReading(t.id, t.name)}</p>{/if}{/each}
      <p class="muted small news-foot">{bid ? "" : "Written every day at the topic's hour · "}<a href={href("news/earlier")}>Earlier days ›</a></p>
    {/if}
  </div>
{/if}

<style>
  .stories { list-style: none; padding: 0; margin: 4px 0 8px; }
  .story-row { display: flex; gap: 8px; align-items: baseline; width: 100%; text-align: left; background: none; border: 0; border-top: 1px solid var(--border); padding: 7px 2px; color: var(--ink); cursor: pointer; font: inherit; }
  .story-row:hover { background: var(--hover, var(--box)); }
  .st-n { color: var(--muted); min-width: 1.2em; font-variant-numeric: tabular-nums; }
  .st-h { flex: 1 1 auto; }
  .st-o { white-space: nowrap; }
  .st-full { color: var(--violet); white-space: nowrap; }
  .story-open { border-top: 1px solid var(--border); padding: 8px 2px 10px; }
  .story-open h3 { margin: 0 0 4px; font-size: 1.05em; display: flex; gap: 8px; }
  .story-open p { margin: 4px 0; }
  .day h2 { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  .day-ideas { margin-left: auto; }
  .earlier-stories summary { cursor: pointer; padding: 4px 2px; }
  @media (max-width: 640px) {
    .story-row { flex-wrap: wrap; }
    .st-h { flex-basis: calc(100% - 2em); }
    .st-o { padding-left: 2em; }
    .day-ideas { margin-left: 0; flex-basis: 100%; }
  }
</style>
