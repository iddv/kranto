<script lang="ts">
  // A list row (WORKSPACE.md 1.5;): one line, always. Fixed cells: the tick, the
  // state (a glyph, and its word where the group shows it: .grp.words), the number, the title with
  // its one fact inline after it (the fact gives way first), the aside, the age, the end (its one
  // action, its grade). There is no second line: what explains a row is its pane.
  // sel names the object it opens in the pane (data-sel; markSel finds it there); on, a row in a
  // pane that opens in place (a version). off greys a row that cannot be chosen; hidden and text
  // (data-text, the words a list's filter reads) are for a list that filters as you type. stw: the
  // state's word, after the title and before the meta, shown on a phone too (Settings says it
  // beside every glyph, UP #10).
  import type { Snippet } from "svelte";
  import { ui } from "../lib/shell.svelte";
  import { stOfWord } from "./settings";
  import { rowMark, touched } from "../term/reflect.svelte";

  let {
    title, href = null, sel = null, go = null, isNew = false, cur = false, hot = false, asideText = false,
    off = false, hidden = false, text = null, on = null, stw = null, tick, st, num, meta, aside, age, end, grade,
  }: {
    title: string; href?: string | null; sel?: string | null; go?: string | null; isNew?: boolean;
    cur?: boolean; hot?: boolean; asideText?: boolean; off?: boolean; hidden?: boolean; text?: string | null; on?: ((e: MouseEvent) => void) | null;
    stw?: readonly [string, string, string] | null;
    tick?: Snippet; st?: Snippet; num?: Snippet; meta?: Snippet | string | null; aside?: Snippet; age?: string | null; end?: Snippet; grade?: Snippet;
  } = $props();
  const sw = $derived(stw && ui.area === "settings" ? stOfWord(stw[2]) || stw : null);
  const cls = $derived(["row lr", isNew ? "new" : "", off ? "off" : ""].filter(Boolean).join(" "));
  // an assistant's verb touched it a moment ago (term/reflect: "✦ Add topic, by Claude Code")
  const touchedBy = $derived(touched.rows && rowMark(sel));
</script>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
<li class={cls + (touchedBy ? " touched" : "")} onclick={on} data-sel={sel} data-go={go} data-new={isNew ? "" : null} data-cur={cur ? "" : null} data-text={text} {hidden}><span class="c-tick">{@render tick?.()}</span><span class="c-st">{@render st?.()}</span><span class={"c-num" + (hot ? " hot" : "")}>{@render num?.()}</span><span class="c-main">{#if href}<a class="r-title" {href} {title}>{title}</a>{:else}<span class="r-title" {title}>{title}</span>{/if}{#if sw}<span class={"stw c-" + sw[1]}>{sw[2]}</span>{/if}{#if touchedBy}<span class="touched-by">{touchedBy}</span>{/if}{#if meta}<span class="c-meta">{#if typeof meta === "string"}{meta}{:else}{@render meta()}{/if}</span>{/if}</span><span class={"c-aside" + (asideText ? " txt" : "")}>{@render aside?.()}</span><span class="c-age">{age || ""}</span><span class="c-end">{#if end}<span class="r-act">{@render end()}</span>{/if}{@render grade?.()}</span></li>
