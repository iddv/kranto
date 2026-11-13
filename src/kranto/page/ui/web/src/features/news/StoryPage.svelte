<script lang="ts">
  // One page a story (#/news/i/:brief/:n): the item's page and the article's
  // page as one. #/news/a/:id lands here (it reads the article, then replaces the address with its
  // story's). The crumb News › Robotics › Wed 11 Nov, the headline, one facts line ("Story 1 of 5 ·
  // 12 sources · 2 min read · written 11 Nov"), the standfirst (else the story's own lines) as the
  // lede, Write a post the one primary. Why it matters as a box: the why line, the article's own
  // idea seed, the story's idea (by rule from stored rows), or Idea from this on its theme,
  // or why there is none. Then the article in its own order (What happened and its numbers, the
  // rest under "Read on"), or Write the full story; the sources, four shown; Today and Next.
  import Empty from "../../ui/Empty.svelte";
  import Loading from "../../ui/Loading.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import Page from "../../pages/Page.svelte";
  import { plural } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { ui } from "../../lib/shell.svelte";
  import NewsSources from "./NewsSources.svelte";
  import { writePost } from "../post/post";
  import { ROWS, articlePath, briefPagePath, dayWords, deepDive, ideaFromThis, ideaHref, shortDay, storyHref, storyKey, type Article, type Brief, type Para, type TopicRows } from "./news";

  let { view }: { view: View } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const kind = $derived(view.w.r.path[1] || "i");
  // #/news/a/:id: the article's own address lands on its story
  const aid = $derived(kind === "a" ? view.w.r.path[2] || "" : "");
  const landing = $derived.by(() => {
    void view.tick;
    return host && aid ? read<Article>(articlePath(aid), 60000) : null;
  });
  $effect(() => {
    const a = landing?.data;
    if (a) location.replace(storyHref(a.brief_id, a.item_n));
  });
  const bid = $derived(kind === "i" ? view.w.r.path[2] || "" : "");
  const n = $derived(Number(view.w.r.path[3] || 0));
  let asked = $state(false);
  let polling = $state(false);
  let pressedAt = 0;
  const c = $derived.by(() => {
    void view.tick;
    return host && bid ? read<Brief>(briefPagePath(bid), polling ? 5000 : 60000) : null;
  });
  const b = $derived(c?.data || null);
  const x = $derived(b ? b.items[n] || null : null);
  const item = $derived(b?.articles?.[String(n)] || null);
  const ac = $derived.by(() => {
    void view.tick;
    return host && item?.status === "ok" ? read<Article>(articlePath(item.id), 60000) : null;
  });
  const a = $derived(ac?.data && ac.data.status === "ok" ? ac.data : null);
  const art = $derived(a?.body || null);
  const s = $derived(b?.stories?.[String(n)] || null);
  $effect(() => {
    if (asked && item && !item.running && Date.parse(item.created_at) > pressedAt) asked = false;
    polling = asked || !!item?.running;
  });
  const canWrite = $derived(!!x && (x.observation_ids || []).length > 0 && !item?.running && !asked && item?.status !== "ok");
  const write = (btn: HTMLElement | null) => deepDive(btn, b!.id, n, x!.headline, () => {
    pressedAt = Date.now() - 1000;
    asked = true;
  });
  const topics = $derived.by(() => {
    void view.tick;
    return host ? read<TopicRows>(ROWS, 60000).data : null;
  });
  const name = $derived(b ? topics?.topics.find((t) => t.id === b.topic_id)?.name || `topic ${b.topic_id}` : "");
  const fresh = $derived((b?.items || []).map((it, i) => ({ it, i })).filter((q) => !q.it.background));
  const place = $derived(fresh.findIndex((q) => q.i === n));
  const next = $derived.by(() => {
    const all = (b?.items || []).map((it, i) => ({ it, i }));
    const k = all.findIndex((q) => q.i === n);
    return k >= 0 && k + 1 < all.length ? all[k + 1] : null;
  });
  const sources = $derived(a ? a.sources : x?.sources || []);
  const first = $derived(art ? art.sections[0] || null : null);
  const rest = $derived(art ? art.sections.slice(1) : []);
  const restWords = $derived(rest.reduce((k, sec) => k + sec.paragraphs.reduce((w, p) => w + p.text.split(/\s+/).length, 0), 0));
  const nth = $derived(new Map((a?.sources || []).map((q, i) => [q.label, i + 1])));
  const sup = (p: { cites?: string[] }): string => (p.cites || []).map((l) => nth.get(l)).filter((k) => k != null).join(",");
  const facts = $derived(b && x ? [x.background ? "From earlier" : `Story ${place + 1} of ${fresh.length}`, plural(sources.length, "source"), a ? `${a.minutes} min read` : null, `written ${shortDay(b.created_at)}`].filter(Boolean).join(" · ") : "");
  const crumbDay = $derived(b ? dayWords(b.created_at) : "");
  const hint = $derived(art?.idea_seed || x?.headline || "");
</script>

