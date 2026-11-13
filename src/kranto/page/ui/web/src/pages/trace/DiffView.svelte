<script lang="ts">
  // An edit's or a write's lines: the file, +n −m, the hunks as a unified
  // diff; a new file as its lines; a credentials file's contents never (redaction rule 3).
  import type { TracePayload } from "../../api/types.gen";
  import { safeText } from "./safe";

  let { d }: { d: TracePayload } = $props();
</script>

<p class="small"><span class="mono">{safeText(d.file_path || "")}</span>{#if d.added != null}{" · "}<span class="plus">+{d.added}</span> <span class="minus">−{d.removed}</span>{/if}{#if d.new_file}{" · "}a new file{/if}</p>
{#if d.hidden}
  <p class="flash" role="status">{d.hidden}: a credentials file's contents are never shown.</p>
{:else}
  <div class="t-diff">
    {#each d.hunks || [] as h, i (i)}
      <div class="hh mono">{h.header}</div>
      {#each h.lines as l, j (j)}<div class={"dline mono " + (l.startsWith("+") ? "add" : l.startsWith("-") ? "del" : "")}>{safeText(l)}</div>{/each}
    {/each}
  </div>
{/if}

<style>
  .plus {
    color: var(--green);
  }
  .minus {
    color: var(--red);
  }
  .t-diff {
    border: 1px solid var(--line);
    border-radius: 6px;
    max-height: 60vh;
    overflow: auto;
    font-size: 12px;
  }
  .hh {
    padding: 2px 8px;
    color: var(--muted);
    background: var(--sunk);
  }
  .dline {
    padding: 0 8px;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .dline.add {
    background: var(--green-wash);
  }
  .dline.del {
    background: var(--red-wash);
  }
</style>
