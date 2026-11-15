<script lang="ts">
  // The version, pressable: "Kranto 0.5.10 · Check for updates". The answer is said beside it, in
  // words, with its next step (checkupdates.ts). Drawn in the status bar (both layouts), on
  // Settings' Overview and on Settings › System › Updates; nothing without the server.
  import { app } from "../../lib/shell.svelte";
  import { checkNow, versionNow, type CheckAnswer } from "./checkupdates";

  let { id, cell = false }: { id: string; cell?: boolean } = $props();
  let answer = $state<CheckAnswer | null>(null);
  let busy = $state(false);
  const version = $derived(versionNow());

  async function press(e: MouseEvent): Promise<void> {
    e.stopPropagation();
    e.preventDefault();
    if (busy) return;
    busy = true;
    try {
      answer = await checkNow();
    } finally {
      busy = false;
    }
  }
</script>

{#if version}
  <span class={"vcheck" + (cell ? " cell wide" : "")} {id}>
    <button type="button" class={cell ? "linkish" : "btn sm"} id={id + "-press"} title="Check for updates now" aria-busy={busy ? "true" : null} disabled={busy}
      onclick={press}>{`Kranto ${version} · ${busy ? "Checking…" : answer ? "Check again" : "Check for updates"}`}</button>
    {#if answer}
      <span class={"vc-said c-" + answer.tone} id={id + "-said"} role="status">{answer.text}</span>
      {#if answer.next?.restart}<button type="button" class="btn sm primary" id={id + "-restart"} title="Restart to update: Kranto backs up, installs and checks itself"
          onclick={(e) => { e.stopPropagation(); void app()?.updApply(e.currentTarget); }}>Restart to update</button>
      {:else if answer.next?.href}<a class="vc-next" href={answer.next.href} onclick={(e) => e.stopPropagation()}>{answer.next.word} ›</a>{/if}
    {/if}
  </span>
{/if}

<style>
  .vcheck { display: inline-flex; align-items: center; gap: 8px; flex-wrap: wrap; min-width: 0; max-width: 100%; }
  .vc-said { white-space: normal; }
  /* the version is long on a branch ("Kranto 0.6.0.dev18+oss.a749a10 · Check for updates"): the
     button wraps on a phone rather than run off the screen */
  .vcheck > button { max-width: 100%; white-space: normal; height: auto; min-height: 26px; text-align: left; overflow-wrap: anywhere; }
  .c-green, .c-blue { color: var(--text); }
  .c-red { color: var(--red); }
</style>
