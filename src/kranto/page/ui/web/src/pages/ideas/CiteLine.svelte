<script lang="ts">
  // An idea card that cites an observation, as a row: its state on Ideas (the server's own, 
  // H1), number and title, its score and topics; the title opens the card (#/ideas/<n>).
  import { n3 } from "../../lib/format";
  import { href } from "../../lib/router";
  import Glyph from "../../ui/Glyph.svelte";
  import Row from "../../ui/Row.svelte";
  import { ideaStatus } from "./cards";
  import { stOf, type CardX } from "./ideas";

  let { x }: { x: CardX } = $props();
  const s = $derived(stOf(ideaStatus(x)));
  const meta = $derived([s[0].toLowerCase(), x.score != null ? "score " + n3(x.score) : null, (x.topics || []).map((t) => t.name).join(", ")].filter(Boolean).join(" · "));
</script>

<Row title={x.title} href={href("ideas/" + x.number)} {meta}>
  {#snippet st()}<Glyph name={s[1]} colour={s[2]} word={s[0]} />{/snippet}
  {#snippet num()}{"#" + x.number}{/snippet}
</Row>
