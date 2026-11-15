<script lang="ts" module>
  /** a section of a pane: s-<id> is the outline's anchor and what [ and ] step to; n is a count beside its word */
  export interface Sec {
    id: string;
    w: string;
    n?: string | number | null;
    warn?: boolean;
    about?: string | { text: string; docs?: string } | null;
  }
</script>

<script lang="ts">
  // A whole pane (WORKSPACE.md 1.6; the old page's paneOf() and paneHeader()): the head sticks to
  // the top of the pane: the kind line, the title, a lede, the actions with a note at the right,
  // and the outline ("On this page", one muted line of links, never tabs; the scroll-spy marks
  // the current section). Then notes about the object, then the sections. At most three actions
  // stay in the head (the old page folds the rest into ⋯; no moved pane has more yet).
  import type { Snippet } from "svelte";
  import Tip from "./Tip.svelte";
  import { app } from "../lib/shell.svelte";

  let { title, name = title, kind, lede = null, acts, right = null, top, sections = [], section }: {
    title: string; name?: string; kind: Snippet; lede?: Snippet | string | null; acts?: Snippet; right?: string | null;
    top?: Snippet; sections?: Sec[]; section?: Snippet<[Sec]>;
  } = $props();
  const has = (n: Sec["n"]) => n != null && n !== "";
  // the scroll-spy marks the outline's current section once the sections are drawn
  $effect(() => {
    void sections.length;
    app()?.spy();
  });
  function jump(e: MouseEvent, id: string): void {
    e.preventDefault();
    const el = document.getElementById("s-" + id);
    if (el) app()?.spyJump(el);
    app()?.spy();
  }
</script>

<div class="pane-in" data-title={title}><div class="dh"><p class="dk mono">{@render kind()}</p><h2 class="dt">{name}</h2>{#if lede}<p class="lede" title={typeof lede === "string" ? lede : null}>{#if typeof lede === "string"}{lede}{:else}{@render lede()}{/if}</p>{/if}{#if acts || right}<div class="acts">{@render acts?.()}<span class="grow"></span>{#if right}<span class="muted mono small">{right}</span>{/if}</div>{/if}{#if sections.length > 1}<nav class="toc" aria-label="On this page"><span class="toc-h">On this page</span><ol>{#each sections as s (s.id)}<li><a href={"#s-" + s.id} onclick={(e) => jump(e, s.id)}>{s.w}{#if has(s.n)}<span class={"n" + (s.warn ? " warn" : "")}>{String(s.n)}</span>{/if}</a></li>{/each}</ol></nav>{/if}</div>{@render top?.()}{#each sections as s (s.id)}<section class="sec" id={"s-" + s.id}><h3>{s.w}{#if has(s.n)}<span class={"n mono" + (s.warn ? " warn" : "")}>{String(s.n)}</span>{/if}{#if s.about}<Tip id={s.about} about={s.w} />{/if}</h3>{@render section?.(s)}</section>{/each}</div>
