<script lang="ts">
  // A compacted week as one row (the old page's rollupLine): its mean signal, the week, its label
  // over its summary and size, its main sources and its age. It opens in the pane as sel=u<id> on
  // the list it was read in (base, with the list's filters q).
  import Glyph from "../../ui/Glyph.svelte";
  import Row from "../../ui/Row.svelte";
  import { ago, dt, plural } from "../../lib/format";
  import { href } from "../../lib/router";
  import { mix, rollupSt, type Rollup } from "./library";

  let { x, base, q = {} }: { x: Rollup; base: string; q?: Record<string, string> } = $props();
  const g = $derived(rollupSt(x));
</script>

<Row sel={"u" + x.id} title={x.label} href={href(base, { ...q, sel: "u" + x.id })} meta={[x.summary, plural(x.size, "observation")].filter(Boolean).join(" · ")} asideText age={ago(dt(x.created_at))}>
  {#snippet st()}<Glyph name={g[0]} colour={g[1]} word={g[2]} />{/snippet}
  {#snippet num()}{(x.period_start || "").slice(5, 10)}{/snippet}
  {#snippet aside()}{mix(x.source_mix, 2)}{/snippet}
</Row>
