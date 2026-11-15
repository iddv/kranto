<script lang="ts">
  // A dialog's frame (#dlg's children): its title, its body, Cancel (the cursor's place unless the
  // body takes it) and the main button. ok gets that button; the dialog decides when to close.
  // more: buttons between Cancel and the main one (an ask's Schedule and its waiting Send); an
  // empty okText draws no main button, and cancelText names Cancel (Close once it is done).
  // details: the subject's sel; the foot's left says Details, which opens the record (the kit's
  // decision dialog, the policy and the history are Details', not the dialog's).
  import type { Snippet } from "svelte";
  import { openDetails } from "./details.svelte";

  let { title, okText, ok, close, okClass = "", disabled = false, cancelText = "Cancel", details = null, more, children }: {
    title: string; okText: string; ok: (btn: HTMLElement) => unknown; close: () => void; okClass?: string; disabled?: boolean;
    cancelText?: string; details?: string | null; more?: Snippet; children: Snippet;
  } = $props();
</script>

<div class="dlg-h" id="dlg-t">{title}</div>
<div class="dlg-b">{@render children()}</div>
<!-- svelte-ignore a11y_autofocus -->
<div class="dlg-f">{#if details}<button type="button" class="linkish dlg-details" id="dlg-details" onclick={() => openDetails(details)}>Details</button>{/if}<button class="btn" autofocus onclick={close}>{cancelText}</button>{@render more?.()}{#if okText}<button class={"btn " + (okClass || "primary")} id="dlg-ok" {disabled} onclick={(e) => void ok(e.currentTarget)}>{okText}</button>{/if}</div>