{#snippet paras(ps: Para[])}
  {#each ps as p, i (i)}<p>{p.text}{#if sup(p)}<sup class="cite" title="Sources">{sup(p)}</sup>{/if}</p>{/each}
{/snippet}

{#if !host}
  <div data-title="News"><NeedHost what="News" verb="needs" /></div>
{:else if kind === "a"}
  <Page head={{ title: "A story", label: `Story ${aid}`, crumb: [{ to: "news", w: "Today" }] }}>
    {#snippet body()}{#if landing?.error && /no such article/.test(String(landing.error))}<Empty text="This story is not here: it may have been written on another install, or the address is wrong." link={{ href: "#/news", w: "News ›" }} />{:else}<Loading error={landing?.error} what="the story" />{/if}{/snippet}
  </Page>
{:else if !b}
  <Page head={{ title: "A story", crumb: [{ to: "news", w: "Today" }] }}>{#snippet body()}<Loading error={c?.error} what="the story" />{/snippet}</Page>
{:else if !x}
  <Page head={{ title: "A story", crumb: [{ to: "news", w: "Today" }] }}>{#snippet body()}<Empty text={`The brief of ${crumbDay} has no story ${n + 1}.`} link={{ href: "#/news", w: "Today ›" }} />{/snippet}</Page>
{:else}
  <Page head={{ title: x.headline, label: x.headline, crumb: [{ to: href("news", { topic: String(b.topic_id) }).slice(2), w: name }, { to: href("news", { s: storyKey(b.id, n) }).slice(2), w: crumbDay }],
      facts, lede: a?.standfirst || x.body, gear: "settings/news",
      primary: { label: "Write a post", id: "story-write", run: () => writePost({ brief: b.id, n, title: x.headline, sources: x.sources.filter((q) => q.url).length }), title: "A blog post about this story, as a draft on Post" } }}
    sections={[{ id: "why", w: "Why it matters" }, ...(first ? [{ id: "what", w: first.title }] : [{ id: "full", w: "The full story" }])]} evidenceWord={`Sources (${sources.length})`}>
    {#snippet section(sec)}
      {#if sec.id === "why"}
        <div class="why-box" id="story-why">
          {#if x.why}<p>{x.why}</p>{/if}
          {#if art?.idea_seed}<p class="small"><strong>An idea in it ·</strong> {art.idea_seed}</p>{/if}
          {#if s?.idea}<p class="small" id="story-idea">Idea · <a href={ideaHref(s.idea.id)}>{`#${s.idea.id} ${s.idea.title}`}</a>{s.idea.state ? ` · ${s.idea.state}` : ""}{s.idea.more ? ` · and ${s.idea.more} more` : ""}</p>{/if}
          <p class="acts">
            {#if !s?.idea && s?.theme}<button type="button" class="btn sm" id="story-idea-from" onclick={(e) => ideaFromThis(e.currentTarget, s, hint)}>Idea from this</button>{/if}
            <a class="btn sm quiet" href={href("ideas", { topic: String(b.topic_id) })}>{`Ideas from ${name} ›`}</a>
          </p>
          {#if !s?.idea && !s?.theme && s?.no_theme}<p class="muted small" id="story-no-idea">{s.no_theme}</p>{/if}
        </div>
      {:else if sec.id === "what" && first}
        {@render paras(first.paragraphs)}
        {#if art?.numbers.length}<ul class="tiles" id="story-numbers">{#each art.numbers as q, i (q.label + i)}<li><span class="v">{q.value}<span class="u">{q.unit}</span></span><span class="l">{q.label}</span></li>{/each}</ul>{/if}
        {#if rest.length}
          <details class="read-on" id="story-read-on"><summary>{`Read on: ${rest.map((r) => r.title).join(" · ")} (${restWords} words)`}</summary>
            {#each rest as r (r.id)}<h3>{r.title}</h3>{@render paras(r.paragraphs)}{/each}
          </details>
        {/if}
      {:else}
        {#if item?.running || asked}<p class="muted" id="story-writing">Writing the full story: it shows here in a minute or so.</p>
        {:else if canWrite}<p class="muted small">{item?.status === "failed" ? `The full story could not be written: ${item.error || "no reason given"}.` : item?.status === "quiet" ? `No full story: ${item.quiet || "the material did not carry one"}.` : "Only the brief's lines so far. The full story reads the pages behind it (about 10 cents)."}</p><p><button type="button" class="btn sm" id="story-full" onclick={(e) => write(e.currentTarget)}>Write the full story</button></p>
        {:else}<p class="muted small" id="story-no-full">No full story: only search results back this one.</p>{/if}
      {/if}
    {/snippet}
    {#snippet evidence()}
      <NewsSources sources={sources.slice(0, 4)} numbered />
      {#if sources.length > 4}<details class="small" id="story-all-sources"><summary>{`All ${sources.length} sources`}</summary><NewsSources sources={sources.slice(4)} numbered /></details>{/if}
    {/snippet}
    {#snippet foot()}
      <p class="story-nav small"><a href={href("news", { s: storyKey(b.id, n) })}>‹ Today</a>{#if next}<a href={storyHref(b.id, next.i)} id="story-next">{`Next: ${next.it.headline} ›`}</a>{/if}</p>
    {/snippet}
  </Page>
{/if}

<style>
  .why-box { border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; background: var(--box); }
  .why-box p { margin: 4px 0; }
  .cite { color: var(--muted); font-size: 0.7em; margin-left: 2px; }
  .tiles { list-style: none; padding: 0; margin: 12px 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 8px; }
  .tiles li { border: 1px solid var(--border); border-radius: 8px; padding: 8px 12px; background: var(--box); display: flex; flex-direction: column; }
  .tiles .v { font-size: 1.4em; color: var(--ink); }
  .tiles .u { font-size: 0.7em; margin-left: 2px; color: var(--ink2); }
  .tiles .l { color: var(--muted); font-size: 0.85em; }
  .read-on summary { cursor: pointer; color: var(--ink2); margin: 8px 0; }
  .story-nav { display: flex; justify-content: space-between; gap: 12px; margin-top: 16px; flex-wrap: wrap; }
  @media (max-width: 640px) { .tiles { grid-template-columns: 1fr 1fr; } }
</style>
