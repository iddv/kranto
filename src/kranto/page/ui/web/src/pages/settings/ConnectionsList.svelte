<script lang="ts">
  // Settings › Sources › Accounts, the list: your accounts (each opens in the pane: Test, Disconnect, its
  // sources), then the providers (a provider's page is its route: the steps, the paste form, the
  // device box, what it reads). Back from a sign-in (?connected= or ?error=), it says how it went,
  // once, and reads everything of the server again. Without the server, it says so.
  import Glyph from "../../ui/Glyph.svelte";
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import Loading from "../../ui/Loading.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import Row from "../../ui/Row.svelte";
  import Icon from "../../shell/Icon.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { app, ui } from "../../lib/shell.svelte";
  import { acctWords, backWords, CONNECTIONS_API, howWord, provSt, type Account, type Connections, type Provider } from "./connections";

  // part: "reading", the logins sources are read with (Settings › Watching);
  // "posting", the accounts a draft is sent with (Settings › Posting); none: every one
  let { view, part = undefined }: { view: View; part?: string } = $props();
  const host = $derived(!!ui.facts?.header.host);
  // the accounts Kranto posts from: Mastodon's posting connection (mastodon_post), never the
  // read-only one that watches a timeline, which is Watching's (7, Codex 4)
  const POSTING = new Set(["mastodon_post", "sanity"]);
  const fits = (key: string): boolean => (part === "posting" ? POSTING.has(key) : part === "reading" ? !POSTING.has(key) : true);
  // back from a sign-in, once: the flash, the server read again, the address without its words
  $effect(() => {
    const q = view.w.r.q, said = backWords(q), L = app();
    if (!said || !L) return;
    delete q.connected;
    delete q.error;
    L.afkDrop();
    history.replaceState(null, "", part === "posting" ? "#/settings/posting" : "#/settings/watching");
    L.say(said.text, said.kind);
  });
  const c = $derived.by(() => {
    void view.tick; // each draw may find the reads stale
    return host ? read<Connections>(CONNECTIONS_API, 15000) : null;
  });
  const d = $derived(c?.data || null);
  // a newsletter platform is offered under Accounts › Newsletter, Connect a provider
  const prov = (st: Provider["state"]): Provider[] => (d ? d.providers.filter((p) => p.state === st && !p.group && fits(p.key)) : []);
  const accounts = $derived(d ? d.accounts.filter((a) => fits(a.provider)) : []);
  const ids = $derived(part === "posting" ? ["p-acct", "p-avail", "p-no"] : part === "reading" ? ["c-acct", "c-avail", "c-no"] : ["c-acct", "c-avail", "c-no"]);
  const words = $derived(part === "reading" ? ["Logins for sources", "Logins you can add"] : part === "posting" ? ["Posting accounts", "Accounts you can connect"] : ["Accounts", "Accounts you can connect"]);
  const mine = (p: Provider): number => (d ? d.accounts.filter((a) => a.provider === p.key).length : 0);
</script>

{#snippet acct(a: Account)}
  {@const w = acctWords(a)}
  {#snippet reconnect()}<a class="btn sm" href={"#/settings/connections/" + a.provider} title="Reconnect">Reconnect</a>{/snippet}
  <Row sel={"eacct:" + a.id} title={a.provider_name} meta={w.meta} end={a.state === "needs_login" ? reconnect : undefined} stw={w.st}>{#snippet st()}<Glyph name={w.st[0]} colour={w.st[1]} word={w.st[2]} />{/snippet}</Row>
{/snippet}
{#snippet provRow(p: Provider)}
  {@const n = mine(p)}
  {@const m = provSt(p, n)}
  {@const word = n ? (p.key.startsWith("mastodon") ? "Connect another" : "Details") : "Connect"}
  {#snippet connect()}<a class="btn sm" id={"connect-" + p.key} href={"#/settings/connections/" + p.key} title={word}>{word}</a>{/snippet}
  <Row title={p.name} href={"#/settings/connections/" + p.key} meta={[howWord(p), p.state === "not_offered" ? p.reason : p.blurb].filter(Boolean).join(" · ")} end={p.state === "available" ? connect : undefined} stw={m}>{#snippet st()}<Glyph name={m[0]} colour={m[1]} word={m[2]} />{/snippet}</Row>
{/snippet}

{#if !host}
  <List title="Connections" crumb="Settings"><NeedHost what="Connections" /></List>
{:else if !d}
  <List title="Connections" crumb="Settings"><Loading error={c?.error} /></List>
{:else}
  <List title="Connections" crumb="Settings">
    {#if d.unavailable}<div class="flash amber" role="status"><Icon name="warn" /><div>{"Connected accounts are off: " + d.unavailable + "."}</div></div>{/if}
    <Group id={ids[0]!} title={words[0]!} count={String(accounts.length)} kind="conns">
      {#each accounts as a (a.id)}{@render acct(a)}{/each}
      {#snippet foot()}{#if !accounts.length}<p class="more">{part === "posting" ? "None connected: every draft can be copied without one." : "No accounts connected."}</p>{/if}{/snippet}
    </Group>
    <Group id={ids[1]!} title={words[1]!} count={String(prov("available").length)} kind="conns" fold={"sources:connect" + (part ? ":" + part : "")}>{#each prov("available") as p (p.key)}{@render provRow(p)}{/each}</Group>
    {#if prov("not_offered").length}<Group id={ids[2]!} title="Not offered" count={String(prov("not_offered").length)} kind="conns" fold={"sources:not-offered" + (part ? ":" + part : "")}>{#each prov("not_offered") as p (p.key)}{@render provRow(p)}{/each}</Group>{/if}
  </List>
{/if}
