<script lang="ts">
  // A source as one row (WORKSPACE.md 1.5;): its state, the label and one fact
  // ("Kranto recommends removing it" when your downvotes say so, the source rule; else why the
  // scout proposed it; else the topics it feeds, on a topic's rows the others), the last
  // fetch; Approve on a proposal whose topic is known and a quiet ✕ to dismiss any proposal (D-4;
  // Undo in the toast). Items a day, kept, yield, its kind and description are its sheet's.
  // On a topic's rows a watched source has ⋯: Remove from <topic>, then Mute, Read less and
  // Retire, which say their reach. Its pane has the verbs.
  import { approveSource, dismissSource } from "../topics/proposals";
  import { removeFrom, removeNote, rowMenu } from "./sourceverbs";
  import Glyph from "../../ui/Glyph.svelte";
  import Row from "../../ui/Row.svelte";
  import { ago, dt } from "../../lib/format";
  import { app } from "../../lib/shell.svelte";
  import { muteWord, proposalTopic, srcSt, topicWords, type Source } from "./sources.svelte";

  let { s, bare = false, approve = false, current = undefined, at = 0, here = null, primary = true, remove = false }: {
    s: Source; bare?: boolean; approve?: boolean; current?: unknown; at?: number;
    /** Remove (from here) is the row's visible verb rather than ⋯ (the Edit sheet,) */
    remove?: boolean;
    /** drawn among a topic's own rows: the topic a proposal is approved for, and the others it also feeds are said */
    here?: { id: number; name: string } | null;
    /** Approve is the group's primary (one per group: the first proposal's) */
    primary?: boolean;
  } = $props();
  const m = $derived(srcSt(s.status));
  const watched = $derived(s.review === "approved");
  const topics = $derived.by(() => {
    void at;
    return (app()?.host()?.topics as { id: number; name: string }[] | undefined) || null;
  });
  // on a topic's rows a proposal is approved for that topic (a wildcard for none), as its Sources page does
  const tid = $derived(approve && s.review === "proposed" ? (here ? (s.group === "wildcard" ? null : here.id) : proposalTopic(s, topics)) : undefined);
  // Dismiss (UP #8) beside Approve on every proposal, whether or not its topic is known
  const asks = $derived(approve && s.review === "proposed");

  function approveIt(e: MouseEvent): void {
    const L = app();
    if (!L || tid === undefined) return;
    const role = s.group === "wildcard" ? "wildcard" : (s as Source & { role?: string | null }).role ?? null;
    void approveSource(e.currentTarget as HTMLElement, { ...s, role }, tid, here && tid === here.id ? here.name : (topics || []).find((x) => x.id === tid)?.name);
  }
</script>

{#snippet removeBtn()}<button type="button" class="btn sm quiet" data-act="te-remove" title={removeNote(s.topics.filter((x) => x.id !== here?.id))} onclick={(e) => here && void removeFrom(e.currentTarget, { id: s.id, label: s.label, topics: s.topics.length }, here)}>Remove</button>{/snippet}
{#snippet moreBtn()}<button type="button" class="btn sm more row-more" aria-haspopup="menu" aria-label={`${s.label}: remove from ${here?.name}, mute or retire`} title="Remove from this topic, mute or retire (.)" onclick={(e) => here && rowMenu(e.currentTarget, { id: s.id, label: s.label, topics: s.topics.length, others: s.topics.filter((x) => x.id !== here.id) }, here)}>⋯</button>{/snippet}
{#snippet approveBtn()}<span class="acts2">{#if tid !== undefined}<button class={"btn sm" + (primary ? " primary" : "")} title="Approve: watched from the next run" onclick={approveIt}>Approve</button>{/if}<button class="btn sm quiet" data-act="dismiss" aria-label={`Dismiss ${s.label}`} title="Dismiss: not watched, and not proposed again (Undo in the toast)" onclick={(e) => void dismissSource(e.currentTarget, s)}>✕</button></span>{/snippet}

<Row sel={"s" + s.id} title={s.label} href={"#/settings/sources/" + s.id} age={s.last_fetch ? ago(dt(s.last_fetch)) : null}
  meta={[s.removal?.recommend ? "Kranto recommends removing it" : null, s.mute ? muteWord(s.mute) : null, s.review === "proposed" ? s.why : null, topicWords(s, here?.id), s.detail].filter(Boolean)[0] || null}
  end={asks ? approveBtn : here && watched && s.topics.some((x) => x.id === here.id) ? (remove ? removeBtn : moreBtn) : undefined}>
  {#snippet st()}<Glyph name={m[0]} colour={m[1]} word={m[2]} />{/snippet}
</Row>

<style>
  /* the row's ⋯ (a topic's rows,): where there is a pointer it shows on hover or focus,
     beside the end cell as Mute does (a narrow column has no room beside the grade); on a phone it
     is always in the row */
  @media (hover: hover) {
    :global(.lr .c-end .btn.row-more) { position: absolute; right: calc(100% + 2px); top: 50%; transform: translateY(-50%); background: var(--box); }
    :global(.row.lr:not(:hover):not(:focus-within):not(.sel) .c-end .btn.row-more) { display: none; }
  }
</style>
