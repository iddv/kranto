<script lang="ts">
  // Post (#/post, the fourth door): one page, no tabs inside it. The head: Post,
  // a plain Write a post ("About what?": this week's news, or an idea;), ⚙ (Settings › Posting), one facts line ("Drafts wait here until you have seen them."). Drafts
  // waiting, one line a draft (its kind in a word, its title, one fact, its age, Open), the newest
  // holding the page's one primary; Sent, one line a post with where it went; the three accounts,
  // optional, each with Connect or Change; Earlier drafts, folded (a weekly issue a newer one
  // replaced, a declined one), each still openable. A draft opens in its sheet (#/post/d/<id>,
  // the P2: Copy, Download, Send, Decline, Details); before that route is there, Open is the
  // ask's own dialog (Send there opens SEND's dialog unchanged), or the cub's page for an earlier
  // draft. A write's short posts are one row naming its sites ("Bluesky ✓ · Mastodon · X"); the
  // accounts are one line, "Where posts go", with one control to Settings › Posting. Scheduled
  // (only when something is): a post the person said yes to at an hour, "Monday 16 Nov, 09:00 ·
  // Bluesky", with Cancel; Sent says a post's numbers where its site gives them, and once, at the
  // foot, which sites give none. Nothing here sends: Send is always the owner's click in the
  // dialog, now or at the hour they chose there.
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import Row from "../../ui/Row.svelte";
  import Loading from "../../ui/Loading.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { ago, dt } from "../../lib/format";
  import { read } from "../../lib/reads.svelte";
  import { ui } from "../../lib/shell.svelte";
  import { openAsk } from "../../features/cubverbs";
  import { dismissWrite, retryWrite, writeAny } from "../../features/post/post";
  import { cancelHour, draftFact, draftHref, dueWhen, failedAbout, failedTitle, fixWords, hasSheet, POST_API, sentLine, whereLine, type Post, type PostDraft } from "./post";

  let { view }: { view: View } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const r = $derived.by(() => {
    void view.tick;
    return host ? read<Post>(POST_API, 15000) : null;
  });
  // every list read as a list, whatever shape came (an older server, a fake): never a crash
  const d = $derived.by((): (Post & { scheduled: PostDraft[]; reach_foot: string | null }) | null => {
    const x = r?.data as Partial<Post> | undefined | null;
    if (!x) return null;
    const list = <T,>(v: T[] | undefined): T[] => (Array.isArray(v) ? v : []);
    const sites = x.sites && typeof x.sites === "object" && typeof x.sites.line === "string" ? x.sites : { line: "No sites chosen for short posts yet.", ticked: 0 };
    return { line: typeof x.line === "string" ? x.line : "Drafts wait here until you have seen them.", drafts: list(x.drafts), scheduled: list(x.scheduled), sent: list(x.sent), earlier: list(x.earlier), accounts: list(x.accounts), sites, failed: list(x.failed), reach_foot: typeof x.reach_foot === "string" ? x.reach_foot : null };
  });
  const sheet = $derived(hasSheet());
  const STATE: Record<string, string> = { newsletter: "✉", mastodon: "✎", blog: "✎", short: "✎" };
</script>

