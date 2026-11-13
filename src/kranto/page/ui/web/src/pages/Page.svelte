<script lang="ts" module>
  /** a section of a reading page: s-<id> is its anchor in the outline */
  export interface PageSec {
    id: string;
    w: string;
    n?: string | number | null;
  }
</script>

<script lang="ts">
  // A thing you read, as a page ("you read a page, you act on a sheet"): an article,
  // a brief, a trend's dossier, a newsletter issue, a post. Its head is the shell's (the crumb with
  // the way back, the title, its facts, the standfirst as the lede, the one primary and ⋯: PageHead,
  // from this declaration); under it the page's outline ("On this page", the sections as anchors,
  // in the subnav's underlined style), the body, then the sections, then the evidence (its sources,
  // readable). NEWS fills an article's body and sections; a cub's object page its
  // card's body (cub/<id>/o/<oid>).
  import type { Snippet } from "svelte";
  import PageTitle from "../ui/PageTitle.svelte";
  import type { HeadDecl } from "../lib/app/heads";
  import { app } from "../lib/shell.svelte";

  let { head, sections = [], body, section, evidence, evidenceWord = "Sources", foot }: {
    head: HeadDecl; sections?: PageSec[]; body?: Snippet; section?: Snippet<[PageSec]>; evidence?: Snippet; evidenceWord?: string; foot?: Snippet;
  } = $props();
  const outline = $derived([...sections, ...(evidence ? [{ id: "evidence", w: evidenceWord }] : [])]);
  function jump(e: MouseEvent, id: string): void {
    e.preventDefault();
    const el = document.getElementById("s-" + id);
    if (el) app()?.spyJump(el);
    else document.getElementById("s-" + id)?.scrollIntoView();
  }
</script>

<article class="wl page-read" data-title={head.label || head.title}>
  <PageTitle {...head} outline />
  {#if outline.length > 1}<nav class="doornav page-toc" aria-label="On this page">{#each outline as s (s.id)}<a href={"#s-" + s.id} onclick={(e) => jump(e, s.id)}>{s.w}{#if s.n != null && s.n !== ""}<span class="n">{String(s.n)}</span>{/if}</a>{/each}</nav>{/if}
  {#if body}<div class="page-body">{@render body()}</div>{/if}
  {#each sections as s (s.id)}<section class="page-sec" id={"s-" + s.id}><h2>{s.w}</h2>{@render section?.(s)}</section>{/each}
  {#if evidence}<section class="page-sec page-evidence" id="s-evidence"><h2>{evidenceWord}</h2>{@render evidence()}</section>{/if}
  {@render foot?.()}
</article>
