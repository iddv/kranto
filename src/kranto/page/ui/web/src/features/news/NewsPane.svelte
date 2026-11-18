<script lang="ts">
  // Desk › News, the pane: one brief (sel=f<id>): its items, each one or two sentences with why
  // it matters and the lines it rests on (an observation's page, or the dated search result),
  // background items last under Earlier; where the search came from, what it cost and what the
  // checks did. With nothing selected, "Nothing selected.".
  import Card from "../../ui/Card.svelte";
  import Detail from "../../ui/Detail.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Loading from "../../ui/Loading.svelte";
  import Pane from "../../ui/Pane.svelte";
  import { cut, dt, longTime, plural, rel } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { ui } from "../../lib/shell.svelte";
  import { cardOf } from "../index";
  import { ROWS, SEL, SPEND_LINE, briefPath, briefSt, searchLine, type Brief, type BriefItem, type TopicRows } from "./news";

  let { view }: { view: View } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const sel = $derived(view.w.r.sel || view.w.id || "");
  const id = $derived(sel.startsWith(SEL) ? sel.slice(1) : null);
  const c = $derived.by(() => {
    void view.tick; // each draw may find the reads stale
    return host && id ? read<Brief>(briefPath(id), 60000) : null;
  });
  const b = $derived(c?.data || null);
  const topics = $derived(host ? read<TopicRows>(ROWS, 60000).data : null);
  const name = $derived(b ? topics?.topics.find((t) => t.id === b.topic_id)?.name || `topic ${b.topic_id}` : "");
  const card = $derived(cardOf(host, "news", "brief"));
  const dated = $derived((b?.items || []).filter((i) => !i.background));
  const earlier = $derived((b?.items || []).filter((i) => i.background));
  const sourceHref = (s: BriefItem["sources"][number]): string | null => s.kind === "obs" && s.id != null ? href("library/o/" + s.id) : s.url;
</script>

{#snippet gone(text: string)}<div class="pane-empty"><p class="empty">{text}</p></div>{/snippet}
{#snippet item(x: BriefItem, n: number)}
  <article class="brief-item" data-item={String(n)}>
    {#if card}<Card schema={card} object={x as unknown as Record<string, unknown>} />{:else}<h4>{x.headline}</h4><p>{x.body}</p><p class="muted">{x.why}</p>{/if}
    <ul class="ctx small">{#each x.sources as s (s.label)}<li>{#if sourceHref(s)}<a href={sourceHref(s)} rel="noopener noreferrer" target={s.kind === "obs" ? null : "_blank"}>{cut(s.title || s.url || s.label, 90)}</a>{:else}{s.title}{/if}<span class="n mono">{`${s.label} · ${s.date || "undated"}`}</span></li>{/each}</ul>
  </article>
{/snippet}

<Detail back={view.back}>
  {#if !id}
    {@render gone("Nothing selected.")}
  {:else if !host}
    {@render gone("This comes from the server, which is not answering.")}
  {:else if !b}
    <div class="pane-in"><Loading error={c?.error} /></div>
  {:else}
    {@const g = briefSt(b.status)}
    <Pane title={name} lede={b.status === "quiet" ? b.quiet : b.status === "failed" ? `This brief failed: ${b.error}` : null}
          right={plural(b.items.length, "item")}
          sections={[{ id: "items", w: "Items", n: dated.length || null }, ...(earlier.length ? [{ id: "earlier", w: "Earlier", n: earlier.length }] : []), { id: "about", w: "About this brief" }]}>
      {#snippet kind()}<Glyph name={g[0]} colour={g[1]} word={g[2]} />{` brief · ${(b.period_start || "").slice(0, 10)} to ${(b.period_end || "").slice(0, 10)}`}{/snippet}
      {#snippet section(s)}
        {#if s.id === "items"}
          {#each dated as x, i (i)}{@render item(x, b.items.indexOf(x))}{:else}<p class="empty">{b.quiet || "No items."}</p>{/each}
        {:else if s.id === "earlier"}
          {#each earlier as x, i (i)}{@render item(x, b.items.indexOf(x))}{/each}
        {:else}
          <dl class="kv small"><dt>Written</dt><dd><time title={longTime(b.created_at)}>{rel(dt(b.created_at))}</time>{b.trigger === "now" ? " (Brief now)" : ""}</dd><dt>Search</dt><dd>{searchLine(b)}</dd><dt>Model</dt><dd>{b.model || "none"}</dd><dt>Cost</dt><dd>{SPEND_LINE}</dd>
            <dt>Checks</dt><dd>{`${plural(Number(b.checks.dropped_uncited || 0), "item")} dropped for citing nothing, ${plural(Number(b.checks.repeats || 0), "repeat")} of the last brief left out, ${plural(Number(b.checks.cut || 0), "item")} cut to length`}</dd></dl>
          <p class="muted small">Every item rests on the lines it cites: an observation your watchers kept, or a dated search result. Nothing comes from the model's memory.</p>
        {/if}
      {/snippet}
    </Pane>
  {/if}
</Detail>
