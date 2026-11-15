<script lang="ts">
  // A cub's sheet (D6: one sheet): drawn by the shell's one sheet in the new frame
  // (j k, the focus trap, esc) and in the pane beside the list in the classic one, never a sheet of
  // the cub page's own. By the selection (sel=): an object (o<id>, or a first-party page's own
  // letter) is its card, its actions and Confirm on an open ticket, with "Open in full" when its card
  // opens as a page; a form (form:<id>) or a head action that takes input (act:<kind>) is its
  // fields. With nothing chosen (the classic pane), what the cub is.
  import Card from "../../ui/Card.svelte";
  import Detail from "../../ui/Detail.svelte";
  import Loading from "../../ui/Loading.svelte";
  import Pane from "../../ui/Pane.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { ui } from "../../lib/shell.svelte";
  import { features, featurePath, trustWord, type FeatureRow, type FormDecl } from "../index";
  import { actionOf, askVerb, cubHref, groupsOf, ticketOf } from "../cub";
  import { cubAct, cubObjectAct, openAsk } from "../cubverbs";

  let { view }: { view: View } = $props();
  const H = $derived(!!ui.facts?.header.host);
  const id = $derived(view.w.r.path[1] || "");
  const fs = $derived.by(() => {
    void view.tick;
    return features(H);
  });
  const f = $derived(fs?.features.find((x) => x.id === id) || null);
  const lists = $derived(f?.manifest.ui.lists || []);
  const forms = $derived(f?.manifest.ui.forms || []);
  const listId = $derived(view.w.r.q.list || lists[0]?.id || "log");
  const list = $derived(lists.find((l) => l.id === listId) || null);
  const sel = $derived(view.w.r.sel || "");
  // an object: sel=o<id> (an id may hold a colon: the newsletter's issue "draft:1"), or a
  // first-party page's own letter
  const objSel = $derived(/^o.+$/.test(sel) || (/^[a-z][^:]+$/.test(sel) && !["settings", "about"].includes(sel)) ? sel.slice(1) : null);
  const data = $derived.by(() => {
    void view.tick;
    return f && f.enabled && list && objSel ? read<Record<string, unknown>>(featurePath(f.id, list.read), 20000) : null;
  });
  const picked = $derived(objSel && list ? groupsOf(list, data?.data).flatMap((g) => g.items).find((o) => String(o.id) === objSel) || null : null);
  const card = $derived(list && f ? f.manifest.ui.cards[list.card] || null : null);
  const form = $derived(sel.startsWith("form:") ? forms.find((x) => x.id === sel.slice(5)) || null : null);
  const headForm = $derived(sel.startsWith("act:") && f ? actionOf(f, sel.slice(4)) : null);
  const back = $derived(cubHref(id, { list: view.w.r.q.list }));
  const kindWord = $derived(form ? form.word.toLowerCase() : headForm ? headForm.title.toLowerCase() : card ? list?.card || "object" : "");
  let formVals = $state<Record<string, unknown>>({});
  $effect(() => {
    void sel;
    formVals = {};
  });
  function submit(x: FeatureRow, fm: FormDecl, btn: HTMLElement): void {
    const ac = actionOf(x, fm.submit);
    if (ac) cubAct(x, ac, { ...formVals }, btn);
  }
</script>

