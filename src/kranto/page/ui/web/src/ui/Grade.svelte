<script lang="ts">
  // The grade on a card's or an observation's row, or under a sheet's title: ▲
  // useful, ▼ not useful; aria-pressed, never colour alone. A second press on the same glyph clears
  // it. It posts (the verb feedback.add) and presses the glyph in place, never redrawing the page
  // (grades.svelte.ts); the keys 1 2 0 press these buttons on the focused row or the page head.
  // Nothing without the server, which keeps the grades.
  import { GLYPHS, GNOUN, gkey, gradeOf, postGrade, type GradeOpts } from "./grades.svelte";
  import { app, ui } from "../lib/shell.svelte";

  let { target, id, current = null, what = null, origin = undefined, context = undefined, done = null }: {
    target: string; id: number | string | null | undefined; current?: unknown; what?: string | null; origin?: string;
    context?: Record<string, unknown>; done?: GradeOpts["done"];
  } = $props();
  const host = $derived(!!ui.facts?.header.host || !!app()?.host());
  const g = $derived(id == null ? null : gradeOf(target, id, current));

  // a "wrong" written before is a downvote: its ▼ is pressed, and pressing ▼ clears it
  const down = (x: string | undefined): string | undefined => (x === "wrong" ? "not_useful" : x);
  const on = (v: string): boolean => !!g && down(g.value) === v;

  function press(e: MouseEvent, v: string): void {
    e.stopPropagation();
    if (id == null) return;
    const now = gradeOf(target, id, current);
    void postGrade(target, id, now && down(now.value) === v ? "skip" : v, { what: what ?? undefined, origin, context, done, current, reasons: [] });
  }
</script>

{#if host && id != null}<span class="grade" role="group" aria-label={"Grade " + (what || GNOUN[target] || target)} data-grade={gkey(target, id)} data-value={g ? g.value : ""}>{#each GLYPHS as [v, glyph, word, cls, key] (v)}<button type="button" class={cls} data-v={v} data-verb="feedback.add" title={`${word} (${key})`} aria-label={word} aria-pressed={on(v) ? "true" : "false"} onclick={(e) => press(e, v)}>{glyph}</button>{/each}</span>{/if}
