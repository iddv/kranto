<script lang="ts">
  // Add source's pane (the old page's paneCatalog, sPreset and previewBox): a kind chosen in the
  // catalog (sel=epreset:<key>) or a proposal to review (sel=ereview:<id>): its fields, the topic,
  // Preview (one fetch, nothing saved) or the scout's test fetch, then Add source (or Approve and
  // watch; Dismiss on a proposal) and Cancel. A kind read with your account is off until it
  // is connected. What is typed is kept across draws (sources.svelte.ts). Added from a topic's
  // Add source (?topic=), it goes back to that topic's Sources; else to the source.
  import { untrack } from "svelte";
  import Detail from "../../ui/Detail.svelte";
  import FLabel from "../../ui/FLabel.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Loading from "../../ui/Loading.svelte";
  import Pane, { type Sec } from "../../ui/Pane.svelte";
  import Icon from "../../shell/Icon.svelte";
  import { dt, longTime, rel } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { go, parse } from "../../lib/router";
  import { app, ui } from "../../lib/shell.svelte";
  import { dismissSource } from "../topics/proposals";
  import { accessWord, CATALOG_API, findPreset, FORM, previewLine, safeHref, SOURCES_API, sourceForm, type Catalog, type Preview, type SourceForm, type Sources } from "./sources.svelte";

  let { view, id }: { view: View; id: string } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const at = $derived(id.indexOf(":"));
  const k = $derived(id.slice(0, at));
  const v = $derived(id.slice(at + 1));
  const c = $derived.by(() => {
    void view.tick; // each draw may find the reads stale
    return host ? read<Catalog>(CATALOG_API, 60000) : null;
  });
  const cat = $derived(c?.data || null);
  const sc = $derived.by(() => {
    void view.tick;
    return host && cat && k === "review" ? read<Sources>(SOURCES_API) : null;
  });
  const review = $derived(sc?.data ? sc.data.sources.find((s) => String(s.id) === v) || null : null);
  const key = $derived(review ? review.preset : k === "preset" ? v : null);
  const found = $derived(cat ? findPreset(cat, key) : [null, null]);
  const prov = $derived(found[0]);
  const s = $derived(found[1]);
  const stateKey = $derived(review ? "review:" + review.id : "preset:" + key);
  const topic0 = $derived(review ? String(review.topics[0]?.id || "") : String(view.w.r.q.topic || cat?.topics[0]?.id || ""));
  // the form for this kind (or proposal), made when another one is opened
  $effect.pre(() => {
    const sk = stateKey, ok = !!cat && (k === "preset" || !!review), fields = review?.fields || null, t = topic0;
    if (ok) untrack(() => sourceForm(sk, fields, t));
  });
  const f = $derived<SourceForm>(FORM.f && FORM.f.key === stateKey ? FORM.f : { key: stateKey, fields: { ...(review?.fields || {}) }, topic: topic0, preview: null, error: null });
  // opened from a topic's Add source: the kind line names it
  const toTopic = $derived(!review && view.w.r.q.topic ? (cat?.topics.find((t) => String(t.id) === String(view.w.r.q.topic)) || null) : null);
  const login = $derived(!!s && s.access === "login");
  const connected = $derived(!!s && !!s.needs && (cat?.connected[s.needs] || []).some((a) => a.state === "connected"));
  const off = $derived(login && !connected);
  const title = $derived(review ? "Review: " + review.label : prov && s ? `${prov.name}: ${s.name}` : "");
  const from = $derived(review?.validation.from ? `From your list: «${review.validation.from}»` : null);
  const lede = $derived(review ? [review.why, review.replaces && "Replaces " + review.replaces + ".", review.proposed_for && "A wildcard for " + review.proposed_for + ".", from].filter(Boolean).join(" ") || "Proposed by the scout." : s?.blurb || "");
  const p = $derived(f.preview);
  const secs = $derived.by((): Sec[] => [{ id: "details", w: "Details" }, ...(p || review ? [{ id: "preview", w: p ? "Preview" : review?.validation.from ? "The test fetch" : "The scout's test fetch" }] : [])]);

  /** one fetch with what is typed, nothing saved */
  function doPreview(btn: HTMLElement): void {
    const L = app(), form = f;
    if (!L) return;
    void L.act(btn, async () => {
      form.error = null;
      try {
        form.preview = (await L.api("/api/sources/preview", { preset: key, fields: $state.snapshot(form.fields), topic: form.topic || null })) as Preview;
      } catch (e) {
        form.preview = null;
        form.error = (e as Error).message;
      }
    });
  }
  /** Add source, or Approve and watch: a reviewed proposal is approved as it is, unless its
   * fields were changed into another source */
  function add(btn: HTMLElement): void {
    const L = app(), form = f, rv = review;
    if (!L) return;
    const changed = rv && form.preview && form.preview.existing_id !== rv.id;
    void L.act(btn, async () => {
      const r = rv && !changed ? await L.api("/api/sources", { id: rv.id, status: "approved", topic: form.topic || null })
        : await L.api("/api/sources", { preset: key, fields: $state.snapshot(form.fields), topic: form.topic || null });
      L.afkDrop();
      return r;
    }, (r) => {
      const res = r as { id?: number; label?: string } | null;
      const sid = res?.id || rv?.id;
      const from = parse().q.topic; // opened from a topic's Add source: back to its Sources
      FORM.f = null;
      go(from && !rv ? `topics/${from}/sources` : "settings/sources/" + sid);
      L.say(`${res?.label || rv?.label || "The source"} is watched. Its first fetch is the next ingest run.`);
    });
  }
  function dismiss(btn: HTMLElement): void {
    const rv = review;
    if (!rv) return;
    void dismissSource(btn, rv, () => {
      FORM.f = null;
      go("settings/sources");
    });
  }
