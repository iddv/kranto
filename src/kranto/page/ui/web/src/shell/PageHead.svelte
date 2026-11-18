<script lang="ts">
  // The one head every page starts with, drawn by the shell at the top of the
  // column (#page-head, once a page), from the page's declaration (lib/app/heads.ts: its title,
  // facts, lede, one primary, ⋯, its line and its flash) and the door's (the crumb, the glyph, the
  // gear and the subnav). Top to bottom: the crumb (Home › the door; none in Classic, where the
  // tree says it, but Watch's topic switcher stays: WT); the glyph, the title and a trust tag, with
  // at most one primary, Stop, ⋯ and ⚙ at the right; one facts line; the Activity line; one
  // notice; the subnav as underlined words with counts, never pills, never tabs.   // the lede's sentence is the title's ? (help is help), and a page's own notice is one quiet line
  // (a k-note), never a coloured box: the box is Kranto's own trouble, the band.
  // Watch is topic-first: its subnav is Topics, then the scoped topic's name with its
  // Sources, Evidence and Map ("Topics · Robotics › Sources Evidence Map"), or All topics' on their
  // pages; on one of those pages the crumb is "Watch › Robotics › Sources", the topic a switcher
  // (another topic, or All topics) that keeps the page.
  import { app, ui } from "../lib/shell.svelte";
  import { go } from "../lib/router";
  import { WATCH_PAGES, watchPath } from "../lib/app/watchscope";
  import { DOOR_HEADS, type HeadVerb } from "../lib/app/heads";
  import More from "../ui/More.svelte";
  import PreparedLine from "../ui/PreparedLine.svelte";
  import RunLine from "../ui/RunLine.svelte";
  import Tip from "../ui/Tip.svelte";

  const d = $derived(ui.facts?.place || null);
  const h = $derived(ui.head);
  const sc = $derived(d?.scope || null);
  // the classic frame draws no crumb (its tree says where you are), a door's page or not (a cub's)
  const classic = $derived.by(() => {
    void ui.drawn;
    return d ? !!d.classic : document.body.classList.contains("classic");
  });
  const door = $derived(d ? DOOR_HEADS[d.id] || null : null);
  // the crumb names the scope while one of its pages is open (the topic itself, or a page)
  const inScope = $derived(!!sc && sc.page != null && (sc.all || !!sc.topic));
  const pageWord = $derived(sc && sc.page ? WATCH_PAGES.find(([k]) => k === sc.page)?.[1] || "" : "");
  // a page that is one of its door's subnav words is titled with the door's word: the subnav says
  // which page ("Ideas" over Cards · Review); any other page keeps its own title
  const onWord = $derived(d?.items.find((x) => x.on)?.w || null);
  const title = $derived(!h ? d?.word || "" : d && (h.title === onWord || h.title === d.word) ? d.word : h.title);
  const glyph = $derived(h?.glyph ?? door?.glyph ?? null);
  const wash = $derived(h?.wash ?? door?.wash ?? "grey");
  const gear = $derived.by(() => {
    void ui.drawn;
    // a route, never an address: "#/settings/posting" made "#/#/settings/posting"
    return (h && h.gear !== undefined ? h.gear : door?.gear ?? null)?.replace(/^#?\/?/, "") || null;
  });
  const line = $derived(h && h.line !== undefined ? h.line : d && (d.items[0]?.on || !d.items.length) ? door?.line ?? null : null);
  // one slot, two uses: the door's words, or an object page's outline (its own)
  const sub = $derived(h?.outline ? null : h?.sub || (d && d.items.length > 1 ? d.items : null));
  const crumb = $derived(!classic && (d || h?.crumb));
  const show = $derived(!!(h || d));

  function switchTopic(btn: HTMLElement): void {
    if (!sc) return;
    const page = sc.page || "";
    const items = sc.topics.map((t) => ({ label: t.name + (t.id === sc.topic ? " ✓" : ""), id: "topic-to-" + t.id, run: () => go(watchPath(t.id, page)) }));
    items.push({ label: "All topics" + (sc.all ? " ✓" : ""), id: "topic-to-all", run: () => go(watchPath(null, page)) });
    app()?.menu(btn, items);
  }
</script>

{#snippet verb(v: HeadVerb, cls: string)}{#if v.href}<a class={"btn sm " + cls} id={v.id || null} title={v.title || null} href={v.href}>{v.label}</a>{:else}<button type="button" class={"btn sm " + cls} id={v.id || null} title={v.title || null} disabled={v.disabled || null} onclick={(e) => v.run?.(e.currentTarget)}>{v.label}</button>{/if}{/snippet}

{#if show}
  <div class={"phead" + (classic ? " classic" : "")} id="page-head">
    {#if crumb || (classic && sc && inScope)}<nav class="crumb" aria-label="Breadcrumb"><a href="#/home">Home</a>{#if d}<span class="sep" aria-hidden="true">›</span><a href={"#/" + (d.items[0]?.to || d.id)} aria-current={d.items.length || (sc && inScope) ? null : "page"}>{d.word}</a>{#if sc && inScope}<span class="sep" aria-hidden="true">›</span><button type="button" class="crumb-switch" id="topic-switch" aria-haspopup="menu" title="Another topic, or All topics: the same page" onclick={(e) => switchTopic(e.currentTarget)}>{sc.name} ▾</button>{#if pageWord}<span class="sep" aria-hidden="true">›</span><a href={"#/" + watchPath(sc.all ? null : sc.topic, sc.page || "")} aria-current="page">{pageWord}</a>{/if}{/if}{/if}{#each h?.crumb || [] as c, i (c.to + i)}<span class="sep" aria-hidden="true">›</span><a href={"#/" + c.to} aria-current={i === (h?.crumb?.length || 0) - 1 ? "page" : null}>{c.w}</a>{/each}</nav>{/if}
    {#if title}
      <div class="trow">
        <h1>{#if glyph}<span class={"pg w-" + wash} aria-hidden="true">{glyph}</span>{/if}<span class="pt">{title}</span></h1>
        {#if h?.trust}<span class={"htag t-" + h.trust.cls} title={h.trust.title || null}>{h.trust.w}</span>{/if}
        {#if h?.about}<Tip id={h.about} about={title} />{:else if h?.lede}<Tip id={{ text: h.lede }} about={title} />{/if}
        {#if h?.primary || h?.stop || h?.more?.length || gear}
          <span class="verbs">{#if h?.primary}{@render verb(h.primary, h.primary.plain ? "" : "primary")}{/if}{#if h?.stop}{@render verb(h.stop, "stop")}{/if}{#if h?.more?.length}<More items={h.more} />{/if}{#if gear}<a class="gear" id="page-gear" href={"#/" + gear} title="Settings" aria-label={`Settings for ${title}`}>⚙</a>{/if}</span>
        {/if}
      </div>
      {#if h?.facts || h?.tags?.length}<p class="facts-line" id="page-facts">{#each h?.tags || [] as t (t.w)}<span class={"htag t-" + t.cls} title={t.title || null}>{t.w}</span>{/each}{#if h?.facts}<span>{h.facts}</span>{/if}</p>{/if}
      {#if line}<RunLine subject={line} tick={ui.drawn} id={h?.lineId || "page-run-line"} />{/if}
      {#if h?.flash}<p class={"k-note " + h.flash.kind} role="status" id="page-flash"><span>{h.flash.text}{#if h.flash.link}{" "}<a href={h.flash.link.href}>{h.flash.link.w}</a>{/if}</span></p>{/if}
      <PreparedLine />
    {/if}
    {#if sub}<nav class="doornav" aria-label={d?.word || title}>{#each sub as x, i (x.to + i)}{#if "sub" in x && x.sub && !(sub[i - 1] as { sub?: boolean } | undefined)?.sub && sc}<span class="scope" id="watch-scope">{#if sc.to}<a href={"#/" + sc.to} class="scope-name" aria-current={sc.on ? "page" : null} title={`${sc.name}: the topic's page`}>{sc.name}</a>{:else}<span class="scope-name">{sc.name}</span>{/if}<span class="sep" aria-hidden="true">›</span></span>{/if}<a href={"#/" + x.to} aria-current={x.on ? "page" : null} data-scoped={"sub" in x && x.sub ? "1" : null}>{x.w}{#if x.n}<span class={"n " + (x.tone || "")} title={x.title || null}>{String(x.n)}</span>{/if}</a>{/each}</nav>{/if}
  </div>
{/if}
