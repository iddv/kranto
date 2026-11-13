<script lang="ts">
  // A session's conversation (the trajectory): you, claude, and the tool calls
  // and their results inline; thinking folded; the selected turn's first message scrolled into
  // view. Every message is untrusted text: claude's as Markdown drawn as text (ui/Md), the rest
  // as plain text, all through safeText first.
  import type { ChatMessage } from "../../api/types.gen";
  import Md from "../../ui/Md.svelte";
  import { safeText } from "./safe";

  let { messages, focus = null, onpick }: { messages: ChatMessage[]; focus?: number | null; onpick: (span: string) => void } = $props();

  let box: HTMLDivElement | undefined = $state();
  $effect(() => {
    if (focus == null || !box) return;
    const el = box.querySelector(`[data-i="${focus}"]`);
    if (el && "scrollIntoView" in el) (el as HTMLElement).scrollIntoView({ block: "start" });
  });
  const who = (m: ChatMessage) => (m.role === "you" ? "you" : m.role === "tool" ? "tool" : "claude");
</script>

<div class="chat" bind:this={box}>
  {#each messages as m (m.i)}
    <div class={"msg " + who(m) + (m.is_error ? " bad" : "")} data-i={m.i} class:t-focus={m.i === focus}>
      <div class="who">
        <span>{who(m)}{#if m.kind === "tool_call"}{" · "}<b>{m.tool}</b>{:else if m.kind === "tool_result"}{" · result"}{#if m.is_error}{" · ✕ error"}{/if}{:else if m.kind === "thinking"}{" · thinking"}{:else if m.kind === "result"}{" · the final answer"}{/if}</span>
        {#if m.span}<button type="button" class="link small" onclick={() => onpick(m.span!)}>the span ›</button>{/if}
      </div>
      {#if m.kind === "thinking"}
        {#if m.text}<details><summary class="small muted">thinking ({safeText(m.text).length} characters)</summary><pre class="pre">{safeText(m.text)}</pre></details>{:else}<p class="small muted">thought here; the transcript keeps no text of it</p>{/if}
      {:else if m.kind === "tool_call" || m.kind === "tool_result"}
        <pre class="pre">{safeText(m.text)}{#if m.cut}{"\n…"}{/if}</pre>
      {:else if m.role === "claude"}
        <Md text={safeText(m.text)} />
      {:else}
        <pre class="pre">{safeText(m.text)}</pre>
      {/if}
    </div>
  {/each}
</div>

<style>
  .chat {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .msg {
    border: 1px solid var(--line);
    border-radius: 8px;
    padding: 8px 10px;
    min-width: 0;
  }
  .msg.you {
    background: var(--blue-wash);
  }
  .msg.tool {
    background: var(--sunk);
  }
  .msg.bad {
    border-color: var(--red);
  }
  .msg.t-focus {
    outline: 2px solid var(--blue);
  }
  .who {
    font-size: 12px;
    color: var(--muted);
    margin-bottom: 4px;
    display: flex;
    gap: 8px;
    align-items: baseline;
  }
  .pre {
    margin: 0;
    white-space: pre-wrap;
    word-break: break-word;
    font: 12px/1.45 var(--mono);
    max-height: 30vh;
    overflow: auto;
  }
  .link {
    margin-left: auto;
    background: none;
    border: 0;
    color: var(--blue);
    cursor: pointer;
    padding: 0;
  }
</style>
