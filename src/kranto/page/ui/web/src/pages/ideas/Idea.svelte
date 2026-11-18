<script lang="ts">
  // An idea card's sheet: its state, its number, its title, the topics
  // with their shares, its theme and when it was written; Write a post (the primary), Pass and
  // Later (p l) in the head and Details; a note while it is put off; then the card: the grade, the
  // thesis and the sites of its sources (decision D4). Its evidence, signals, score
  // and why it was written are its Details (kranto_details card:<n>). The verbs are verbs.ts's
  // (passIdea, laterIdea: the row's menu and ⌘K share them).
  import { openDetails } from "../../ui/details.svelte";
  import { laterIdea, passIdea } from "./verbs";
  import { writePost } from "../../features/post/post";
  import { shortDay, storyHref } from "../../features/news/news";
  import { cardIdeas, cardX } from "./cards";
  import Clamp from "../../ui/Clamp.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import GradeHead from "../../ui/GradeHead.svelte";
  import Pane, { type Sec } from "../../ui/Pane.svelte";
  import Tip from "../../ui/Tip.svelte";
  import Icon from "../../shell/Icon.svelte";
  import { pct, rel } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { app } from "../../lib/shell.svelte";
  import { canDecide, ideaNo, ideaTitle, isDispatch, laterUntil, PITCH_KIND, srcWord, stOf, type Cited, type Idea } from "./ideas";

  let { view, i }: { view: View; i: Idea } = $props();
  const c = $derived(i.card);
  const title = $derived(ideaTitle(i));
  const s = $derived(stOf(i.status));
  // the card as the server's /api/ideas sends it (its topics, theme, evidence, grade and rank); a
  // dispatch card is not in the default list, so its one-card read
  const one = $derived.by(() => {
    void view.tick;
    if (!c || c.number == null || !app()?.host()) return null;
    return read<Record<string, unknown>>(`/api/ideas/${encodeURIComponent(String(c.number))}?embedding=ref`, 60000).data || null;
  });
  const x = $derived.by(() => {
    void view.tick; // the cards' read, read again on its schedule
    const ci = c && app()?.host() ? cardIdeas() : null;
    const hit = ci && ci.from === "api" ? ci.list.find((k) => k.number === Number(c?.number)) || null : null;
    return hit || (one && one.id != null ? cardX(one) : null);
  });

  // "In the news": the newest story that matches the card by rule (the card's own read)
  const news = $derived.by(() => {
    const n = one?.news as { brief_id: number; n: number; headline: string; date: string } | null | undefined;
    return n && typeof n.brief_id === "number" ? n : null;
  });
  // the head's verbs: Write a post (the primary), Pass, Later
  type Act = "write" | "pass" | "later";
  const acts = $derived.by((): Act[] => {
    const out: Act[] = canDecide(i) ? ["pass", "later"] : [];
    if (c && c.number != null) out.unshift("write");
    return out;
  });
  const btns: Partial<Record<Act, HTMLElement>> = $state({});
  const anchor = (a: Act): HTMLElement => btns[a]?.isConnected ? (btns[a] as HTMLElement) : document.createElement("button");
  function run(a: Act, el: HTMLElement | null): void {
    if (!app()) return;
    if (a === "write" && c && c.number != null) writePost({ card: Number(c.number), title, sources: new Set(ev.map((e) => e.url).filter(Boolean)).size });
    else if (a === "pass") passIdea(el || anchor("pass"), i);
    else if (a === "later") void laterIdea(el, i);
  }
  const WORD: Record<Act, string> = {
    write: "A blog post or a short post about this card, as a draft on Post",
    pass: "Grade it not useful, say why, and close it (p)",
    later: "Put it off for a week: not waiting for you (l)",
  };
  // the keys of the head's verbs (keys.json's Decide group): p, l
  $effect(() => {
    void view.tick; // the page's keys are set again on every draw
    const L = app();
    if (!L) return;
    if (acts.includes("pass")) L.pageKey("p", () => run("pass", anchor("pass")));
    if (acts.includes("later")) L.pageKey("l", () => run("later", btns.later?.isConnected ? btns.later : null));
  });

  // the sheet is the thesis and its sources (decision D4); every other field is
  // under Details. A dispatch card says who it is for and the dispatch's argument
  const brief = $derived(!!c && !isDispatch(i));
  const fields = $derived(!c ? [] : brief ? ([["Thesis", c.thesis || c.insight]] as [string, string | null | undefined][]).filter((f) => f[1])
    : ([["For", c.who], ["The dispatch's argument", c.thesis]] as [string, string | null | undefined][]).filter((f) => f[1]));
  const ev = $derived((x && (x.evidence || []).length ? x.evidence : c ? (c.evidence as Cited[]) || [] : []) as Cited[]);
  /** the card's sources as one line of sites: each site once; their links are in Details */
  const srcs = $derived.by((): [string, string][] => {
    if (!brief) return [];
    const seen = new Map<string, string>();
    for (const e of ev) {
      if (!e.url) continue;
      let site = "";
      try { site = new URL(e.url).hostname.replace(/^www\./, ""); } catch { continue; }
      if (site && !seen.has(site)) seen.set(site, e.url);
    }
    return [...seen.entries()].slice(0, 5);
  });
  // a project's topic ("Receipts (project)") is not the owner's: the sheet leaves it out
  const tops = $derived((x?.topics || []).filter((t) => !/ \(project\)$/.test(t.name)));
  const secs = $derived.by((): Sec[] => [{ id: "card", w: isDispatch(i) ? "From the dispatch" : c ? "Card" : "The idea as written" }]);
  const detailsSel = $derived(c && c.number != null ? "card:" + c.number : "i" + i.id);
  const d = $derived(c?.dispatch || {});
  const pitchKind = $derived(PITCH_KIND[c?.pitch_kind || ""] || "");
