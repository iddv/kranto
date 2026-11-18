<script lang="ts">
  // The scout's proposals as a group: close matches first, wildcards last; each row has its tick
  // (what the foot's button watches), its match to the topic, the label and why, items in 30 days,
  // and on a topic's Sources (approve) Approve.
  import type { Snippet } from "svelte";
  import { SvelteSet } from "svelte/reactivity";
  import { href } from "../../lib/router";
  import Glyph from "../../ui/Glyph.svelte";
  import Group from "../../ui/Group.svelte";
  import Row from "../../ui/Row.svelte";
  import { about, approveSource, perDay, type Proposal } from "./proposals";
  import { fitWords, placeWords } from "../welcome/welcome.svelte";

  // ``busy``: the scout still runs, so an empty list is not yet "found nothing" (  // fix 3); ``plain``: Welcome's words, each row's fit in words and no score
  let { title, tid, rows, ticked, foot, approve = false, name, busy = false, plain = false }: {
    title: string; tid: number | string | null; rows: Proposal[]; ticked: Set<number>; foot?: Snippet; approve?: boolean; name?: string; busy?: boolean; plain?: boolean;
  } = $props();
  // the ticks as they change here (the set is the caller's, kept per topic)
  const on = new SvelteSet<number>();
  let n = $state(0);
  // read again when the rows change: a scout adds rows and ticks its close matches in place
  $effect(() => { void rows; on.clear(); for (const x of ticked) on.add(x); n = ticked.size; });
  const order = $derived(rows.slice().sort((a, b) => Number(a.role === "wildcard") - Number(b.role === "wildcard") || Number(!!b.pretick) - Number(!!a.pretick)
    || ((b.validation || {}).median_similarity || 0) - ((a.validation || {}).median_similarity || 0)));
  // one primary in the group: the first proposal's Approve
  const lead = $derived(order.find((p) => p.review !== "approved")?.id);
  const count = $derived(`${n} ticked · about ${about(perDay(rows.filter((p) => on.has(p.id) || p.review === "approved")))} new items a day`);
  function tick(p: Proposal, yes: boolean): void {
    if (yes) { ticked.add(p.id); on.add(p.id); } else { ticked.delete(p.id); on.delete(p.id); }
    n = ticked.size;
  }
  const n2 = (v: number) => Number(v).toFixed(2);
  const mark = (p: Proposal): [string, string, string] => p.review === "approved" ? ["check", "green", "Active"] : p.role === "wildcard" ? ["dot", "amber", "Further afield"] : p.pretick ? ["check", "blue", "Fits well"] : ["open", "grey", "Proposed"];
</script>

{#snippet right()}<span class="muted">Places further afield are never ticked for you.</span>{/snippet}
{#snippet bottom()}<div class="more pfoot">{#if !rows.length && !busy}<span>No place that could be read was found. Find more, or add a source by hand.</span>{/if}<a href={href("settings/sources/new", { topic: tid })}>Add a source by hand</a><span class="grow"></span><span class="muted">{count}</span>{@render foot?.()}</div>{/snippet}

<Group id={"props-" + (tid || "new")} {title} count={String(rows.length)} kind={"props" + (approve ? " approve" : "")} {right} foot={bottom}>
  {#each order as p (p.id)}
    {@const v = p.validation || {}}
    {@const w = mark(p)}
    {@const watched = p.review === "approved"}
    {#snippet tickBox()}<input type="checkbox" class="ptick" aria-label={"Watch " + p.label} checked={watched || on.has(p.id)} disabled={watched} onchange={(e) => tick(p, e.currentTarget.checked)} />{/snippet}
    {#snippet st()}<Glyph name={w[0]} colour={w[1]} word={w[2]} />{/snippet}
    {#snippet num()}{v.median_similarity != null ? n2(v.median_similarity) : "–"}{/snippet}
    {#snippet aside()}{v.recent != null ? `${v.recent} in 30 d` : "–"}{/snippet}
    {#snippet end()}<button class={"btn sm" + (p.id === lead ? " primary" : "")} title="Approve" onclick={(e) => void approveSource(e.currentTarget, p, tid, name)}>Approve</button>{/snippet}
    <Row sel={approve ? "s" + p.id : null} tick={tickBox} {st} num={plain ? undefined : num} hot={(v.median_similarity ?? 0) >= 0.4} title={p.label} href={approve ? "#/settings/sources/" + p.id : null}
      meta={[plain ? fitWords(p.validation?.median_similarity) || w[2].toLowerCase() : w[2].toLowerCase(), plain ? placeWords(p.site_name) : p.site_name, p.why, p.replaces ? "replaces " + String(p.replaces) : null,
        p.spend ? `X bills about $${p.spend.run_usd.toFixed(2)} a run` : null].filter(Boolean).join(" · ")} {aside} asideText end={approve && !watched ? end : undefined} />
  {/each}
</Group>
