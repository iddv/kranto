<script lang="ts">
  // What an assistant just prepared, in a corner of whichever page is open: one line
  // (who prepared what; several merge: "3 waiting: review"), the action's own button (the owner's
  // approval, the same as in Needs you: its dialog reads it back first) and Open. A thin bar runs
  // down over 8 s; hovering pauses it; on time out nothing happens, the item stays in Needs you. A
  // locked kind (a key, consent) offers Open only.
  import { buttonOf, toastLine } from "../lib/prepared";
  import { closeToast, openPrepared, PTOAST, TOAST_MS } from "./prepared.svelte";

  const one = $derived(PTOAST.items.length === 1 ? PTOAST.items[0]! : null);
</script>

{#if PTOAST.items.length}
  <div class="ptoast" id="prepared-toast" role="status" aria-live="polite"
    onmouseenter={() => (PTOAST.paused = true)} onmouseleave={() => (PTOAST.paused = false)}
    onfocusin={() => (PTOAST.paused = true)} onfocusout={() => (PTOAST.paused = false)}>
    <span class="mark" aria-hidden="true">✦</span>
    <span class="grow">{toastLine(PTOAST.items)}</span>
    {#if one && !one.locked}<button type="button" class="btn sm primary" id="ptoast-act" onclick={() => { closeToast(); openPrepared(one); }}>{buttonOf(one)}</button>{/if}
    <a class="btn sm" id="ptoast-open" href="#/needs" onclick={() => closeToast()}>Open</a>
    <button type="button" class="linkish x" aria-label="Close" onclick={() => closeToast()}>✕</button>
    <span class="bar" aria-hidden="true" style={`width: ${(100 * PTOAST.left) / TOAST_MS}%`}></span>
  </div>
{/if}

<style>
  .ptoast { position: fixed; top: 56px; right: 16px; z-index: 41; display: flex; align-items: center; gap: 8px; max-width: min(520px, calc(100vw - 32px)); padding: 9px 12px 11px; border: 1px solid var(--violet); border-left-width: 4px; border-radius: 8px; background: var(--box); font-size: 13px; overflow: hidden; }
  .mark { color: var(--violet); }
  .grow { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .x { text-decoration: none; opacity: .8; }
  .bar { position: absolute; left: 0; bottom: 0; height: 3px; background: var(--violet); transition: width .1s linear; }
  @media (max-width: 700px) {
    .ptoast { top: auto; bottom: 72px; left: 8px; right: 8px; max-width: none; }
    .ptoast .btn { min-height: 40px; }
  }
</style>
