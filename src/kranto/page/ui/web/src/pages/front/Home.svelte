<script lang="ts">
  // The home (#/ and #/home): one fixed order, each block absent when it has
  // nothing to say. The date and one sentence; the one thing (needs.ts nextOf:
  // the newest thing that waits for a yes, else the oldest thing to fix), the page's one primary;
  // today's brief (three topics at most, three items each); the five newest idea cards with ▲ ▼;
  // one quiet line. After home.away_days without a visit, the brief and the cards give way to While
  // you were away: one list of five, chosen by the server's rule, until one of them is opened or Show
  // today is chosen (only then is the visit marked). Everything but the one thing comes from
  // the server's one read, GET /api/home; the band, if any, stands above everything. No tiles, no
  // cubs, no Arrange: the home is not arranged any more (a stored arrangement is read and ignored).
  import Group from "../../ui/Group.svelte";
  import Row from "../../ui/Row.svelte";
  import Next from "../../ui/Next.svelte";
  import Grade from "../../ui/Grade.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { ago, dt } from "../../lib/format";
  import { app, ui } from "../../lib/shell.svelte";
  import { features } from "../../features/index";
  import { arrangement } from "../../features/shell";
  import { needsCount, nextOf, reviewCount, todayRead, type Want, type Host } from "./needs";
  import { activityRows, awaySpan, briefFact, cardHref, coreNeeds, dayTitle, everythingLine, everythingParts, homeRows, itemHref, nextLine, orderNeeds, preparedRows, quietLine, rowCubs, sentence, sinceWords, uniqueRows, type HomeRow } from "./home";
  import { openPrepared, refusedPrepared } from "../../ui/prepared.svelte";
  import { openAsk } from "../../features/cubverbs";
  import { PREPARED_API, waitingItems, type Prepared } from "../../lib/prepared";
  import { dismissIncident } from "../../shell/incidents";
  import type { Activity } from "../../api/types.gen";
  import { ACT_PATH, bandOf } from "../../lib/activity";
  import IncidentBand from "../../shell/IncidentBand.svelte";
  import { drop, read } from "../../lib/reads.svelte";
  import { HOME_API, homeRead, VISIT_API } from "../../features/home";
  import { href } from "../../lib/router";
  import { firstLine } from "../welcome/voice";
  import { PRODUCT, Product } from "../../lib/product";

  let { view }: { view: View } = $props();
  /** a time to come, as the four rows say it: "at 14:20" */
  const at = (iso: string): string => {
    const t = dt(iso);
    return t == null ? "" : "at " + new Date(t).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  };
  const L = $derived(app());
  const host = $derived.by(() => {
    void view.tick;
    return (L ? L.host() : null) as unknown as Host | null;
  });
  const H = $derived(!!host);
  const t = $derived.by(() => {
    void view.tick;
    return todayRead(host)?.data || null;
  });
  const review = $derived.by(() => {
    void view.tick;
    return reviewCount(host);
  });
  const f = $derived.by(() => {
    void view.tick;
    return features(H);
  });
  const a = $derived.by(() => {
    void view.tick;
    return arrangement(H);
  });
  // the server's one read of the home
  // read more often during the first hour, while the read moves
  let firstHour = false;
  const hr = $derived.by(() => {
    void view.tick;
    return homeRead(H, firstHour ? 10000 : 60000);
  });
  const d = $derived(hr?.data || null);
  const first = $derived(d?.first && !d.first.error && d.first.topic ? d.first : null);
  $effect(() => {
    firstHour = !!first;
    if (!first) return;
    const t = setInterval(() => L?.render(), 10000);
    return () => clearInterval(t);
  });
  // what the activity read adds: a failing kind's Fix row, a run that stopped for you
  const act = $derived.by(() => {
    void view.tick;
    return read<Activity>(ACT_PATH, 5000).data;
  });
  const cubNeeds = $derived.by(() => {
    void view.tick;
    return rowCubs(f, a, "needs_you").flatMap((x) => homeRows(hr, x, "needs_you"));
  });
  // the candidates for the one thing: the core's rows, the prepared items, the cubs' asks (a draft
  // that waits), the failing kinds; Needs you (#/needs) holds them all, the home only the one
  const needs = $derived.by((): HomeRow[] => {
    void view.tick; // the cards' read, read again on its schedule
    const core = coreNeeds(t, host, review);
    const items = H ? waitingItems(read<{ prepared: Prepared[] }>(PREPARED_API, 10000).data?.prepared) : [];
    return orderNeeds(core, [...preparedRows(items), ...activityRows(act, cubNeeds, { band: true, prepared: true })], cubNeeds);
  });
  const incs = $derived(bandOf(act)); // Kranto's own trouble: the band, never the one thing
  const nx = $derived(nextOf(needs.filter((r): r is HomeRow & { want: Want } => !!r.want).map((r) => ({ ...r, at: r.at ?? null }))));
  // an older the server (no sentence in its home read) keeps the counts' sentence
  const said = $derived(first ? `${Product} is reading ${first.topic!.name} for the first time.` : d?.sentence || (d && !d.date ? sentence(needsCount(host, uniqueRows(cubNeeds).length, cubNeeds.map((r) => r.href), act), cubNeeds.length, t ? t.new_kept : 0, 0) : ""));

  // While you were away, until one of its five is opened or Show today is chosen
  let today = $state(false);
  const away = $derived(!today && d?.away ? d.away : null);
  const briefs = $derived(d?.briefs && d.briefs.topics ? d.briefs : null);
  const ideas = $derived(d?.ideas && d.ideas.rows ? d.ideas : null);
  const quiet = $derived(d?.quiet ? quietLine(d.quiet) : "");

  /** the visit is marked: the ordinary home as it draws, once a page load */
  let marked = false;
  function markVisit(): void {
    if (marked || !L) return;
    marked = true;
    void L.api(VISIT_API, {}).catch(() => { marked = false; });
  }
  $effect(() => {
    if (d && d.date && !d.away) markVisit();
  });
  /** a row of the five is opened: the visit is marked on the way */
  function opened(): void {
    markVisit();
  }
  function showToday(): void {
    today = true;
    markVisit();
    drop(HOME_API); // the ordinary home's "new since" counts from the visit before this one
  }
