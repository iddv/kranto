<script lang="ts">
  // An idea card from a topic as one row (a topic's Ideas and Overview): its state on Ideas
  // (the server's own: waiting, later, posted, passed; H1), #n, the title over its citations,
  // its signals, the topic's share of it, Later's date, the score and the grade. The title opens
  // the card's sheet (#/ideas/<n>), where Pass and Later are.
  import Glyph from "../../ui/Glyph.svelte";
  import Grade from "../../ui/Grade.svelte";
  import Row from "../../ui/Row.svelte";
  import { ago, n3, pct, plural } from "../../lib/format";
  import { href } from "../../lib/router";
  import { rankLine, signalsText, stOf, type CardX } from "./ideas";

  let { x }: { x: CardX; t?: { id: number; name: string } } = $props();
  const s = $derived(stOf(x.state || "waiting"));
  const later = $derived(x.later_until ? "later: until " + new Date(x.later_until).toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : null);
  const meta = $derived([s[0].toLowerCase(), x.cited ? plural(x.cited, "citation") : null, x.status === "unsupported" ? "evidence unsupported" : null, signalsText(x.signals),
    x.share != null && x.share < 1 ? `${pct(x.share)} from this topic` : null, later, rankLine(x)].filter(Boolean).join(" · "));
  const created = $derived(Date.parse(String(x.raw?.created_at || "")) / 1000 || null);
</script>

<Row title={x.title} href={href("ideas/" + x.number)} {meta} age={created ? ago(created) : null}>
  {#snippet st()}<Glyph name={s[1]} colour={s[2]} word={s[0]} />{/snippet}
  {#snippet num()}{"#" + x.number}{/snippet}
  {#snippet aside()}{x.score != null ? n3(x.score) : ""}{/snippet}
  {#snippet grade()}<Grade target="idea" id={x.number} current={x.grade} what={"card #" + x.number} />{/snippet}
</Row>
