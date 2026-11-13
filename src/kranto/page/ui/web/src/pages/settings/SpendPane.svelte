<script lang="ts">
  // Settings › Spend, the pane: watching's month with nothing selected; a cap's field, its Save and
  // Undo when one is selected (every cap is here, the server's one writer). Empty is
  // no cap; what is typed is kept until Save.
  import Detail from "../../ui/Detail.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Loading from "../../ui/Loading.svelte";
  import Pane from "../../ui/Pane.svelte";
  import SaveBar from "../../ui/SaveBar.svelte";
  import SettingField from "../../ui/SettingField.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { app, ui } from "../../lib/shell.svelte";
  import { groupOf, kindLine, SET_ST } from "../../ui/settings";
  import { saveUndo } from "../../ui/save";
  import { capDef, OLD_CAP, type CapDef } from "./caps";
  import { CAPS, capText, capValue, capWord, money, planWords, searchLine, WATCH, xLine, type WatchCaps } from "./spend.svelte";

  let { view }: { view: View } = $props();
  const id = $derived(groupOf(view.w));
  const d = $derived(id ? capDef(OLD_CAP[id] || id.replace(/^cap:/, "")) : null);
  const host = $derived(!!ui.facts?.header.host);
  const reads = $derived.by(() => {
    void view.tick;
    return {
      w: host ? read<WatchCaps>(WATCH, 30000) : null,
      H: (app()?.host() || null) as { spend_this_month_usd?: number; budget_usd?: number | null } | null,
    };
  });

  /** one cap written through the server's writer; Undo writes the cap before it */
  function saveCap(btn: HTMLElement, x: CapDef, now: number | null | undefined): void {
    const L = app();
    if (!L) return;
    const fid = "cap-" + x.key;
    let value: number | null = null;  // read at the press, inside the write: a bad cap is refused in red
    const write = async (v: number | null) => {
      const r = await L.api(WATCH, { [x.field]: v });
      L.afkDrop();
      await L.loadHost();
      return r;
    };
    void saveUndo(btn, {
      write: () => {
        value = capValue(fid, now);
        return write(value);
      },
      undo: () => write(now ?? null),
      what: () => `${x.word.toLowerCase()}, ${capWord(value)}`,
      effect: x.effect,
      after: () => {
        delete CAPS[fid];
      },
    });
  }
</script>

{#snippet month()}
  {#if !host}<p class="muted">Spend is the server's, which is not hosting this page.</p>
  {:else if !reads.w?.data}<Loading error={reads.w?.error} />
  {:else}
    {@const m = reads.w.data}
    {@const H = reads.H}
    {@const pct = H && H.budget_usd ? Math.min(100, (H.spend_this_month_usd || 0) / H.budget_usd * 100) : 0}
    {#if m.plan}<p class="small" id="plan-line">{planWords(m.plan)}</p>{/if}<div class="big">{money(m.spent_usd) || "$0.00"}<span class="muted small">{m.monthly_usd == null ? " this month · no cap" : ` of ${capWord(m.monthly_usd)} this month`}</span></div>{#if H && H.budget_usd != null}<div class="meter" role="img" aria-label={`${Math.round(pct)}% of watching's monthly cap used`}><span style={`width:${pct}%`}></span></div>{/if}{#if xLine(m.x)}<p class="mt" id="spend-x"><strong>{"X reads: "}</strong>{xLine(m.x)}</p>{/if}{#if searchLine(m.search)}<p class="mt" id="spend-search"><strong>{"Live search: "}</strong>{searchLine(m.search)}</p>{/if}
  {/if}
{/snippet}

<Detail back={view.back}>
  {#if !id}
    <Pane title="Totals" lede="Every cap is in the list, under Caps: select one to change it. Empty is no cap." sections={[{ id: "watch", w: "This month" }]}>
      {#snippet kind()}<Glyph name="dot" colour="blue" word="Spend" />{kindLine("spend")}{/snippet}
      {#snippet section()}{@render month()}{/snippet}
    </Pane>
  {:else if !d}
    <div class="pane-empty"><p class="empty">No such cap.</p></div>
  {:else if !host}
    <div class="pane-empty"><p class="empty">{`${d.word} is the server's, which is not hosting this page.`}</p></div>
  {:else if !reads.w?.data}
    <div class="pane-in"><Loading error={reads.w?.error} what="the caps" /></div>
  {:else}
    {@const x = d}
    {@const now = x.get(reads.w?.data || null)}
    {@const st = now == null ? SET_ST.dflt : x.key === "watch" && reads.w?.data?.alarm ? SET_ST.warn : SET_ST.set}
    {@const fid = "cap-" + x.key}
    <Pane title={x.word} lede={x.hint} right={capWord(now)} sections={[{ id: "cap", w: "Cap" }, ...(x.key === "watch" || x.key === "x" || x.key === "search" ? [{ id: "watch", w: "This month" }] : [])]}>
      {#snippet kind()}<Glyph name={st[0]} colour={st[1]} word={st[2]} />{kindLine("spend", "caps")}{/snippet}
      {#snippet section(s)}
        {#if s.id === "cap"}
          {#if x.key === "x" && !xLine(reads.w?.data?.x)}<p class="muted small">X is not connected: this cap applies once it is (Settings › Sources › Accounts › X).</p>{/if}
          {#if x.key === "dive" && reads.w?.data && !reads.w.data.deep_dive.enabled}<p class="muted small">Deep dives are off (Settings › Watching › Deep dives); this applies when they are on.</p>{/if}
          <SettingField id={fid} label={x.word} kind="money" value={fid in CAPS ? CAPS[fid]! : capText(now)} input={(v) => (CAPS[fid] = v)} now={capWord(now)} empty="no cap" />
          <SaveBar id="save-cap" note="Empty is no cap." effect={x.effect} save={(b) => saveCap(b, x, now)} />
        {:else}{@render month()}{/if}
      {/snippet}
    </Pane>
  {/if}
</Detail>
