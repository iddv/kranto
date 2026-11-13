<script lang="ts">
  // The one thing: the single item Needs you and the home open with, drawn
  // large: what it is and who raised it in one muted line, its title, one line of why, and its
  // action, the page's one primary. Chosen by rule (today.ts nextOf), never by a model; the row
  // it stands for leaves its group, so it is never said twice. At most 30 words.
  import type { Snippet } from "svelte";
  import { openDetails } from "./details.svelte";

  let { kind, title, why = null, href = null, sel = null, details = null, tone = "violet", act }: {
    /** "prepared by Claude Code, 14 min ago" (after "Next ·") */
    kind: string; title: string; why?: string | null; href?: string | null; sel?: string | null;
    /** the record's sel (kranto_details): Details opens it in the drawer */
    details?: string | null;
    /** the left bar's colour: violet for what waits to go out, amber or red for a fix */
    tone?: string; act?: Snippet;
  } = $props();
</script>

<section class={"next t-" + tone} id="next" data-sel={sel} aria-labelledby="next-h">
  <p class="nk"><b>Next</b>{" · " + kind}</p>
  <h2 id="next-h">{#if href}<a {href}>{title}</a>{:else}{title}{/if}</h2>
  {#if why}<p class="why">{why}</p>{/if}
  <div class="acts r-act">{@render act?.()}{#if details}<button type="button" class="linkish nd" id="next-details" onclick={() => openDetails(details)}>Details ›</button>{/if}</div>
</section>

<style>
  .next { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 4px 16px; align-items: center; padding: 12px 16px 12px 16px; margin: 4px 0 12px;
    border: 1px solid var(--border); border-left: 4px solid var(--tone, var(--violet)); border-radius: 10px; background: var(--box); }
  .t-violet { --tone: var(--violet); } .t-amber { --tone: var(--amber); } .t-red { --tone: var(--red); } .t-blue { --tone: var(--blue); } .t-green { --tone: var(--green); }
  .nk { grid-column: 1; font-size: 12px; color: var(--muted); margin: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .nk b { color: var(--tone); font-weight: 600; }
  h2 { grid-column: 1; font-size: 17px; font-weight: 650; line-height: 1.3; margin: 0; overflow-wrap: anywhere; }
  h2 a { color: var(--text); }
  h2 a:hover { color: var(--link); }
  .why { grid-column: 1; font-size: 13px; color: var(--muted); margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .acts { grid-column: 2; grid-row: 1 / 4; display: flex; flex-direction: column; align-items: flex-end; gap: 6px; }
  .acts :global(.btn.primary) { padding: 5px 14px; font-size: 13px; }
  .nd { font-size: 12px; color: var(--muted); background: none; border: 0; padding: 0; cursor: pointer; }
  .nd:hover { color: var(--link); }
  @media (max-width: 759px) {
    .next { grid-template-columns: minmax(0, 1fr); }
    .acts { grid-column: 1; grid-row: auto; flex-direction: row; align-items: center; margin-top: 6px; }
    .acts :global(.btn) { min-height: 36px; }
    .why { white-space: normal; }
  }
</style>
