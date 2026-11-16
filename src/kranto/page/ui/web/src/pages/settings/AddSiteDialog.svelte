<script lang="ts">
  // Settings › Posting's Add a site: every site Kranto offers, one line each with Add or Remove
  // (and, for a ticked one, whether its posts end with the disclosure line: off by default);
  // then "Not possible today", the sites Kranto does not offer, each with its reason. Nothing
  // posts from here.
  import DialogFrame from "../../ui/DialogFrame.svelte";
  import { read } from "../../lib/reads.svelte";
  import { POSTING_API, savePosting, type Posting } from "./posting";

  let { close }: { close: () => void } = $props();
  const p = $derived(read<Posting>(POSTING_API, 0).data || null);
  const ticked = $derived(new Set((p?.sites || []).filter((s) => s.ticked).map((s) => s.id)));
  function toggle(btn: HTMLElement, id: string, name: string): void {
    const next = new Set(ticked);
    const on = !next.has(id);
    if (on) next.add(id);
    else next.delete(id);
    savePosting(btn, { sites: [...next] }, on ? `${name} added: Write a post writes for it.` : `${name} removed.`);
  }
</script>

<DialogFrame title="Add a site" okText="" cancelText="Close" {close} ok={() => {}}>
  {#if p}
    <ul class="plain" id="add-site-list">
      {#each p.sites as s (s.id)}
        <li data-site={s.id}><b>{s.name}</b>{" "}<span class="muted small">{s.ways.includes("open") ? `opens ${s.name} with the draft ready` : ""}{s.can_direct ? ", or Kranto posts it after your yes" : ""}</span>{" "}
          <button type="button" class="btn sm" data-act="site-toggle" onclick={(e) => toggle(e.currentTarget, s.id, s.name)}>{s.ticked ? "Remove" : "Add"}</button>
          {#if s.ticked}<label class="inline small"><input type="checkbox" data-act="site-disclose" checked={s.disclose} onchange={(e) => savePosting(e.currentTarget, { disclose: { [s.id]: e.currentTarget.checked } })} /> End with “{s.disclosure_words || p.disclosure}”</label>{/if}
        </li>
      {/each}
    </ul>
    <p class="small" id="add-site-gone-h"><b>Not possible today</b></p>
    <ul class="plain" id="add-site-gone">
      {#each p.not_offered as g (g.id)}<li data-site={g.id}><b>{g.name}</b>{" "}<span class="muted small">{g.why}{g.later ? `. ${g.later}.` : ""}</span></li>{/each}
    </ul>
  {:else}
    <p class="muted">Reading the sites…</p>
  {/if}
</DialogFrame>
