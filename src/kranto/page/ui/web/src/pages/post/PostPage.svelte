<script lang="ts">
  // Post (#/post, the fourth door): one page, no tabs inside it. The head: Post,
  // a plain Write a post ("About what?": this week's news, or an idea;), ⚙ (Settings › Posting), one facts line ("Drafts wait here until you have seen them."). Drafts
  // waiting, one line a draft (its kind in a word, its title, one fact, its age, Open), the newest
  // holding the page's one primary; Sent, one line a post with where it went; the three accounts,
  // optional, each with Connect or Change; Earlier drafts, folded (a weekly issue a newer one
  // replaced, a declined one), each still openable. A draft opens in its sheet (#/post/d/<id>,
  // the P2: Copy, Download, Send, Decline, Details); before that route is there, Open is the
  // ask's own dialog (Send there opens SEND's dialog unchanged), or the cub's page for an earlier
  // draft. Nothing here sends: Send is always the owner's click in the dialog.
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
  import { accountHref, accountWords, connectedCount, draftFact, draftHref, failedAbout, failedTitle, hasSheet, POST_API, sentLine, type Post, type PostDraft } from "./post";

  let { view }: { view: View } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const r = $derived.by(() => {
    void view.tick;
    return host ? read<Post>(POST_API, 15000) : null;
  });
  // every list read as a list, whatever shape came (an older the server, a fake): never a crash
  const d = $derived.by((): Post | null => {
    const x = r?.data as Partial<Post> | undefined | null;
    if (!x) return null;
    const list = <T,>(v: T[] | undefined): T[] => (Array.isArray(v) ? v : []);
    return { line: typeof x.line === "string" ? x.line : "Drafts wait here until you have seen them.", drafts: list(x.drafts), sent: list(x.sent), earlier: list(x.earlier), accounts: list(x.accounts), failed: list(x.failed) };
  });
  const sheet = $derived(hasSheet());
  const STATE: Record<string, string> = { newsletter: "✉", mastodon: "✎", blog: "✎" };
</script>

<!-- a draft's one verb: Open (its sheet, or its ask's dialog until the sheet's route is there) -->
{#snippet open(x: PostDraft, main: boolean)}
  {#if !sheet && (x.ticket != null || x.again != null)}
    <button type="button" class={"btn sm" + (main ? " primary" : "")} data-act="post-open" onclick={(e) => openAsk({ cub: x.cub, ticket: x.ticket, again: x.again }, e.currentTarget)}>Open</button>
  {:else}
    <a class={"btn sm" + (main ? " primary" : "")} data-act="post-open" href={draftHref(x)}>Open</a>
  {/if}
{/snippet}

{#snippet draftRow(x: PostDraft, main: boolean)}
  {#snippet end()}{@render open(x, main)}{/snippet}
  <Row title={x.title} href={sheet ? draftHref(x) : null} meta={draftFact(x)} age={ago(dt(x.at))} {end}>
    {#snippet st()}<span class="gl c-violet" role="img" aria-label={x.word}><span class="hglyph" aria-hidden="true">{STATE[x.kind] || "•"}</span><span class="gl-w" aria-hidden="true">{x.word}</span></span>{/snippet}
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
          {#snippet end()}{#if f.fix}<a class="btn sm" href={"#/" + f.fix}>Settings › Watching</a>{/if}<button type="button" class="btn sm" data-act="post-retry" onclick={(e) => retryWrite(e.currentTarget, failedAbout(f), f.as)}>Try again</button><button type="button" class="btn sm quiet" data-act="post-dismiss" onclick={(e) => dismissWrite(e.currentTarget, f.about, f.as)}>Dismiss</button>{/snippet}
          <Row title={failedTitle(f)} meta={f.error} age={ago(dt(f.at))} {end}>
            {#snippet st()}<span class="gl c-red" role="img" aria-label="failed"><span class="hglyph" aria-hidden="true">✕</span></span>{/snippet}
          </Row>
        {/each}
      </Group>
    {/if}
    <Group id="post-drafts" title="Drafts waiting" count={String(d.drafts.length)} kind="words">
      {#each d.drafts as x, i (x.id)}{@render draftRow(x, i === 0)}{/each}
      {#if !d.drafts.length}<li class="gempty"><span class="muted">No draft waits. A draft comes when you choose Write a post on a story or an idea, or with the weekly issue.</span></li>{/if}
    </Group>
    <Group id="post-sent" title="Sent" count={String(d.sent.length)}>
      {#each d.sent as x (x.id)}
        {#snippet end()}{#if x.link}<a class="btn sm quiet" href={x.link} target="_blank" rel="noopener noreferrer" title="Where it went">↗</a>{/if}{/snippet}
        <Row title={x.title} meta={sentLine(x)} age={ago(dt(x.at))} {end} />
      {/each}
      {#if !d.sent.length}<li class="gempty"><span class="muted">Nothing sent yet. A sent post shows here with where it went and how many it reached.</span></li>{/if}
    </Group>
    <Group id="post-accounts" title="Accounts" count={`${connectedCount(d.accounts)} of ${d.accounts.length}`} says="optional: every draft can be copied without one">
      {#each d.accounts as a (a.key)}
        {#snippet end()}<a class="btn sm" href={accountHref(a)}>{a.state === "connected" ? "Change" : a.state === "needs_login" ? "Sign in" : "Connect"}</a>{/snippet}
        <Row title={a.word} meta={accountWords(a)} {end} />
      {/each}
    </Group>
    {#if d.earlier.length}
      <Group id="post-earlier" title="Earlier drafts" count={String(d.earlier.length)} fold="post:earlier" start>
        {#each d.earlier as x (x.id)}
          {#snippet end()}<a class="btn sm quiet" href={draftHref(x)}>Open</a>{/snippet}
          <Row title={x.title} meta={x.line || draftFact(x)} age={ago(dt(x.at))} {end} />
        {/each}
      </Group>
    {/if}
  </List>
{/if}

<style>
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