</script>

{#snippet gone(text: string)}<div class="pane-empty"><p class="empty">{text}</p></div>{/snippet}

<Detail back={view.back}>
  {#if !host}
    {@render gone("Adding a source needs the server, which is not answering.")}
  {:else if !cat}
    <div class="pane-in"><Loading error={c?.error} /></div>
  {:else if k !== "preset" && k !== "review"}
    {@render gone("Nothing to show here.")}
  {:else if k === "review" && !sc?.data}
    <div class="pane-in"><Loading error={sc?.error} /></div>
  {:else if k === "review" && !review}
    {@render gone("No such proposal.")}
  {:else if !s && !review}
    {@render gone("No such kind in the catalog.")}
  {:else}
    {@const st = review ? (["open", "amber", "Proposed"] as const) : login ? (["open", "blue", "With your account"] as const) : (["check", "green", "Public"] as const)}
    {@const sim = previewLine(p, review?.validation || {}).sim}
    <Pane {title} {lede} right={s ? accessWord(s.access) : null} sections={secs}>
      {#snippet kind()}<Glyph name={st[0]} colour={st[1]} word={st[2]} />{review ? " proposed source · review" : ` add source · ${prov?.name}` + (toTopic ? ` · to ${toTopic.name}` : "")}{/snippet}
      {#snippet top()}
        {#if s && login && !connected}<div class="note c-blue" role="status"><Icon name="note" /><div><strong>{"Needs your account. "}</strong>{`This reads with your ${(prov?.name || "").split(" ")[0]} account, read-only. Connect it first under Settings › Watching; the preview is off until then. `}<a href={"#/settings/connections/" + s.needs}>Connect</a></div></div>{/if}
        {#if s && s.retention_days}<div class="note c-grey" role="status"><Icon name="note" /><div>{`Kept ${s.retention_days} days, not the default: the site's terms ask for short retention.`}</div></div>{/if}
        {#if review && !s}<div class="note c-amber" role="status"><Icon name="warn" /><div>This proposal was made before the catalog; approve it as it was tested.</div></div>{/if}
      {/snippet}
      {#snippet section(sec)}
        {#if sec.id === "details"}
          {#each s ? s.fields : [] as x (x.key)}<div class="field"><FLabel forId={"f-" + x.key} text={x.label} hint={x.hint || null} /><input id={"f-" + x.key} style="width:min(100%,420px)" placeholder={x.placeholder} value={String(f.fields[x.key] || "")} disabled={off} oninput={(e) => { f.fields[x.key] = e.currentTarget.value; f.preview = null; }} /></div>{/each}
          <div class="field"><FLabel forId="f-topic" text="Topic" tipId="sources.topic" /><select id="f-topic" onchange={(e) => { f.topic = e.currentTarget.value; f.preview = null; }}><option value="" selected={f.topic === ""}>No topic: every item is judged</option>{#each cat.topics as t (t.id)}<option value={String(t.id)} selected={f.topic === String(t.id)}>{t.name}</option>{/each}</select></div>
          {#if s}<button class="btn" id="preview" disabled={off} onclick={(e) => doPreview(e.currentTarget)}>{p ? "Preview again" : "Preview"}</button>{/if}
          {#if f.error}<div class="note c-red" role="status"><Icon name="x" /><div>{"The preview failed: " + f.error}</div></div>{/if}
        {:else}
          {@const line = previewLine(p, review?.validation || {}).line}
          {@const pre = p ? p.prefilter : cat.prefilter}
          <p><strong>{line}</strong>{sim != null ? `. The prefilter line is ${Number(pre).toFixed(2)}: items below it are not judged.` : ". No topic: every item is judged."}</p>
          <p class="muted small">{p ? "One fetch, nothing saved." : "When it was proposed."}</p>
          {#if p && p.existing_id}<p class="muted small">This source exists already; adding it again approves it.</p>{/if}
          {#if p}<ul class="ctx mt">{#each p.newest as it, i (i)}{@const u = safeHref(it.url || it.link)}<li>{#if it.url || it.link}<a href={u} rel="noopener noreferrer" target="_blank">{it.title}</a>{:else}<span>{it.title}</span>{/if}<span class="n">{#if it.published_at}<time title={longTime(it.published_at)}>{rel(dt(it.published_at))}</time>{/if}</span></li>{/each}</ul>{/if}
          <div class="inline mt"><button class="btn primary" id="add" onclick={(e) => add(e.currentTarget)}>{review ? "Approve and watch" : "Add source"}</button>{#if review}<button class="btn" id="dismiss-source" onclick={(e) => dismiss(e.currentTarget)}>Dismiss</button>{/if}<span class="grow"></span><a href="#/settings/sources/new" onclick={() => (FORM.f = null)}>Cancel</a></div>
        {/if}
      {/snippet}
    </Pane>
  {/if}
</Detail>
