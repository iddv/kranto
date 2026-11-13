<script lang="ts">
  // The lines an item rests on, readable (Sources;): each its
  // title (a link out when it has an address), where it is from and its date; an observation's
  // record a quiet link after it ("in your library ›", the library's sheet). Never "[obs 9324]",
  // never an ISO date ("Hacker News · 11 Nov":).
  import { cut } from "../../lib/format";
  import { href } from "../../lib/router";
  import { outletOf, shortDay, type BriefSource } from "./news";

  let { sources, numbered = false }: { sources: BriefSource[]; numbered?: boolean } = $props();
</script>

<ol class={"news-sources" + (numbered ? " numbered" : "")}>
  {#each sources as s, i (s.label + i)}
    <li><span class="ns-t">{#if s.url}<a href={s.url} rel="noopener noreferrer" target="_blank">{cut(s.title || s.url, 120)}</a>{:else}{cut(s.title || s.label, 120)}{/if}</span>
      <span class="ns-d">{`${outletOf(s)} · ${s.date ? shortDay(s.date) : "undated"}`}</span>{#if s.kind === "obs" && s.id != null}<a class="ns-obs" href={href("library/o/" + s.id)} title="The record of this line in your library">in your library ›</a>{/if}</li>
  {/each}
</ol>
