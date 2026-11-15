<script lang="ts">
  // A prepared item read back once before it is approved (the owner, 2026-10-29: the dialog
  // repeated the whole body as raw text, under a button called Press): what it does, the key
  // fields in a short list (area, labels, where it goes), and a long text drawn as markdown,
  // collapsed to a few lines with Show all (ReadBack, the asks' dialog's too). Its button is the
  // action's own words; Cancel first.
  import DialogFrame from "./DialogFrame.svelte";
  import ReadBack from "./ReadBack.svelte";
  import { dialogSubject, keyFields, longFields, usesChanges, whoOf, type Prepared } from "../lib/prepared";

  let { p, title, okText, onOk, close }: {
    p: Prepared; title: string; okText: string; onOk: (btn: HTMLElement, close: () => void) => unknown; close: () => void;
  } = $props();
</script>

<DialogFrame {title} {okText} ok={(btn) => onOk(btn, close)} {close} details={"prep:" + p.uuid}>
  <p class="pd-who">{`Prepared by ${whoOf(p)}. Nothing happens until you choose ${okText}.`}</p>
  <ReadBack subject={dialogSubject(p)} keys={keyFields(p)} longs={longFields(p)} named={usesChanges(p)} />
</DialogFrame>

<style>
  .pd-who { color: var(--muted); font-size: 13px; margin: 0 0 8px; }
</style>