</script>

<!-- a row's state: its glyph and its word in its colour, never colour alone (R1) -->
{#snippet state(glyph: string, word: string, tone: string)}<span class={"gl c-" + tone} role="img" aria-label={word}><span class="hglyph" aria-hidden="true">{glyph}</span><span class="gl-w" aria-hidden="true">{word}</span></span>{/snippet}

<!-- the one thing's verb: the screen's one primary -->
{#snippet verb(r: HomeRow)}{#if r.prepared}{@const p = r.prepared}<button type="button" class="btn sm primary" data-prepared-act={p.uuid} title={r.verb} onclick={() => openPrepared(p)}>{r.verb}</button>{:else if r.ask}{@const k = r.ask}<button type="button" class="btn sm primary" data-act="ask-open" title={r.verb} onclick={(e) => openAsk(k, e.currentTarget)}>{r.verb}</button>{:else}<a class="btn sm primary" href={r.href} title={r.verb}>{r.verb}</a>{/if}{#if r.dismiss}{@const id = r.dismiss}<button type="button" class="btn sm quiet" data-dismiss={id} title="Put it away until it happens again" onclick={(e) => dismissIncident(id, e.currentTarget)}>Dismiss</button>{/if}{/snippet}

{#snippet nextBox()}
  {#if nx}{@const r = nx}{#snippet main()}{@render verb(r)}{/snippet}
    <Next kind={nextLine(r)} title={r.title} href={r.href} why={r.prepared ? [r.prepared.says, `Nothing happens until you choose ${r.verb}.`].filter(Boolean).join(" ") : r.meta || null} details={r.prepared ? "prep:" + r.prepared.uuid : null} sel={r.key} tone={r.want === "approve" ? "violet" : r.want === "fix" ? "amber" : "blue"} act={main} />
    {#if r.prepared && refusedPrepared[r.prepared.uuid]}<p class="c-amber" role="alert">{refusedPrepared[r.prepared.uuid]}</p>{/if}
  {/if}
{/snippet}

{#snippet chevron(to: string, what: string)}<a class="btn sm quiet chev" href={to} aria-label={"Open " + what}>›</a>{/snippet}

{#snippet briefBox()}
  {#if briefs}
    {#each briefs.topics || [] as b (b.brief)}
      {#snippet read_()}<a href={href("news/b/" + b.brief)} class="g-link">Read the brief</a>{/snippet}
      {#snippet more()}{#if b.more}<p class="g-foot muted">{b.more === 1 ? "1 more in this brief." : `${b.more} more in this brief.`}</p>{/if}{/snippet}
      <Group id={"home-brief-" + b.brief} title="Today's brief" count={briefFact(b.topic.name, b.at)} kind="words" right={read_} foot={more}>
        {#each b.items as it (it.n)}
          {#snippet end()}{@render chevron(itemHref(b.brief, it.n), it.title)}{/snippet}
          <Row title={it.title} href={itemHref(b.brief, it.n)} meta={it.source || null} age={ago(dt(b.at))} {end}>{#snippet st()}{@render state("▤", "news", "amber")}{/snippet}</Row>
        {/each}
      </Group>
    {/each}
    {#if briefs.more}<p class="g-foot" id="home-briefs-more"><a href="#/news">{`and ${briefs.more} more ${briefs.more === 1 ? "brief" : "briefs"} on News`}</a></p>{/if}
  {/if}
{/snippet}

<!-- the first hour (mock `first`): while the newest topic has no first brief,
     the read as it goes and the topic's four rows, then that the page may be closed -->
{#snippet firstBox()}
  {#if first}
    {@const line = firstLine(first)}
    {#snippet topicLink()}<a href={href("topics/" + first.topic!.id)} class="g-link" id="home-first-topic">The topic's page ›</a>{/snippet}
    {#snippet foot()}<p class="g-foot muted" id="home-first-foot">{`${first.quiet ? first.quiet + " " : ""}You can close this page; ${PRODUCT} keeps reading.`}</p>{/snippet}
    <Group id="home-first" title="The first hour" count={first.topic!.name} right={topicLink} {foot}>
      {#if line}<li class="gempty" id="home-first-read"><span>{line}</span></li>{/if}
      {#each first.rows || [] as r (r.key)}
        <Row title={r.title} meta={r.words} age={r.at ? (r.state === "done" ? ago(dt(r.at)) : at(r.at)) : ""}>{#snippet st()}{@render state(r.state === "done" ? "✓" : r.state === "running" ? "◐" : "○", r.state === "done" ? "done" : r.state === "running" ? "now" : "next", r.state === "done" ? "green" : r.state === "running" ? "blue" : "grey")}{/snippet}</Row>
      {/each}
    </Group>
  {/if}
{/snippet}

{#snippet ideasBox()}
  {#if ideas && (ideas.rows || []).length}
    {#snippet all()}<a href="#/ideas" class="g-link" id="home-all-ideas">{`All ${ideas.total ?? ""}`.trim()}</a>{/snippet}
    <Group id="home-ideas" title="New ideas" count={ideas.new ? `${ideas.new} ${sinceWords(ideas.since)}` : null} right={all}>
      {#each ideas.rows || [] as c (c.id)}
        <Row title={c.title} href={cardHref(c.id)} age={ago(dt(c.at))} sel={"card:" + c.id}>
          {#snippet st()}<span class="gl c-violet" role="img" aria-label="idea"><span class="hglyph" aria-hidden="true">◆</span></span>{/snippet}
          {#snippet num()}{"#" + c.id}{/snippet}
          {#snippet grade()}<Grade target="idea" id={c.id} current={c.grade} what={"card #" + c.id} />{/snippet}
        </Row>
      {/each}
    </Group>
  {/if}
{/snippet}

{#snippet awayBox()}
  {#if away}
    {#snippet back()}<button type="button" class="linkish g-link" id="home-show-today" onclick={showToday}>Show today</button>{/snippet}
    {@const ev = everythingParts(away)}
    {#snippet foot()}<p class="g-foot" aria-label={everythingLine(away)}>{ev.head}{#if ev.ideas}<a id="home-everything" href={href("ideas", { since: away.since })} onclick={opened}>{ev.ideas}</a>{/if}{#if ev.ideas && ev.briefs}{" and "}{/if}{#if ev.briefs}<a id="home-everything-briefs" href={href("news/earlier")} onclick={opened}>{ev.briefs}</a>{/if}</p>{/snippet}
    <Group id="home-away" title="While you were away" count={awaySpan(away.since)} right={back} {foot}>
      {#each away.rows as r (r.kind + (r.id ?? r.brief) + ":" + (r.n ?? ""))}
        {#if r.kind === "card" && r.id != null}
          {@const id = r.id}
          <Row title={r.title} href={cardHref(id)} age={ago(dt(r.at))} sel={"card:" + id} on={opened}>
            {#snippet st()}<span class="gl c-violet" role="img" aria-label="idea"><span class="hglyph" aria-hidden="true">◆</span></span>{/snippet}
            {#snippet num()}{"#" + id}{/snippet}
            {#snippet grade()}<Grade target="idea" id={id} current={r.grade ?? null} what={"card #" + id} />{/snippet}
          </Row>
        {:else if r.brief != null}
          {@const to = itemHref(r.brief, r.n ?? 0)}
          {#snippet end()}{@render chevron(to, r.title)}{/snippet}
          <Row title={r.title} href={to} meta={r.source || r.topic || null} age={ago(dt(r.at))} {end} on={opened}>{#snippet st()}{@render state("▤", "news", "amber")}{/snippet}</Row>
        {/if}
      {/each}
      {#if !away.rows.length}<li class="gempty"><span class="muted">Nothing new was written while you were away.</span></li>{/if}
    </Group>
  {/if}
{/snippet}

<div class="wl home" id="home" data-title="Home">
  {#if !d && !hr?.error}
    <p class="empty">Loading…</p>
  {:else}
    {#if incs.length}<IncidentBand incidents={incs} />{/if}
    <div class="greet"><h1>{dayTitle()}</h1>{#if away || said}<p class="lede" id="home-sentence">{away ? away.sentence : said}</p>{/if}</div>
    {@render nextBox()}
    {#if away}
      {@render awayBox()}
    {:else}
      {@render firstBox()}
      {@render briefBox()}
      {@render ideasBox()}
    {/if}
    {#if quiet}<p class="quietline" id="home-quiet">{quiet} <a href="#/activity">Activity</a></p>{/if}
    {#if hr?.error && !d}<p class="muted" id="home-unread">The home could not be read. <a href="#/needs">Needs you</a> and <a href="#/news">News</a> still can.</p>{/if}
  {/if}
</div>

<style>
  .home { padding: 18px 0 28px; max-width: 920px; }
  .greet { margin: 0 0 14px; }
  .home h1 { font-size: 22px; font-weight: 700; }
  .home .lede { color: var(--muted); max-width: 64ch; margin-top: 4px; }
  .home :global(.grp) { margin-top: 14px; }
  .hglyph { color: var(--c, var(--muted)); }
  .g-link { font-size: 12.5px; }
  .g-foot { font-size: 12.5px; margin: 8px 12px 4px; }
  .chev { min-width: 24px; }
  .quietline { color: var(--muted); font-size: 12.5px; margin-top: 22px; }
  .linkish { background: none; border: 0; padding: 0; font: inherit; color: var(--link); cursor: pointer; }
  .linkish:hover { text-decoration: underline; }
  @media (max-width: 700px) {
    .home h1 { font-size: 19px; }
    /* a group's head keeps its words whole on a phone: its link goes to the next line */
    .home :global(.grp .ghd) { flex-wrap: wrap; row-gap: 0; height: auto; min-height: 27px; padding-bottom: 3px; }
    .home :global(.grp .ghd .grow) { flex-basis: 100%; height: 0; }
    .home :global(.grp .ghd .g-link) { margin-left: auto; line-height: 20px; }
    .home :global(.ghd h2) { flex: none; overflow: visible; text-overflow: clip; white-space: nowrap; }
  }
</style>
