<script lang="ts">
  // A detail page's grade, under its title, on one line: "Your grade ▲ ▼ · why ▾". The
  // why chips are a popover (whyPop) that opens after a grade (as Pass asks why) and on why ▾;
  // the keys a–f press them (ui/ticks.svelte.ts's gradeKeys finds this bar by data-why-target).
  // WHYCUR keeps what the page drew, so a key knows the grade's reasons.
  import Grade from "./Grade.svelte";
  import { chipsOf, gkey, whyPop, WHYCUR } from "./grades.svelte";
  import { app, ui } from "../lib/shell.svelte";

  // compact (a card's sheet, D4's 12 controls): no why ▾ button; the
  // why chips still open after a grade, beside the bar, and the keys a–f still press them
  let { target, id, current = null, what, compact = false }: { target: string; id: number | string | null | undefined; current?: unknown; what: string; compact?: boolean } = $props();
  const host = $derived(!!ui.facts?.header.host || !!app()?.host());
  const chips = $derived(host ? chipsOf(target) : []);
  let why = $state<HTMLElement>();
  let bar = $state<HTMLElement>();
  $effect.pre(() => {
    if (id != null) WHYCUR[gkey(target, id)] = current;
  });
  /** after a grade: the why chips, under why ▾ or (compact) beside the bar */
  function asked(g: unknown): void {
    if (!g || id == null) return;
    const at = why && why.isConnected ? why : compact && bar && bar.isConnected ? bar : null;
    if (at) whyPop(at, target, id, { what }, true);
  }
</script>

{#if host && id != null}<div class="gh line" data-why-target={target} data-why-id={String(id)} bind:this={bar}><span class="muted small">Your grade</span><Grade {target} {id} {current} {what} done={asked} />{#if chips.length && !compact}<button type="button" class="linkish small whyb" aria-haspopup="dialog" title="Why? (a–f, after a grade)" bind:this={why} onclick={(e) => whyPop(e.currentTarget, target, id, { what })}>why ▾</button>{/if}</div>{/if}