{#snippet fieldsOf(x: FeatureRow, fields: FormDecl["fields"])}
  {#each fields as fd (fd.key)}
    <div class="ffield"><label for={"ff-" + fd.key}>{fd.label}</label>
      {#if fd.kind === "enum"}<select id={"ff-" + fd.key} onchange={(e) => (formVals[fd.key] = e.currentTarget.value)}><option value="">choose…</option>{#each fd.choices as c (c)}<option value={String(c)}>{String(c)}</option>{/each}</select>
      {:else if fd.kind === "choice"}{@const cs = fd.read ? ((read<{ choices: { value: string; word: string }[] }>(featurePath(x.id, fd.read), 60000).data?.choices) || []) : fd.choices.map((c) => ({ value: String(c), word: String(c).replace(/_/g, " ") }))}<span class="chips" id={"ff-" + fd.key}>{#each cs as c (c.value)}{@const cur = (formVals[fd.key] as string[] | undefined) || []}<button type="button" class="chip" aria-pressed={cur.includes(c.value) ? "true" : "false"} onclick={() => (formVals[fd.key] = cur.includes(c.value) ? cur.filter((v) => v !== c.value) : [...cur, c.value])}>{c.word}</button>{" "}{/each}</span>
      {:else if fd.kind === "bool"}<button type="button" class="btn sm sw" role="switch" id={"ff-" + fd.key} aria-checked={formVals[fd.key] ? "true" : "false"} onclick={() => (formVals[fd.key] = !formVals[fd.key])}>{formVals[fd.key] ? "Yes" : "No"}</button>
      {:else if fd.kind === "markdown"}<textarea id={"ff-" + fd.key} class="mdfield" rows="12" oninput={(e) => (formVals[fd.key] = e.currentTarget.value)}></textarea>
      {:else if fd.kind === "int" || fd.kind === "usd"}<input id={"ff-" + fd.key} type="number" oninput={(e) => (formVals[fd.key] = e.currentTarget.value === "" ? null : Number(e.currentTarget.value))} />
      {:else}<input id={"ff-" + fd.key} oninput={(e) => (formVals[fd.key] = e.currentTarget.value)} />{/if}
      {#if fd.hint}<span class="hint">{fd.hint}</span>{/if}</div>
  {/each}
{/snippet}

<Detail back={view.back}>
  {#if !f}
    <div class="pane-empty"><p class="empty">{fs ? `There is no cub called ${id} on this Kranto.` : "Loading…"}</p></div>
  {:else if !sel}
    <Pane title={f.title} lede={f.says}>
      {#snippet kind()}{`${trustWord(f.trust)} · ${f.mode} · ${f.version}`}{/snippet}
      {#snippet top()}<p class="muted small">Choose a row to see it here; its settings are on <a href={href("settings/" + f.id)}>Settings › {f.title}</a>.</p>{/snippet}
    </Pane>
  {:else}
    <div class="pane-in cub-sheet" id="cub-sheet" data-title={f.title}>
      <p class="dk mono">{`${f.title} · ${trustWord(f.trust)}${kindWord ? " · " + kindWord : ""}`}</p>
      {#if headForm}
        <h3>{headForm.title}</h3>
        {#if headForm.says}<p class="lede">{headForm.says}</p>{/if}
        {@render fieldsOf(f, headForm.fields)}
        <p class="foot"><a class="btn" href={back}>Cancel</a><button class="btn primary" data-act={headForm.kind} onclick={(e) => cubAct(f, headForm, { ...formVals }, e.currentTarget)}>{headForm.title}</button></p>
      {:else if form}
        <h3>{form.word}</h3>
        {#if form.says}<p class="lede">{form.says}</p>{/if}
        {@render fieldsOf(f, form.fields)}
        <p class="foot"><span class="muted small">{form.cost}</span><button class="btn primary" onclick={(e) => submit(f, form, e.currentTarget)}>{form.word}</button></p>
      {:else if picked && card}
        <Card schema={card} object={picked} />
        {@const tid = ticketOf(picked)}
        <p class="acts">{#if tid}<button class="btn primary" data-act="ask-open" onclick={(e) => openAsk({ cub: f.id, ticket: tid, again: null }, e.currentTarget)}>{askVerb(f, fs?.request_schemas)}</button>{/if}
          {#if card.open === "page"}<a class="btn" id="cub-open-page" href={href(`cub/${f.id}/o/${encodeURIComponent(String(picked.id))}`, { list: view.w.r.q.list })}>Open in full</a>{/if}
          {#each card.actions as k (k)}{@const ac = actionOf(f, k)}{#if ac && !ac.fields.length}<button class="btn" data-act={k} onclick={(e) => cubObjectAct(f, ac, picked, {}, e.currentTarget)}>{ac.title}</button>{/if}{/each}</p>
        {#each card.actions as k (k)}{@const ac = actionOf(f, k)}{#if ac && ac.fields.length}
          <div class="actform"><h4>{ac.title}</h4>{@render fieldsOf(f, ac.fields)}<button class="btn sm" data-act={k} onclick={(e) => cubObjectAct(f, ac, picked, { ...formVals }, e.currentTarget)}>{ac.title}</button></div>
        {/if}{/each}
      {:else if objSel && !data?.data}
        <Loading error={data?.error} what="this list" />
      {:else}
        <p class="empty">{objSel ? "That is not in this list any more." : "Nothing to show here."}</p>
      {/if}
    </div>
  {/if}
</Detail>

<style>
  .cub-sheet .dk { color: var(--muted); font-size: 12.5px; margin: 0 0 8px; }
  .cub-sheet h3 { font-size: 16px; font-weight: 650; margin-bottom: 6px; }
  .acts { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  .actform { margin-top: 14px; padding-top: 10px; border-top: 1px solid var(--border-2); }
  .actform h4 { font-size: 13px; margin-bottom: 4px; }
  .ffield { display: flex; flex-direction: column; gap: 4px; margin: 8px 0; }
  .ffield .hint { color: var(--muted); font-size: 11.5px; }
  .ffield .mdfield { font-family: var(--mono); font-size: 12.5px; line-height: 1.5; min-height: 12em; resize: vertical; width: 100%; box-sizing: border-box; }
  .foot { display: flex; align-items: center; gap: 10px; justify-content: space-between; margin-top: 12px; }
  .lede { color: var(--muted); max-width: 70ch; margin-bottom: 12px; }
</style>
