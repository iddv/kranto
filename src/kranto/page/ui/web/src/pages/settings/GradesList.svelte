<script lang="ts">
  // Settings › System › Your grades (#/settings/grades, once settings/learning):
  // what your ▲ and ▼ changed, read from the server's GET /api/grades/summary (taste and the source
  // rule, no model): your grades in the window, the cards they moved, the themes the next ideas run
  // cards in their order (and the ones it skips), the sources.
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import Loading from "../../ui/Loading.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import Row from "../../ui/Row.svelte";
  import Tip from "../../ui/Tip.svelte";
  import { plural } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { ui } from "../../lib/shell.svelte";
  import { GRADES_API, topThemes } from "./grades";
  import type { GradesSummary } from "../../api/afk.gen";

  let { view }: { view: View } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const a = $derived.by(() => {
    void view.tick; // each draw may find the read stale
    return host ? read<GradesSummary>(GRADES_API, 30000) : null;
  });
  const d = $derived(a?.data || null);
  const dayOf = (iso: string): string => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
</script>

<List title="Your grades" crumb="Settings">
  {#if !host}
    <NeedHost what="Your grades" verb="need" />
  {:else if !d}
    <Loading error={a?.error} />
  {:else}
    {@const c = d.counts}
    {@const i = d.ideas}
    {@const s = d.sources}
    <Group id="g-grades" title="Your grades" kind="sets">
      {#snippet right()}<Tip id={{ text: "A ▲ or ▼ on a card or on evidence. Nothing here is a model's choice: the order is worked out from what you graded, what Kranto already stores about each card, and how long ago you graded it (a grade counts half after 90 days)." }} about="grades" />{/snippet}
      <Row sel="egrades" title="How your grades are used" meta="one formula, no model: the cards like what you graded rank higher or lower"></Row>
      {#snippet foot()}<p class="more" id="grades-counts">{c.grades ? `${c.grades} in ${d.window_days} days: ${plural(c.cards, "on a card", "on cards")}, ${c.evidence} on evidence` + (c.cleared ? `; ${c.cleared} cleared.` : ".") : `None in ${d.window_days} days. A ▲ or ▼ on a card or a piece of evidence is a grade.`}</p>{/snippet}
    </Group>
    <Group id="g-ideas" title="Ideas" count={String(i.moved)} kind="sets">
      {#each i.top as x (x.id)}
        <Row sel={"gidea:" + x.id} href={href("ideas/" + x.id)} title={x.title} meta={`#${x.id} · ${x.line}` + (x.position ? ` · now ${x.position} of ${i.shown}` : "")}></Row>
      {/each}
      {#snippet foot()}<p class="more" id="grades-ideas">{i.moved ? `${plural(i.moved, "card ranks", "cards rank")} higher or lower because of them; ${i.still} ${i.still === 1 ? "is" : "are"} where ${i.still === 1 ? "it" : "they"} would be anyway.` : "No card has moved yet: an upvote lifts the cards like it, a downvote sinks them."}</p>{/snippet}
    </Group>
    {@const shownThemes = topThemes(d.themes)}
    <Group id="g-themes" title="The next ideas run" count={String(d.themes.length)} kind="sets">
      {#each shownThemes as t (t.lineage_id)}
        <Row sel={"gtheme:" + t.lineage_id} title={t.name || t.lineage_id} meta={(t.skip ? "skipped this run: " : "") + (t.line || "")} stw={t.skip ? ["held", "amber", "Skipped"] : null}>{#snippet num()}{(t.taste > 0 ? "+" : "") + t.taste.toFixed(2)}{/snippet}</Row>
      {/each}
      {#snippet foot()}<p class="more" id="grades-themes">{d.themes.length ? `The themes your grades reach, in the order the next ideas run cards them${d.themes.length > shownThemes.length ? ` (the first ${shownThemes.length - d.themes.filter((t) => t.skip).length} and every one it skips; ${d.themes.length - shownThemes.length} more after them)` : ""}; one your downvotes sank is left out until they fade.` : "Your grades reach no theme of the latest map: the next ideas run cards in its usual order."}</p>{/snippet}
    </Group>
    {#if s}<Group id="g-sources" title="Sources" count={String(s.recommended.length)} kind="sets">
      {#each s.recommended as x (x.id)}
        <Row sel={"gsrc:" + x.id} href={href("settings/sources/" + x.id)} title={x.label} meta={`recommended for removal: ${x.down} of its ${x.down + x.up} graded posts were not useful`}></Row>
      {/each}
      {#each s.kept as x (x.id)}
        <Row sel={"gkept:" + x.id} href={href("settings/sources/" + x.id)} title={x.label} meta={`kept on ${dayOf(x.at)}` + (x.down ? `, after ${x.down} of ${x.down + x.up} graded posts were not useful` : "")}></Row>
      {/each}
      {#snippet foot()}<p class="more" id="grades-sources">{s.recommended.length ? `Needs you asks whether to remove ${s.recommended.length === 1 ? "it" : "them"}; nothing is removed without your approval.` : "None recommended for removal." + (s.closest ? ` Closest: ${s.closest.label}, ${s.closest.down} of ${s.closest.down + s.closest.up} graded posts not useful.` : "")}{` A source is offered for removal when ${s.remove_after} or more of its posts in ${s.window_days} days were downvoted and at most a quarter as many upvoted.`}</p>{/snippet}
    </Group>{/if}
  {/if}
</List>