</script>

{#snippet act(a: Act)}
  {#if a === "write"}<button class="btn sm primary" data-act="write" id="idea-write" title={WORD.write} bind:this={btns.write} onclick={(e) => run("write", e.currentTarget)}>Write a post</button>
  {:else if a === "pass"}<button class="btn sm" data-act="pass" title={WORD.pass} bind:this={btns.pass} onclick={(e) => run("pass", e.currentTarget)}>Pass<kbd>p</kbd></button>
  {:else if a === "later"}<button class="btn sm quiet" data-act="later" title={WORD.later} bind:this={btns.later} onclick={(e) => run("later", e.currentTarget)}>Later<kbd>l</kbd></button>{/if}
{/snippet}
{#snippet note(colour: string, ic: string, text: string)}<div class={"note c-" + colour} role="status"><Icon name={ic} /><div>{text}</div></div>{/snippet}
{#snippet kind()}<Glyph name={s[1]} colour={s[2]} word={s[0]} />{c ? ` card ${ideaNo(i)}` : " " + srcWord(i.source)}{` · ${brief ? String(i.state || "waiting") : s[0].toLowerCase()}`}{/snippet}
{#snippet lede()}{#each tops.slice(0, 3) as t, n (n)}{n ? " · " : ""}{t.name}{t.share != null && t.share < 1 ? " " + pct(t.share) : ""}{/each}{#if x && x.theme}{tops.slice(0, 3).length ? " · " : ""}{"theme " + x.theme.name}{/if}{tops.slice(0, 3).length || (x && x.theme) ? " · " : ""}{(c ? "written " : "added ") + rel(i.created)}{/snippet}
{#snippet heads()}{#each acts as a (a)}{@render act(a)}{/each}<button type="button" class="linkish small" id="idea-details" onclick={() => openDetails(detailsSel)}>Details ›</button>{/snippet}
{#snippet top()}{#if i.later_until}{@render note("grey", "waiting", `Put off until ${laterUntil(i)}: it is not waiting for you before then.`)}{/if}{/snippet}

{#snippet section(sec: Sec)}
  {#if sec.id === "card"}
    {#if c}<GradeHead target="idea" id={c.number} current={c.grade} what={"card " + ideaNo(i)} compact={brief} />{/if}
    {#if isDispatch(i) && c}<section class="box" id="pitch"><div class="box-h"><h2>{c.pitch_label || `The ${pitchKind} pitch`}</h2><Tip id={{ text: `Your ${pitchKind} pitch as you wrote it, in the dispatch “${d.title || d.dispatch_id}” (${d.date || ""}).` }} about="the pitch" /><span class="grow"></span>{#if d.url}<a class="small" href={d.url} rel="noopener noreferrer" target="_blank">Read the dispatch ↗</a>{/if}</div><div class="box-b"><p class="prose">{c.pitch_text || ""}</p>{#if c.prediction?.statement}<h3 class="mt" style="font-size:14px">The dispatch's prediction</h3><p class="prose">{c.prediction.statement}</p>{#if c.prediction.by}<p class="muted small">{"resolves by " + c.prediction.by}</p>{/if}{/if}</div></section>{/if}
    {#if fields.length}<dl class="kv">{#each fields as [k, v] (k)}<dt>{k}</dt><dd>{#if typeof v === "string" && v.length > 160 && !brief}<Clamp text={v} />{:else}{v}{/if}</dd>{/each}</dl>{:else}<p class="prose">{i.text || "(no text)"}</p>{/if}
    {#if srcs.length}<p class="small" id="idea-sources">{"Sources: "}{srcs.map(([site]) => site).join(" · ")}</p>{/if}
    {#if news}<p class="small" id="idea-news">In the news · <a href={storyHref(news.brief_id, news.n)}>{news.headline}</a>{` · ${shortDay(news.date)} ›`}</p>{/if}
  {/if}
{/snippet}

<Pane {title} {kind} {lede} acts={heads} {top} sections={secs} {section} />
