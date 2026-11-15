<script lang="ts">
  // Library › Observations, the pane (WORKSPACE.md 2.1): an observation (#/library/o/<id>), the
  // judge's words, its source and the topics it feeds (why it is here:), the idea cards that cite it, its neighbourhood and the judgment;
  // one read of /api/observations/<id>; away from the library too (sel=o<id> on Today or a
  // topic's page). A search's compacted week (sel=u<id>) is Rollups' pane. With nothing
  // selected, "Nothing selected.". The theme is the map's, when Map has read it (no read of its
  // own). Its kind line says "Seen": the page's JSON has no new flag (only the library's rows
  // do), as the old page drew it. The grade, Cited by (the cards and News briefs the server says cite
  // it, drawn from the old module's cached idea cards) and Explain are the old module's, shared with Today until it moves.
  import { muteMenu } from "../settings/sourceverbs";
  import Explain from "../../ui/Explain.svelte";
  import { keepOpen, OPENED } from "../../ui/opened.svelte";
  import { citedBy } from "../ideas/cards";
  import CiteLine from "../ideas/CiteLine.svelte";
  import Detail from "../../ui/Detail.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import GradeHead from "../../ui/GradeHead.svelte";
  import Loading from "../../ui/Loading.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import Pane, { type Sec } from "../../ui/Pane.svelte";
  import Icon from "../../shell/Icon.svelte";
  import { cut, dt, firstSentence, longTime, n3, rel, tokText, tokTitle } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { app, ui } from "../../lib/shell.svelte";
  import ObsLine from "./ObsLine.svelte";
  import RollupPane from "./RollupPane.svelte";
  import { n2, obsHref, words, type ObservationPage } from "./library";
  import { mapTheme } from "./map.svelte";
  import { topicList } from "../settings/sources.svelte";
  import type { SourceLink } from "../../api/afk.gen";

  let { view }: { view: View } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const rollup = $derived(view.w.object === "need" && !!view.w.id?.startsWith("u"));
  const id = $derived(view.w.object === "observation" && view.w.obj ? String(view.w.obj[2]) : null);
  const c = $derived.by(() => {
    void view.tick; // each draw may find the reads stale
    return host && id ? read<ObservationPage>(`/api/observations/${encodeURIComponent(id)}?k=12`, 60000) : null;
  });
  const o = $derived(c?.data || null);
  const cited = $derived.by(() => {
    void view.tick; // null until the idea cards are read
    return o ? citedBy(o.id, o.cited_by?.ideas) : null;
  });
  const theme = $derived.by(() => {
    void view.tick;
    return o ? mapTheme(o.id) : null;
  });
  const secs = $derived.by((): Sec[] => !o ? [] : [{ id: "summary", w: "Summary" }, { id: "source", w: "Source" },
    ...(o.dive_children.length ? [{ id: "step", w: "One step away", n: o.dive_children.length }] : []),
    ...(cited ? [{ id: "cited", w: "Cited by", n: cited.length + (o.cited_by?.briefs.length || 0) }] : []),
    { id: "hood", w: "Neighbourhood" }, { id: "nearby", w: "Nearby", n: o.neighbours.length }, { id: "judgment", w: "Judgment" }]);

  const judged = $derived((o ? [["content quality", o.content_quality], ["durability", o.durability], ["opportunity", o.opportunity]] : []) as [string, number][]);
  // why it is in a topic: the topics its source feeds (an older the server does not say)
  const tops = $derived(o?.topics || []);
  const feedsWords = (ts: SourceLink[]): string => (!ts.length ? "feeds no topic: every item from it is judged" : ts.length === 1 ? `feeds ${ts[0]!.name} (its only topic)` : `feeds ${topicList(ts)}`);
  const whyHere = (ts: SourceLink[], sim: number | null | undefined): string =>
    (ts.length ? `its source feeds ${topicList(ts)}` : "its source feeds no topic") + (sim != null ? `; judged at similarity ${n2(sim)} to ${ts.length === 1 ? ts[0]!.name : "its topic"}` : "");

  function mute(e: MouseEvent, x: ObservationPage): void {
    // its menu says the reach: a mute acts on every topic the source feeds
    if (x.source_id && x.source_label) muteMenu(e.currentTarget as HTMLElement, { id: x.source_id, label: x.source_label, topics: ((x as { topics?: unknown[] }).topics || []).length });
  }
  /** an X post's observation: Remove this post (a deletion request), after a confirm */
  const fromX = (x: ObservationPage): boolean => x.source_kind === "x" || x.source_kind === "xai_search";
  function remove(x: ObservationPage): void {
    const L = app();
    if (!L) return;
    const body = document.createElement("p");
    body.textContent = "the server removes this observation and the model calls behind it now, through the recorded purge, with no rollup made from it; the purge record says it was removed at your request. The post is never read again.";
    L.dialog("Remove this post?", [body], "Remove", (btn, close) => void L.act(btn, async () => {
      const r = await L.api(`/api/observations/${x.id}/remove`, {});
      L.afkDrop();
      return r;
    }, (r) => {
      close();
      L.say((r as { message: string }).message);
      location.hash = "#/library";
    }), "");
  }
</script>

