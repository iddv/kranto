<script lang="ts">
  // An idea card as one row of Ideas: its state, #n (the
  // card's name, in the sans face: D-8), the title and one fact: its rank line ("ranked up: like 2
  // cards you upvoted"), else Later's date, else where it came from, else its topic; when
  // it was written; the grade. Its title opens it in the sheet, which has the rest.
  import Glyph from "../../ui/Glyph.svelte";
  import Grade from "../../ui/Grade.svelte";
  import Row from "../../ui/Row.svelte";
  import { ago } from "../../lib/format";
  import { href } from "../../lib/router";
  import { ideaNo, ideaTitle, isDispatch, laterText, PITCH_KIND, rankLine, srcWord, stOf, type CardX, type Idea } from "./ideas";

  let { i, x = null, at = 0 }: { i: Idea; x?: CardX | null; at?: number } = $props();
  const c = $derived(i.card);
  // a card's word is its state on Ideas (Waiting, Later, Posted, Passed: its group's)
  const s = $derived(stOf(x && String(i.id) === String(x.number) ? x.state || "waiting" : i.status));
  const meta = $derived.by(() => {
    // one topic, its name only (its shares and the citations count are on the sheet:)
    const top = x && x.topics && x.topics[0] ? x.topics[0].name : null;
    // the rank line first: it is why the row sits where it does, and the row cuts what
    // does not fit at its end
    return [rankLine(x), laterText(i), isDispatch(i) ? `${PITCH_KIND[c?.pitch_kind || ""] || ""} pitch, your dispatch` : c ? null : "from " + srcWord(i.source), top].filter(Boolean)[0] || "";
  });
  const card = $derived(c && c.number != null ? c.number : null);
</script>

<Row title={ideaTitle(i)} href={href("ideas/" + i.id)} meta={meta || null} age={ago(i.created)}>
  {#snippet st()}<Glyph name={s[1]} colour={s[2]} word={s[0]} />{/snippet}
  {#snippet num()}{card != null ? "#" + card : ""}{/snippet}
  {#snippet grade()}{#if card != null}<Grade target="idea" id={card} current={c?.grade} what={"card " + ideaNo(i)} context={{ position: at + 1 }} />{/if}{/snippet}
</Row>
