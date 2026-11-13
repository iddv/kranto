<script lang="ts">
  // Settings › Posting: the accounts a draft can be sent with, all optional
  // (every draft can be copied without one): the newsletter platform (MAIL, in the sheet) and the
  // posting accounts (Mastodon, Sanity for the blog); then what Kranto writes, each posting cub's
  // own settings page (the weekly issue, its day, hour and topics, practice), one click away.
  // Its old addresses land here: Settings › Accounts, Cubs, and the cubs' own settings pages'
  // aliases (lib/nodes.json).
  import Glyph from "../../ui/Glyph.svelte";
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import Parts from "../../ui/Parts.svelte";
  import Row from "../../ui/Row.svelte";
  import Empty from "../../ui/Empty.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { ui } from "../../lib/shell.svelte";
  import ConnectionsList from "./ConnectionsList.svelte";
  import { NEWSLETTER_API, nlLine, nlSt, type Newsletter } from "./newsletter";
  import { cubsOf, features } from "../../features/index";

  let { view }: { view: View } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const nl = $derived.by(() => {
    void view.tick;
    return host ? read<Newsletter>(NEWSLETTER_API, 15000).data || null : null;
  });
  const nst = $derived(nl ? nlSt(nl) : (["open", "grey", "Not connected"] as const));
  // the posting cubs (the newsletter, the toot, the blog, and any cub that posts or sends)
  const posting = $derived.by(() => {
    void view.tick;
    return cubsOf(features(host)).filter((x) => ["post", "send"].includes(x.manifest.ui.kind || "") || ["newsletter", "toot", "examplecom", "blog"].includes(x.id));
  });
</script>

<List title="Posting" crumb="Settings" sub="Optional: every draft can be copied without an account.">
  <Group id="post-newsletter" title="A newsletter" count="1" kind="sets">
    <Row sel="enl" title="Newsletter" meta={nlLine(nl)} stw={nst}>{#snippet st()}<Glyph name={nst[0]} colour={nst[1]} word={nst[2]} />{/snippet}</Row>
  </Group>
  <Group id="post-voice" title="How you write" count="1" kind="sets" says="your voice, switches and samples: every post follows them">
    <Row title="How you write" href={href("settings/posting/voice")} meta="the voice card, the switches, samples, what reads like AI"></Row>
  </Group>
  {#if host}<Parts {view} parts={[[ConnectionsList, "posting"]]} />{/if}
  <Group id="post-writes" title="What Kranto writes" count={String(posting.length)} kind="sets" says="each one's own settings: when, about what, practice">
    {#each posting as x (x.id)}<Row title={x.title} href={href("settings/" + x.id)} meta={x.enabled ? x.mode || "on" : "off"}></Row>{/each}
    {#if !posting.length}<Empty li text="Nothing writes posts yet." />{/if}
  </Group>
</List>