{#snippet when(at: string | null | undefined)}{#if at}<time title={longTime(at)}>{rel(dt(at))}</time>{/if}{/snippet}

{#if rollup}
  <RollupPane {view} />
{:else}
  <Detail back={view.back}>
    {#if !id}
      <div class="pane-empty"><p class="empty">Nothing selected.</p></div>
    {:else if !host}
      <NeedHost what="The library" verb="needs" />
    {:else if !o}
      <div class="pane-in" data-title="Observation">{#if c?.error && /not found/i.test(c.error)}<p class="empty">{`No observation ${id}. It may have been compacted into a weekly rollup.`}</p>{:else}<Loading error={c?.error} />{/if}</div>
    {:else}
      {@const kw = words(o.kind)}
      <Pane title={"Observation #" + o.id} name={firstSentence(o.summary) || o.title || "#" + o.id} lede={o.title} right={"signal " + n2(o.signal)} sections={secs}>
        {#snippet kind()}<Glyph name="dot" colour="grey" word="Seen" />{` observation #${o.id} · ${kw}` + (tops.length ? " · " + topicList(tops) : "")}{/snippet}
        {#snippet acts()}{#if o.source_url}<a class="btn sm" href={o.source_url} rel="noopener noreferrer" target="_blank">Open original ↗</a>{/if}{#if o.source_id && o.source_label}<button class="btn sm quiet" type="button" id="mute-obs" onclick={(e) => mute(e, o)}>Mute source</button>{/if}{#if fromX(o)}<button class="btn sm quiet" type="button" id="remove-post" onclick={() => remove(o)}>Remove this post</button>{/if}{/snippet}
        <!-- the grade is a line under the title, one section fewer -->
        {#snippet top()}<GradeHead target="observation" id={o.id} current={o.grade} what="this observation" />{#if o.override}<div class="note c-amber" role="status"><Icon name="warn" /><div><strong>{"Override. "}</strong>{o.override_reason || ""}</div></div>{/if}{/snippet}
        {#snippet section(s)}
          {#if s.id === "summary"}
            <p class="prose">{o.summary}</p>{#if o.why_it_matters}<p class="muted mt"><strong>{"Why kept: "}</strong>{o.why_it_matters}</p>{/if}
          {:else if s.id === "source"}
            <dl class="kv small"><dt>Source</dt><dd>{#if o.source_id}<a href={"#/settings/sources/" + o.source_id}>{o.source_label || "source"}</a><span class="muted" id="obs-feeds">{" · " + feedsWords(tops)}</span>{:else}{o.source_label || "imported"}{/if}</dd>{#if o.source_id}<dt>Why here</dt><dd id="obs-why-here">{whyHere(tops, o.topic_similarity)}</dd>{/if}<dt>Kind</dt><dd>{kw}</dd><dt>Kept</dt><dd>{@render when(o.created_at)}</dd>{#if o.item_published_at}<dt>Published</dt><dd>{o.item_published_at.slice(0, 10)}</dd>{/if}{#if theme}<dt>Theme</dt><dd><a href={href("library/clusters/" + theme.cluster)}>{theme.label}</a></dd>{/if}</dl>
            {#if o.source_excerpt}<blockquote class="excerpt muted">{o.source_excerpt}</blockquote>{/if}
            {#if o.source_url}<p class="mono muted small url">{o.source_url}</p>{:else}<p class="muted small">No link to the original.</p>{/if}
            {#if o.dive_parent}{@const p = o.dive_parent}<p class="muted mt">{`Read one step from another item (${p.relation}): `}<a href={obsHref(p.id)}>{`#${p.id} ${cut(p.title || p.summary, 80)}`}</a>.</p>{/if}
          {:else if s.id === "step"}
            <ul class="lst pl">{#each o.dive_children as x (x.id)}<ObsLine o={{ ...x, kind: x.relation, source_label: "linked" }} />{/each}</ul>
          {:else if s.id === "cited"}
            {#if cited && cited.length}<ul class="lst pl">{#each cited as x (x.number)}<CiteLine {x} />{/each}</ul>{/if}
            {#if o.cited_by?.briefs.length}<p class="small">{"News: "}{#each o.cited_by.briefs as b, n (b)}{n ? ", " : ""}<a href={href("news/earlier", { sel: "f" + b })}>{`brief #${b}`}</a>{/each}</p>{/if}
            {#if !(cited && cited.length) && !o.cited_by?.briefs.length}<p class="muted small">None yet.</p>{/if}
          {:else if s.id === "hood"}
            {#if o.synthesis}
              <p>{o.synthesis.text}</p><p class="muted small mt">{"Written by a model from this observation and its nearest neighbours; numbers refer to "}{#each o.synthesis.input_ids as x, i (i)}{i ? " " : ""}<a href={obsHref(x)}>{`[${i + 1}]`}</a>{/each}.</p>
            {:else}
              <Explain body={{ observation_id: o.id }} what="this neighbourhood" />
            {/if}
          {:else if s.id === "nearby"}
            {#if o.neighbours.length}<ul class="lst pl">{#each o.neighbours as x (x.id)}<ObsLine o={x} />{/each}</ul>{:else}<p class="empty">Nothing else yet.</p>{/if}
          {:else}
            <dl class="kv small">{#each judged as [k, v] (k)}<dt>{k}</dt><dd class="mono">{n2(v)}</dd>{/each}</dl>
            <p class="mono mt">{`signal = ${n2(o.content_quality)} × ${n2(o.durability)} × ${n2(o.opportunity)} = ${n3(o.signal)}`}</p>
            <div class="meter" role="img" aria-label={`signal ${n2(o.signal)} of 1`}><span style={`width:${Math.min(100, (o.signal || 0) * 100)}%`}></span></div>
            {#if (o.tags || []).length}<p class="small muted">{o.tags.join(", ")}</p>{/if}
            <dl class="kv small mt"><dt>admitted by</dt><dd>{words(o.admitted_by || "–") + (o.topic_similarity != null ? ` (${n2(o.topic_similarity)})` : "")}</dd></dl>
          {/if}
        {/snippet}
      </Pane>
    {/if}
  </Detail>
{/if}