<!-- a draft's one verb: View (its sheet, or its ask's dialog until the sheet's route is there);
     never "Open", which is the word for opening the site with the draft filled in -->
{#snippet open(x: PostDraft, main: boolean)}
  {#if !sheet && (x.ticket != null || x.again != null)}
    <button type="button" class={"btn sm" + (main ? " primary" : "")} data-act="post-open" onclick={(e) => openAsk({ cub: x.cub, ticket: x.ticket, again: x.again }, e.currentTarget)}>View</button>
  {:else}
    <a class={"btn sm" + (main ? " primary" : "")} data-act="post-open" href={draftHref(x)}>View</a>
  {/if}
{/snippet}

<!-- the accounts' one control: the sites you post to, on Settings › Posting -->
{#snippet sitesEnd()}<a class="btn sm" id="post-sites" href="#/settings/posting">Sites</a>{/snippet}

{#snippet draftRow(x: PostDraft, main: boolean)}
  {#snippet end()}{@render open(x, main)}{/snippet}
  <Row title={x.title} href={sheet ? draftHref(x) : null} meta={x.missed || draftFact(x)} age={ago(dt(x.at))} {end}>
    <!-- a post whose hour passed while Kranto was stopped: an amber mark a phone keeps too -->
    {#snippet st()}{#if x.missed}<span class="gl c-amber" role="img" aria-label="its hour passed"><span class="hglyph" aria-hidden="true">!</span><span class="gl-w" aria-hidden="true">hour passed</span></span>{:else}<span class="gl c-violet" role="img" aria-label={x.word}><span class="hglyph" aria-hidden="true">{STATE[x.kind] || "•"}</span><span class="gl-w" aria-hidden="true">{x.word}</span></span>{/if}{/snippet}
  </Row>
{/snippet}

{#if !host}
  <List title="Post"><NeedHost what="Post" /></List>
{:else if !d}
  <List title="Post"><Loading error={r?.error} /></List>
{:else}
  <List title="Post" head={{ facts: d.line, gear: "settings/posting", primary: { label: "Write a post", plain: true, id: "post-write", title: "About this week's news, or an idea", run: () => writeAny() } }}>
    <!-- a Write a post that wrote no draft stays here with why, until dismissed -->
    {#if d.failed.length}
      <Group id="post-failed" title="No draft written" count={String(d.failed.length)}>
        {#each d.failed as f (f.as + f.about)}
          {#snippet end()}{#if f.fix}<a class="btn sm" href={"#/" + f.fix}>{fixWords(f.fix)}</a>{/if}<button type="button" class="btn sm" data-act="post-retry" onclick={(e) => retryWrite(e.currentTarget, failedAbout(f), f.as)}>Try again</button><button type="button" class="btn sm quiet" data-act="post-dismiss" onclick={(e) => dismissWrite(e.currentTarget, f.about, f.as)}>Dismiss</button>{/snippet}
          <Row title={failedTitle(f)} age={ago(dt(f.at))} {end}>
            {#snippet st()}<span class="gl c-red" role="img" aria-label="failed"><span class="hglyph" aria-hidden="true">✕</span></span>{/snippet}
          </Row>
          <!-- its reason, on its own line under the row, on a phone too (the row's fact gave way
               there, and the failed row lost why) -->
          <li class="row-why small" data-why={f.as + f.about}>{f.error}</li>
        {/each}
      </Group>
    {/if}
    <Group id="post-drafts" title="Drafts waiting" count={String(d.drafts.length)} kind="words">
      {#each d.drafts as x, i (x.id)}{@render draftRow(x, i === 0)}{/each}
      {#if !d.drafts.length}<li class="gempty"><span class="muted">No draft waits. A draft comes when you choose Write a post on a story or an idea, or with the weekly issue.</span></li>{/if}
    </Group>
    <!-- a post the person said yes to at an hour: it goes then, and can be cancelled until then -->
    {#if d.scheduled.length}
      <Group id="post-scheduled" title="Scheduled" count={String(d.scheduled.length)}>
        {#each d.scheduled as x (x.id)}
          {#snippet end()}<button type="button" class="btn sm" data-act="post-cancel" onclick={(e) => cancelHour(e.currentTarget, x.id)}>Cancel</button>{/snippet}
          <!-- when and where is the row's title, so a phone keeps it; the post's title is its fact -->
          <Row title={dueWhen(x)} href={sheet ? draftHref(x) : null} meta={x.title} {end} />
        {/each}
      </Group>
    {/if}
    <Group id="post-sent" title="Sent" count={String(d.sent.length)}>
      {#each d.sent as x (x.id)}
        {#snippet end()}{#if x.link}<a class="btn sm quiet" href={x.link} target="_blank" rel="noopener noreferrer" title="Where it went">↗</a>{/if}{/snippet}
        <!-- where and how it went is the row's title ("X · posted by you"); the post's title is its fact -->
        <Row title={sentLine(x)} href={sheet ? draftHref(x) : null} meta={x.title} age={ago(dt(x.at))} {end} />
      {/each}
      {#if !d.sent.length}<li class="gempty"><span class="muted">Nothing sent yet. A sent post shows here with where it went and how many it reached.</span></li>{/if}
      {#if d.sent.length && d.reach_foot}<li class="gempty" id="post-reach-foot"><span class="muted small">{d.reach_foot}</span></li>{/if}
    </Group>
    <Group id="post-accounts" title="Accounts" says="optional: every draft can be copied without one">
      <Row title="Where posts go" meta={whereLine(d)} end={sitesEnd} />
    </Group>
    {#if d.earlier.length}
      <Group id="post-earlier" title="Earlier drafts" count={String(d.earlier.length)} fold="post:earlier" start>
        {#each d.earlier as x (x.id)}
          {#snippet end()}<a class="btn sm quiet" href={draftHref(x)}>View</a>{/snippet}
          <Row title={x.title} meta={x.line || draftFact(x)} age={ago(dt(x.at))} {end} />
        {/each}
      </Group>
    {/if}
  </List>
{/if}

<style>
  /* a failed write's reason, its own line under its row (desktop and phone alike) */
  .row-why { list-style: none; color: var(--red, var(--ink)); padding: 0 8px 6px 34px; overflow-wrap: anywhere; }
  /* a failed write's reason and where posts go are read whole: the fact takes its own line
     under the title, wrapped, at every width (they were cut to a few letters) */
  :global(section[aria-labelledby="post-failed"] .lr .c-main),
  :global(section[aria-labelledby="post-accounts"] .lr .c-main) { flex-wrap: wrap; row-gap: 2px; }
  :global(section[aria-labelledby="post-failed"] .lr .c-meta),
  :global(section[aria-labelledby="post-accounts"] .lr .c-meta) { flex: 1 1 100%; white-space: normal; overflow: visible; text-overflow: clip; }
  :global(section[aria-labelledby="post-failed"] .lr .r-title) { white-space: normal; }
  /* a phone hides a row's fact; a failed write keeps its reason, under its title (as "Where posts
     go" keeps its line) */
  @media (max-width: 759px) {
    :global(section[aria-labelledby="post-failed"] .lr .c-main) { display: flex; flex-direction: column; -webkit-line-clamp: unset; line-clamp: unset; }
    :global(section[aria-labelledby="post-failed"] .lr .c-main .c-meta) { display: block; white-space: normal; overflow: visible; }
    :global(section[aria-labelledby="post-failed"] .lr .c-end) { grid-column: 4 / 8; grid-row: 2; justify-self: start; }
    :global(section[aria-labelledby="post-failed"] .row.lr) { row-gap: 4px; }
  }
  /* a phone (the mock,): a group's note goes to its own line under the heading, and a
     draft's kind is its glyph (the word is its label) so its title keeps the room */
  @media (max-width: 700px) {
    :global(section[aria-labelledby^="post-"] .ghd) { flex-wrap: wrap; height: auto; min-height: 27px; padding-bottom: 3px; }
    :global(section[aria-labelledby^="post-"] .ghd h2) { flex: none; overflow: visible; text-overflow: clip; }
    :global(section[aria-labelledby^="post-"] .ghd .g-says) { flex-basis: 100%; line-height: 18px; }
    :global(section.grp.words[aria-labelledby="post-drafts"] .lr .c-st .gl-w) { display: none; }
    :global(section.grp.words[aria-labelledby="post-drafts"]) { --stw: 28px; }
  }
</style>
