<script lang="ts">
  // Settings › Spend, the list: where it went this month, by topic (its count
  // is its total, which matches the totals in the pane), then Caps: every cap, one row each
  //. All of it is the server's (/api/spend/topics, /api/settings/spend).
  import Glyph from "../../ui/Glyph.svelte";
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import Loading from "../../ui/Loading.svelte";
  import Row from "../../ui/Row.svelte";
  import SetRow from "../../ui/SetRow.svelte";
  import { plural } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { ui } from "../../lib/shell.svelte";
  import { SET_ST } from "../../ui/settings";
  import { CAP_DEFS } from "./caps";
  import { capWord, cents, otherRows, TOPICS, WATCH, type TopicSpend, type WatchCaps } from "./spend.svelte";

  let { view }: { view: View } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const reads = $derived.by(() => {
    void view.tick;
    return {
      t: host ? read<TopicSpend>(TOPICS, 60000) : null,
      w: host ? read<WatchCaps>(WATCH, 30000) : null,
    };
  });
  const t = $derived(reads.t?.data || null);
  const m = $derived(reads.w?.data || null);
  const caps = $derived(host ? CAP_DEFS : []);
</script>

{#snippet dot(colour: string, word: string)}<Glyph name="dot" {colour} {word} />{/snippet}

<List title="Spend" crumb="Settings">
  {#if !host}
    <Group id="sp-topic" title="By topic" kind="spend">{#snippet right()}<span class="muted">watching</span>{/snippet}{#snippet foot()}<p class="more">Spend is the server's, which is not hosting this page.</p>{/snippet}</Group>
  {:else if !t}
    <Group id="sp-topic" title="By topic" kind="spend">{#snippet foot()}<Loading error={reads.t?.error} />{/snippet}</Group>
  {:else}
    <Group id="sp-topic" title="By topic" about={{ text: "Watching's model calls this month; a shared source's are split." }} count={cents(t.total_usd) + (t.budget_usd == null ? "" : " of " + cents(t.budget_usd))} kind="spend">
      {#each t.topics as x (x.id)}<Row sel={"t" + x.id} title={x.name} meta={plural(x.calls, "call")}>{#snippet st()}{@render dot("blue", "Topic")}{/snippet}{#snippet num()}{cents(x.usd)}{/snippet}</Row>{/each}
      {#if t.broad.calls}<Row title="Broad lane (sources with no topic)" meta={plural(t.broad.calls, "call")}>{#snippet st()}{@render dot("grey", "Broad lane")}{/snippet}{#snippet num()}{cents(t.broad.usd)}{/snippet}</Row>{/if}
      {#each otherRows(t.other) as x (x.purpose)}<Row title={x.word} meta={plural(x.calls, "call")}>{#snippet st()}{@render dot("grey", "Other purpose")}{/snippet}{#snippet num()}{cents(x.usd)}{/snippet}</Row>{/each}
      {#if t.compacted_usd}<Row title="Calls since compacted (retention)" stw={["closed", "grey", "Compacted"]}>{#snippet st()}<Glyph name="closed" colour="grey" word="Compacted" />{/snippet}{#snippet num()}{cents(t.compacted_usd)}{/snippet}</Row>{/if}
    </Group>
  {/if}
  {#if caps.length}
    <Group id="sp-caps" title="Caps" about={{ text: "Every spend cap, in one list. Empty is no cap: spend is uncapped unless you set one." }} count={String(caps.length)} kind="sets">
      {#each caps as x (x.key)}{@const v = x.get(m)}<SetRow key={"cap:" + x.key} word={x.word} summary={!m ? "reading…" : capWord(v) + (x.key === "x" && m && !m.x?.connected ? " · X is not connected" : "")} state={v == null ? SET_ST.dflt : x.key === "watch" && m?.alarm ? SET_ST.warn : SET_ST.set} />{/each}
    </Group>
  {/if}
</List>
