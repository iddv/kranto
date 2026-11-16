<script lang="ts">
  // A cub's object you read, as a page (D-11; #/cub/<id>/o/<oid>): when its card
  // says open: page, its body field is the page's text (markdown drawn as text: no HTML, no image,
  // ui/Md), under the shell's head: Home › Cubs › Newsletter › the issue's subject, its card's lines
  // as the facts, Confirm the one primary while a ticket waits, its actions under ⋯, its cites as
  // the evidence.
  import Card from "../../ui/Card.svelte";
  import Empty from "../../ui/Empty.svelte";
  import Loading from "../../ui/Loading.svelte";
  import Md from "../../ui/Md.svelte";
  import Page from "../../pages/Page.svelte";
  import type { View } from "../../lib/pages.svelte";
  import type { MenuItem } from "../../lib/app";
  import { read } from "../../lib/reads.svelte";
  import { go, href } from "../../lib/router";
  import { ui } from "../../lib/shell.svelte";
  import { features, featurePath, glyphOf, trustWord, type ListDecl } from "../index";
  import { actionOf, askVerb, at, citesOf, cubHref, groupsOf, POST_CRUMB, ticketOf } from "../cub";
  import { cubObjectAct, openAsk } from "../cubverbs";
  import { KIND_WASH } from "../../pages/settings/feature";

  let { view }: { view: View } = $props();
  const H = $derived(!!ui.facts?.header.host);
  const id = $derived(view.w.r.path[1] || "");
  const oid = $derived(decodeURIComponent(view.w.r.path[3] || ""));
  const fs = $derived.by(() => {
    void view.tick;
    return features(H);
  });
  const f = $derived(fs?.features.find((x) => x.id === id) || null);
  // the list it is in: the address's, else the first whose card opens as a page
  const list = $derived.by((): ListDecl | null => {
    const ls = f?.manifest.ui.lists || [];
    return ls.find((l) => l.id === view.w.r.q.list) || ls.find((l) => f!.manifest.ui.cards[l.card]?.open === "page") || ls[0] || null;
  });
  const card = $derived(list && f ? f.manifest.ui.cards[list.card] || null : null);
  const data = $derived.by(() => {
    void view.tick;
    return f && list ? read<Record<string, unknown>>(featurePath(f.id, list.read), 20000) : null;
  });
  const o = $derived(list ? groupsOf(list, data?.data).flatMap((g) => g.items).find((x) => String(x.id) === oid) || null : null);
  const body = $derived(o && card?.body ? at(o, card.body) : null);
  // a page's text is at most 200,000 characters
  const text = $derived(typeof body === "string" ? body.slice(0, 200000) : null);
  const tid = $derived(o ? ticketOf(o) : null);
  const cites = $derived(o && card?.origin ? citesOf(at(o, card.origin)) : []);
  const base = $derived(f ? { crumb: [POST_CRUMB, { to: "cub/" + f.id, w: f.title }], glyph: glyphOf(f.manifest.ui.glyph), wash: KIND_WASH[f.manifest.ui.kind || ""] || "grey", trust: { w: trustWord(f.trust), cls: f.trust }, gear: "settings/" + f.id } : {});
  const more = $derived.by((): MenuItem[] => {
    if (!f || !o || !card) return [];
    const out: MenuItem[] = [];
    for (const k of card.actions) {
      const ac = actionOf(f, k);
      if (ac && !ac.fields.length) out.push({ label: ac.title, id: "page-" + k, run: (b) => cubObjectAct(f, ac, o, {}, b) });
    }
    out.push({ label: "Its sheet", id: "page-sheet", title: "The card, its fields and its actions", run: () => go("cub/" + f.id, { ...(list ? { list: list.id } : {}), sel: "o" + oid }) });
    return out;
  });
  const titleOf = $derived(o && card ? String(at(o, card.title) ?? o.title ?? oid) : oid);
  const facts = $derived(o && card ? card.lines.map((k) => at(o, k)).filter((v) => typeof v === "string" && v).concat(typeof o.state === "string" ? [o.state] : []).join(" · ") : "");
</script>

{#if !H || !fs}
  <Page head={{ title: id, crumb: [POST_CRUMB] }}>{#snippet body()}{#if !H}<Empty text="Features come from the server, which is not hosting this page." />{:else}<Loading />{/if}{/snippet}</Page>
{:else if !f}
  <Page head={{ title: id, crumb: [POST_CRUMB] }}>{#snippet body()}<Empty text={`There is no feature called ${id} on this Kranto.`} link={{ href: "#/post", w: "Post ›" }} />{/snippet}</Page>
{:else if !o}
  <Page head={{ ...base, title: f.title }}>{#snippet body()}{#if !data?.data}<Loading error={data?.error} what={list ? `its ${list.word.toLowerCase()}` : "it"} />{:else}<Empty text="That is not in its list any more." link={{ href: cubHref(f.id, { list: list?.id }), w: `${f.title} ›` }} />{/if}{/snippet}</Page>
{:else}
  <Page head={{ ...base, title: titleOf, label: titleOf, crumb: [...(base.crumb || []), { to: `cub/${f.id}/o/${encodeURIComponent(oid)}`, w: titleOf.length > 48 ? titleOf.slice(0, 47) + "…" : titleOf }],
      facts, primary: tid ? { label: askVerb(f, fs.request_schemas), id: "page-confirm", run: (b) => openAsk({ cub: f.id, ticket: tid, again: null }, b) } : null, more }}
    evidenceWord="What it rests on">
    {#snippet body()}
      {#if text}<div class="cub-body"><Md text={text} /></div>
      {:else}<Empty text={`Its text is not here: it is in the draft (${String(o.where || "its platform")}). An issue or a post drafted from now on keeps it.`} />{/if}
      {#if card}<details class="fold"><summary>Its card</summary><Card schema={card} object={o} /></details>{/if}
    {/snippet}
    {#snippet evidence()}{#if cites.length}<ul class="ctx small">{#each cites as c, i (c.label + i)}<li>{#if c.url}<a href={c.url} target="_blank" rel="noopener noreferrer">{c.title || c.label}</a>{:else if c.obs != null}<a href={href("library/o/" + c.obs)}>{c.title || c.label}</a>{:else if c.brief != null}<a href={href("news/b/" + c.brief)}>{c.title || c.label}</a>{:else}{c.title || c.label}{/if}{#if c.n > 1}<span class="muted">{` · ${c.n} items`}</span>{/if}<span class="n mono">{c.date || ""}</span></li>{/each}</ul>{:else}<p class="muted small">It names no source.</p>{/if}{/snippet}
  </Page>
{/if}

<style>
  .cub-body { border: 1px solid var(--border); border-radius: 10px; padding: 16px 20px; background: var(--box); max-width: min(72ch, 100%); min-width: 0; overflow-wrap: anywhere; }
  .fold { margin: 14px 0 0; }
  .fold summary { cursor: pointer; color: var(--muted); font-size: 12.5px; }
</style>
