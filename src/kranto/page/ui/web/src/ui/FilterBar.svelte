<script lang="ts" module>
  /** a select: its key in the URL, its name, its options as [value, words] */
  export type Select = [string, string, [string, string][]];
</script>

<script lang="ts">
  // A list's filters in its toolbar (WORKSPACE.md 1.4): the search (/), then compact dropdowns;
  // the state lives in the URL. two filters or more fold into Filter ▾, the active ones
  // chips beside it, each with ×; the sort stays inline.
  import { go, type Route } from "../lib/router";
  import { closePop, popWith } from "./pop";
  import FilterPop from "./FilterPop.svelte";

  let { r, base, placeholder, selects }: { r: Route; base: string; placeholder: string; selects: Select[] } = $props();
  const sorts = $derived(selects.filter((s) => s[0] === "sort"));
  const filters = $derived(selects.filter((s) => s[0] !== "sort"));
  const active = $derived(filters.filter(([k, , opts]) => r.q[k] && opts.some(([v]) => v === r.q[k])));
  const to = (key: string, v: string) => go(base, { ...r.q, [key]: v, page: "" });
  /** Enter applies the search and hands the keys back to the list (j moves the cursor, not the
   * text); esc leaves the box, and an emptied box clears the search (QA B5) */
  function search(e: KeyboardEvent): void {
    const el = e.currentTarget as HTMLInputElement;
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation(); // this esc only leaves the box: the sheet or the selection stays
      release(el);
      if (!el.value.trim() && r.q.q) to("q", "");
      return;
    }
    if (e.key !== "Enter") return;
    e.preventDefault();
    release(el);
    to("q", el.value.trim());
  }
  /** the list filters as you type, a moment after the typing stops, the cursor kept in the box
   * (17, Codex 22, Gemini 16: Ideas filtered only on Enter, with no hint) */
  let typing: ReturnType<typeof setTimeout> | undefined;
  function typed(e: Event): void {
    const el = e.currentTarget as HTMLInputElement;
    clearTimeout(typing);
    typing = setTimeout(() => {
      const v = el.value.trim();
      if (v === (r.q.q || "").trim()) return;
      to("q", v);
      requestAnimationFrame(() => {
        const s = document.getElementById("search") as HTMLInputElement | null;
        if (s && document.activeElement !== s) {
          s.focus({ preventScroll: true });
          s.setSelectionRange(s.value.length, s.value.length);
        }
      });
    }, 350);
  }
  function release(el: HTMLInputElement): void {
    el.blur();
    document.getElementById("rows")?.focus({ preventScroll: true });
  }
  /** Filter ▾'s popover: one select per filter, labelled; a change applies it */
  function pop(anchor: HTMLElement): void {
    const el = popWith(anchor, "Filters", FilterPop, { filters, q: r.q, pick: (k: string, v: string) => { closePop(false); to(k, v); } }, "filters");
    (el?.querySelector("select") as HTMLElement | null)?.focus();
  }
</script>

{#snippet sel([key, name, opts]: Select)}<select class="tb-f" aria-label={name} onchange={(e) => to(key, e.currentTarget.value)}>{#each opts as [v, w] (v)}<option value={v} selected={(r.q[key] || "") === v}>{`${name.toLowerCase()} ${w || "all"}`}</option>{/each}</select>{/snippet}

<input type="search" id="search" class="tb-q" placeholder={placeholder + "  ( / )"} aria-label={placeholder} value={r.q.q || ""} onkeydown={search} oninput={typed} />{#if filters.length < 2}{#each filters as s (s[0])}{@render sel(s)}{/each}{:else}<button type="button" class="btn sm fbtn" id="filter" aria-haspopup="dialog" title="Filters" onclick={(e) => pop(e.currentTarget)}>Filter{#if active.length}<span class="n">{String(active.length)}</span>{/if} ▾</button><span class="fchips">{#each active as [key, name, opts] (key)}<span class="fchip">{`${name.toLowerCase()} ${(opts.find(([v]) => v === r.q[key]) || [])[1] || r.q[key]}`}<button type="button" aria-label={`Clear the ${name.toLowerCase()} filter`} title="Clear" onclick={() => to(key, "")}>×</button></span>{/each}</span>{/if}{#each sorts as s (s[0])}{@render sel(s)}{/each}
