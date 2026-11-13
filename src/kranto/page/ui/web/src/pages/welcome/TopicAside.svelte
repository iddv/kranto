<script lang="ts">
  // Add topic's side: the topics so far (the one being added among them) with their sources and
  // items a day, the cap, and what happens next. The pane on #/topics/new (AddTopicPane), the
  // stage's right column on #/welcome/topics.
  import Loading from "../../ui/Loading.svelte";
  import Mark from "../../shell/Mark.svelte";
  import type { Topics } from "../../api/afk.gen";
  import { plural } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { app } from "../../lib/shell.svelte";
  import { SETUP_API, type Setup } from "../settings/keys.svelte";
  import { SOURCES_API, type Sources } from "../settings/sources.svelte";
  import { about, budgetLine, newStep, perDay, TOPIC } from "./welcome.svelte";
  import { PRODUCT, Product } from "../../lib/product";

  let { view, welcome = false }: { view: View; welcome?: boolean } = $props();
  const reads = $derived.by(() => {
    void view.tick; // each draw may find the reads stale
    return { lc: read<Topics>("/api/topics", 20000), sc: read<Sources>(SOURCES_API, 20000), st: read<Setup>(SETUP_API, 30000) };
  });
  const T = $derived(TOPIC.t || newStep());
  // the ticks (a plain Set) are counted again at each draw, as the old page did
  const ticks = $derived.by(() => {
    void view.tick;
    return `${T.ticked.size} ticked of ${T.rows.length} proposed`;
  });
  const d = $derived(reads.lc.data);
  const srcs = $derived(reads.sc.data ? reads.sc.data.sources : []);
  const mine = (tid: number) => srcs.filter((s) => s.review === "approved" && s.topics.some((x) => x.id === tid));
  const active = $derived(d ? d.topics.filter((x) => x.status === "active") : []);
  const watched = $derived(srcs.filter((s) => s.review === "approved"));
  const budget = $derived(reads.st.data ? reads.st.data.budget_usd : (app()?.host()?.budget_usd as number | null | undefined));
</script>

<section class="box aside"><div class="box-h"><h2>Your topics so far</h2></div>{#if !d}<Loading error={reads.lc.error} />{:else if active.length || T.id}<ul>{#each active.filter((x) => x.id !== T.id) as x (x.id)}<li class="row nocost"><div class="r-st"><Mark name="check" colour="green" word="Added" /></div><div class="r-main"><a class="r-title" href={href("topics/" + x.id)}>{x.name}</a><div class="r-meta">{`${plural(mine(x.id).length, "source")} · about ${about(perDay(mine(x.id)))} items a day`}</div></div><div class="r-act"></div><div class="r-time"></div></li>{/each}{#if T.id}<li class="row nocost"><div class="r-st"><Mark name="open" colour="grey" word="Editing" /></div><div class="r-main"><span class="r-title">{T.name}</span><div class="r-meta">{ticks}</div></div><div class="r-act"></div><div class="r-time"></div></li>{/if}</ul>{:else}<p class="empty">None yet.</p>{/if}{#if d}<div class="box-b small muted">{`Together: ${plural(active.length, "topic")}, ${plural(watched.length, "source")}, about ${about(perDay(watched))} new items a day. ${budgetLine(budget)} You can change any of this later under Topics.`}</div>{/if}</section>
<section class="box aside"><div class="box-h"><h2>What happens next</h2></div><div class="box-b small"><p>{`${Product} reads every ${reads.st.data?.every_hours || 3} hours and keeps what fits your sentence. The first brief comes as soon as 8 items are kept, a few minutes into the first read. Each night ${PRODUCT} groups what it kept into themes (the map); ideas come from themes, once 30 items are kept.`}</p>{#if welcome}<p class="mt">Step 3 says what it costs and starts the first read.</p>{/if}</div></section>
