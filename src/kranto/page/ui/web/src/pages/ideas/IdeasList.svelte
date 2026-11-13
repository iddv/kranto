<script lang="ts">
  // Ideas, as one list of the server's cards (H1: /api/ideas alone, never the build loop's
  // snapshot): unfiltered, grouped Waiting · Later · Posted · Passed by each card's own state (a
  // filter or a search makes them one group, Matching), Waiting in the server's rank order (your
  // grades first, then what resembles them), the rest newest first. A row's pane is the
  // card's sheet (IdeaPane). At most fourteen of Waiting before Show all; Later, Posted and Passed
  // start folded to their names and counts, opened by their ▸ and
  // remembered. With no card yet, the page says when the first come (the map's own next run).
  import { cardIdeas, cardX as cardOne, IDEAS_API, topicCards } from "./cards";
  import FilterBar from "../../ui/FilterBar.svelte";
  import { SvelteSet } from "svelte/reactivity";
  import Group from "../../ui/Group.svelte";
  import PageTitle from "../../ui/PageTitle.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { app } from "../../lib/shell.svelte";
  import { href } from "../../lib/router";
  import { listRoute } from "../data.svelte";
  import { plural } from "../../lib/format";
  import IdeaLine from "./IdeaLine.svelte";
  import { PRODUCT } from "../../lib/product";
  import { cardIdea, firstWords, IDEA_GROUPS, IDEA_SELECTS, match, rankOrder, sinceGroup, stOf, type CardX, type IdeasFirst } from "./ideas";

  let { view }: { view: View } = $props();
  // no model chosen yet: the empty page says the one press that moves it on
  const noModel = $derived.by(() => {
    void view.tick;
    return !!app()?.host() && read<{ key?: { set?: boolean } }>("/api/setup", 30000).data?.key?.set === false;
  });
  const r = $derived(listRoute(view.w));
  const q = $derived(r.q);
  const host = $derived(!!app()?.host());
  // the cards, read again on their schedule: with ?topic=, only that topic's, filtered by the server
  //; the owner's dispatch cards are their own read (?source=dispatch)
  const ci = $derived.by(() => {
    void view.tick;
    if (!host) return null;
    return q.topic ? topicCards(q.topic) : cardIdeas();
  });
  const dispatch = $derived.by(() => {
    void view.tick;
    return host && q.source === "dispatch" ? read<{ ideas?: Record<string, unknown>[] }>("/api/ideas?origin=dispatch&embedding=ref", 60000).data : null;
  });
  const all = $derived.by((): CardX[] => {
    if (q.source === "dispatch") return ((dispatch?.ideas || []) as unknown[]).map((x) => cardOne(x)).filter((x): x is CardX => !!x);
    return ci?.list || [];
  });
  // when the first cards come, while there are none (the server's ``first``)
  const first = $derived.by(() => {
    void view.tick;
    return host && !q.topic && ci && !ci.list.length ? read<{ first?: IdeasFirst }>(IDEAS_API, 30000).data?.first || null : null;
  });
  const topicName = $derived(q.topic ? ((app()?.host()?.topics as { id: number; name: string }[] | undefined) || []).find((t) => String(t.id) === q.topic)?.name || "topic " + q.topic : "");
  const text = (x: CardX): string => [x.title, String(x.raw?.one_liner || ""), (x.topics || []).map((t) => t.name).join(" "), stOf(x.state)[0]].join(" ");
  const xs = $derived(all.filter((x) => (!q.status || (x.state || "waiting") === q.status) && (!q.kind || x.raw?.pitch_kind === q.kind) && match(q.q, text(x)))
    .sort((a, b) => String(b.raw?.created_at || "").localeCompare(String(a.raw?.created_at || ""))));
  const since = $derived(sinceGroup(xs, (q as Record<string, string | undefined>).since));
  const filtered = $derived(!!(q.status || q.source || q.kind || q.q || q.topic || since));
  const posOf = (x: CardX): number | null | undefined => x.rank?.position;
  const groups = $derived(since ? [{ k: "since", w: since.w, xs: since.xs }] : filtered ? [{ k: "match", w: "Matching", xs }] : IDEA_GROUPS.map(([k, w]) => {
    const g = xs.filter((x) => (x.state || "waiting") === k);
    return { k, w, xs: k === "waiting" ? rankOrder(g, posOf) : g };
  }).filter((g) => g.xs.length));
  const FIRST = 14;
  const opened = new SvelteSet<string>();       // Show all, for this page's life
  const at = $derived(new Map(groups.flatMap((g) => g.xs).map((x, n) => [x.number, n])));
  const waiting = $derived(all.filter((x) => (x.state || "waiting") === "waiting").length);
  const sub = $derived(since ? `${since.xs.length} of ${all.length}` : filtered ? `${xs.length} of ${all.length}` : `${plural(all.length, "idea")} · ${waiting} waiting`);
</script>

<div class="wl" data-title="Ideas"><PageTitle title="Ideas" facts={all.length ? sub : ""} /><div class="tb"><span class="tbn filters"><FilterBar r={{ path: ["ideas"], q, sel: null }} base="ideas" placeholder="Search ideas" selects={IDEA_SELECTS as never} /></span></div>
  {#if q.topic}<p class="topic-only" id="topic-only">Ideas of <a href={href("topics/" + q.topic)}>{topicName}</a><span class="muted"> · </span><a href={href("ideas", { ...q, topic: "" })}>All topics</a></p>{/if}
  {#if since}<p class="topic-only" id="ideas-since">{since.w}<span class="muted"> · </span><a href={href("ideas", { ...q, since: "" })}>All ideas</a></p>{/if}
  {#if !xs.length || (since && !since.xs.length)}
    {#if !all.length && !since && noModel}<p class="empty" id="ideas-empty">{`No ideas yet. They come from what ${PRODUCT} keeps: `}<a href="#/welcome">{`set up ${PRODUCT} first ›`}</a></p>
    {:else}<p class="empty" id="ideas-empty">{since && all.length ? "No idea was written since then." : all.length ? "No ideas match." : first ? firstWords(first) : q.topic ? "No ideas from this topic yet." : "No ideas yet: they come from your topics, after the first map."}</p>{/if}
  {:else}
    {#each groups as g (g.k)}
      {@const rows = opened.has(g.k) || g.xs.length <= FIRST ? g.xs : g.xs.slice(0, FIRST)}
      {#snippet more()}{#if rows.length < g.xs.length}<div class="more"><button type="button" class="linkish" data-show-all={g.k} onclick={() => opened.add(g.k)}>{`Show all ${g.xs.length}`}</button></div>{/if}{/snippet}
      <Group id={"id-" + g.k} title={g.w} count={String(g.xs.length)} kind="ideas" fold={filtered ? null : "ideas:" + g.k} start={!filtered && g.k !== "waiting"} foot={more}>
        {#each rows as x (x.number)}<IdeaLine i={cardIdea(x)} {x} at={at.get(x.number) ?? 0} />{/each}
      </Group>
    {/each}
  {/if}
</div>
