<script lang="ts">
  // Settings › Posting: where posts go, all optional (every draft can be copied without an
  // account). The sites you post to, one line each (a site is a word in a line, never a logo): how
  // it posts and one control, Post directly where Kranto can post there after your yes (off
  // until you switch it on), or Mastodon's server to open; Add a site (the other sites, the
  // disclosure line, and what is not possible today, with why). Then your blog (step one of
  // Write a post: short posts link to it), the newsletter (MAIL, in the sheet) and How you write.
  // Its old addresses land here: Settings › Accounts, the toot cub's settings (lib/app/route).
  import Glyph from "../../ui/Glyph.svelte";
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import Row from "../../ui/Row.svelte";
  import Empty from "../../ui/Empty.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { ui } from "../../lib/shell.svelte";
  import { openDialog } from "../../ui/dialog.svelte";
  import { NEWSLETTER_API, nlLine, nlSt, type Newsletter } from "./newsletter";
  import { POSTING_API, savePosting, siteLine, waitingLine, type Posting, type PostingSite } from "./posting";
  import AddSiteDialog from "./AddSiteDialog.svelte";

  let { view }: { view: View } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const nl = $derived.by(() => {
    void view.tick;
    return host ? read<Newsletter>(NEWSLETTER_API, 15000).data || null : null;
  });
  const nst = $derived(nl ? nlSt(nl) : (["open", "grey", "Not connected"] as const));
  const p = $derived.by(() => {
    void view.tick;
    return host ? read<Posting>(POSTING_API, 15000).data || null : null;
  });
  const ticked = $derived((p?.sites || []).filter((s) => s.ticked));
  const blog = $derived(p?.blog || null);
  const blogLine = $derived(!blog || blog.state === "not set" ? "not connected: short posts link to the sources" : blog.post_url ? `short posts link to ${blog.post_url}` : "connected; add your posts' address");
  let server = $state("");
</script>

{#snippet siteEnd(s: PostingSite)}
  {#if s.needs === "instance" && !s.instance}
    <form class="inline" onsubmit={(e) => { e.preventDefault(); savePosting(e.currentTarget.querySelector("input"), { instance: server }, "Saved: Open goes to your server."); }}><input type="text" class="sm" id="posting-server" placeholder="Your server" aria-label="Your Mastodon server" bind:value={server} /></form>
  {:else if s.can_direct && !s.ways.includes("open")}
    <!-- a site with no Open (LinkedIn) is posted directly or not at all: Connect, no switch -->
    {#if !s.account && s.connection}<a class="btn sm" data-act="post-connect" href={href("settings/connections/" + s.connection)}>Connect</a>{/if}
  {:else if s.can_direct}
    <label class="inline small"><input type="checkbox" data-act="post-direct" data-site={s.id} checked={s.direct} onchange={(e) => savePosting(e.currentTarget, { direct: { [s.id]: e.currentTarget.checked } }, e.currentTarget.checked ? (s.account ? `Kranto posts to ${s.name} after your yes.` : `Connect ${s.name} (posting) so Kranto can post there.`) : `${s.name}: Open only.`)} /> Post directly</label>
    {#if waitingLine(s)}{" "}<span class="small c-amber" data-act="post-direct-waiting">{waitingLine(s)}</span>{/if}
    {#if s.direct && !s.account && s.connection}{" "}<a class="small" data-act="post-connect" href={href("settings/connections/" + s.connection)}>Connect</a>{/if}
  {/if}
{/snippet}

<List title="Posting" crumb="Settings" sub="Optional: every draft can be copied without an account.">
  <Group id="post-sites" title="Sites you post to" count={String(ticked.length)}>
    {#each ticked as s (s.id)}
      {#snippet end()}{@render siteEnd(s)}{/snippet}
      <Row title={s.name} meta={siteLine(s)} {end} />
    {/each}
    {#if !ticked.length}<Empty li text="No site yet: add the ones you post to." />{/if}
    {#snippet foot()}<p class="more"><button type="button" class="btn sm" id="posting-add" onclick={() => openDialog(AddSiteDialog, {})}>Add a site</button></p>{/snippet}
  </Group>
  <Group id="post-newsletter" title="Your blog and newsletter" count="2" kind="sets">
    <Row title="Your blog" href={href("settings/connections/sanity")} meta={blogLine} />
    <Row sel="enl" title="Newsletter" meta={nlLine(nl)} stw={nst}>{#snippet st()}<Glyph name={nst[0]} colour={nst[1]} word={nst[2]} />{/snippet}</Row>
  </Group>
  <Group id="post-voice" title="How you write" count="1" kind="sets">
    <Row title="How you write" href={href("settings/posting/voice")} meta="every post follows it"></Row>
  </Group>
</List>
