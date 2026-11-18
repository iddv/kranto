<script lang="ts">
  // The status bar: the service in one word (Paused,
  // Degraded or Healthy), the version (pressable: Check for updates) and ? keys, with the keys of
  // a chord or a split while one is held. The tokens used today are Settings › Spend's (D-6); the
  // last ingest and the library's size are Activity's and Settings › System's. No links to the old
  // pages: the feed stays on Health › Messages. When the word is not Healthy, the cell after it
  // says why in one line (the server's health.py,) and opens that run's trace.
  import Mark from "./Mark.svelte";
  import VersionCheck from "../pages/settings/VersionCheck.svelte";
  import { CHORD_HINT } from "../lib/keys";
  import { app, ui } from "../lib/shell.svelte";

  const b = $derived(ui.facts?.bar);
  const h = $derived(ui.facts?.hint);
  const hint = $derived.by(() => {
    if (ui.chord) return CHORD_HINT;
    if (ui.split) return "← → resize · ⇧ 64 px · Home End" + (ui.split === "split-nav" ? " · enter icons" : "") + " · double-click resets · esc";
    if (!h) return "";
    const parts: string[] = [];
    if (h.rows) parts.push("j k move");
    if (h.grade) parts.push("1 2 grade");
    if (h.tick) parts.push("x tick");
    if (h.term) parts.push("c Claude Code");
    if (h.review) parts.push("0 skip · a–f why · enter open"); // the queue's keys (the legend under the card is gone)
    if (h.sections) parts.push("[ ] sections");
    return parts.join(" · ");
  });
</script>

{#if b?.preview}<span class="cell preview" id="bar-preview" role="status">{b.preview}</span>{/if}{#if b}<a class="cell health" href={b.why ? b.why.href : "#/settings/health"} title={b.why ? b.why.text : "Health: the service, its runs and its messages"}><Mark name={b.word.icon} colour={b.word.colour} word={b.word.text} /></a>{#if b.why}<a class="cell why" id="health-why" href={b.why.href} title={b.why.text}>{b.why.text}</a>{/if}<VersionCheck id="bar-version" cell /><span class="grow"></span>{#if ui.chord || ui.split}<span class="cell hint wide" id="key-hint">{hint}</span>{/if}<button class="cell linkish" type="button" onclick={() => app()?.keySheet()}>? keys</button>{/if}
