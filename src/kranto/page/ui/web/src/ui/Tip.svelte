<script lang="ts" module>
  // The ? tip: what a new user learns once sits one hover, focus, click or tap
  // away, never in the row's path. Its words are tips.json, keyed by id (tests/page/test_tips.py reads
  // it); "docs": true adds a link to its paragraph on /brb/help (docs/ui-help.md), a string links
  // that paragraph instead. It is the one popover (ui/popover.ts): esc, a click elsewhere,
  // leaving it or scrolling its pane closes it. A hover opens it after 150 ms on a pointer that
  // hovers.
  import TIPS from "./tips.json";

  export interface TipText {
    text: string;
    docs?: string | boolean;
  }
  export const tipText = (id: string): TipText | null => (TIPS as Record<string, TipText>)[id] || null;
  const tipSlug = (id: string): string => id.replace(/[^a-z0-9]+/gi, "-").toLowerCase();
</script>

<script lang="ts">
  import { flushSync, mount, unmount } from "svelte";
  import TipBox from "./TipBox.svelte";
  import { closePop, popNow, popover } from "./popover";

  let { id, about }: { id: string | TipText; about?: string } = $props();
  const t = $derived(typeof id === "string" ? tipText(id) : id);
  const key = $derived(typeof id === "string" ? id : t && t.docs && t.docs !== true ? t.docs : "field");
  let b = $state<HTMLButtonElement>();
  let expanded = $state(false);
  let described = $state<string | null>(null);
  let timer: ReturnType<typeof setTimeout> | undefined;
  let by: string | null = null;
  const hovers = typeof matchMedia === "function" && matchMedia("(hover: hover)").matches;

  const mine = (): boolean => !!b && popNow()?.anchor === b;
  function shut(): void {
    clearTimeout(timer);
    if (mine()) closePop(false);
  }
  function open(how: string): void {
    if (!b || !t) return;
    const P = popNow();
    if (mine() && P) {
      if (how === "click") {
        by = "click";
        P.el.setAttribute("role", "dialog");
      }
      return;
    }
    by = how;
    const docs = t.docs ? tipSlug(t.docs === true ? key : t.docs) : null;
    const pane = b.closest("#dscroll, #rows, #nav, .dlg-b") || document;
    let box: Record<string, unknown> | null = null;
    const el = popover(b, "About " + (about || key), [], {
      onclose: () => {
        expanded = false;
        described = null;
        pane.removeEventListener("scroll", shut);
        if (box) void unmount(box);
        box = null;
      },
    });
    box = mount(TipBox, { target: el, props: { text: t.text, docs } });
    flushSync();
    el.classList.add("tipbox");
    el.id = "tip-" + tipSlug(key);
    el.setAttribute("role", how === "click" ? "dialog" : "tooltip");
    el.addEventListener("mouseleave", () => {
      if (by === "hover") shut();
    });
    pane.addEventListener("scroll", shut, { once: true, passive: true });
    expanded = true;
    described = el.id;
  }
</script>

{#if t && t.text}<button type="button" class="tip" data-tip={key} aria-label={"About " + (about || key.replace(/[._]/g, " "))} aria-expanded={expanded ? "true" : "false"} aria-describedby={described} bind:this={b}
  onclick={(e) => { e.preventDefault(); e.stopPropagation(); if (mine() && by === "click") shut(); else open("click"); }}
  onfocus={() => open("focus")}
  onblur={(e) => { if (!(mine() && popNow()?.el.contains(e.relatedTarget as Node))) shut(); }}
  onkeydown={(e) => {
    if (e.key === "Escape" && mine()) { e.preventDefault(); e.stopPropagation(); closePop(); }
    else if (e.key === "?") { e.preventDefault(); e.stopPropagation(); open("click"); } // not the sheet: this tip
  }}
  onmouseenter={() => { if (!hovers) return; clearTimeout(timer); timer = setTimeout(() => open("hover"), 150); }}
  onmouseleave={(e) => { if (!hovers) return; clearTimeout(timer); if (by === "hover" && mine() && !popNow()?.el.contains(e.relatedTarget as Node)) shut(); }}>?</button>{/if}
