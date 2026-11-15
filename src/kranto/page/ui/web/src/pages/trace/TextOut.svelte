<script lang="ts">
  // A payload's text (a tool's output, a turn's words): untrusted, so drawn as text after
  // safeText (safe.ts), in a scroll box with line numbers; stderr after the output, marked; a
  // long one a page at a time ("Show the next 64 KB").
  import { safeText } from "./safe";

  let { text, stderr = null, error = false, next = null, onmore = null, busy = false }: {
    text: string;
    stderr?: string | null;
    error?: boolean;
    next?: number | null;
    onmore?: (() => void) | null;
    busy?: boolean;
  } = $props();

  const lines = $derived(safeText(text).split("\n"));
  const errLines = $derived(stderr ? safeText(stderr).split("\n") : []);
</script>

<div class="out" class:t-err={error}>
  <ol class="t-code">
    {#each lines as l, i (i)}<li><span class="t-ln">{i + 1}</span><span class="tx">{l}</span></li>{/each}
  </ol>
  {#if errLines.length}
    <p class="small muted">stderr</p>
    <ol class="t-code stderr">
      {#each errLines as l, i (i)}<li><span class="t-ln">{i + 1}</span><span class="tx">{l}</span></li>{/each}
    </ol>
  {/if}
</div>
{#if next != null && onmore}
  <button type="button" class="btn" disabled={busy} onclick={onmore}>{busy ? "Reading…" : "Show the next 64 KB"}</button>
{/if}

<style>
  .out {
    max-height: 60vh;
    overflow: auto;
    border: 1px solid var(--line);
    border-radius: 6px;
    background: var(--sunk);
  }
  .out.t-err {
    border-color: var(--red);
  }
  .t-code {
    list-style: none;
    margin: 0;
    padding: 6px 0;
    font: 12px/1.45 var(--mono);
  }
  .t-code li {
    display: flex;
    gap: 10px;
    padding: 0 8px;
  }
  .t-ln {
    flex: 0 0 3.2em;
    text-align: right;
    color: var(--muted);
    user-select: none;
  }
  .tx {
    flex: 1;
    white-space: pre-wrap;
    word-break: break-word;
    min-width: 0;
  }
  .stderr .tx {
    color: var(--red);
  }
  .btn {
    margin-top: 8px;
  }
</style>
