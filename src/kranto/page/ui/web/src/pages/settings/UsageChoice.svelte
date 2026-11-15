<script lang="ts">
  // The usage-reports question (the owner's D1: asked once, nothing sent until
  // answered): the two sentences, three choices with none chosen for the person, and where to
  // read every field. Welcome's first step and Settings › Privacy & access draw it; a choice is saved at
  // once through the one setter (POST /api/settings/telemetry).
  import type { Privacy } from "./privacy";
  import { CHOICES, DOCS, PRIVACY_API, type Mode } from "./privacy";
  import { href } from "../../lib/router";
  import { put } from "../../lib/reads.svelte";
  import { app } from "../../lib/shell.svelte";

  let { p, local = false }: { p: Privacy; local?: boolean } = $props();
  const choices = $derived(local ? [...CHOICES, ["local", "Local only: count here, send nothing"] as [Mode, string]] : CHOICES);
  const fixed = $derived(p.why === "DO_NOT_TRACK" || p.why === "KRANTO_TELEMETRY");

  function choose(mode: Mode, el: HTMLElement): void {
    const L = app();
    if (!L) return;
    void L.act(el, async () => {
      const r = (await L.api(PRIVACY_API, { mode })) as Privacy;
      put(PRIVACY_API, r);
      return r;
    }, (x) => {
      const r = x as Privacy;
      L.say(`Usage reports: ${r.meaning}.` + (r.why_not && r.mode !== "off" && r.mode !== "local" ? ` ${r.why_not}.` : ""));
    });
  }
</script>

<p class="small">{p.summary}</p>
<div class="field" role="radiogroup" aria-label="Usage reports">
  {#each choices as [m, w] (m)}<label class="radio"><input type="radio" name="usage-mode" id={"usage-" + m} value={m} disabled={fixed} checked={p.answered && p.mode === m} onchange={(e) => choose(m, e.currentTarget)} />{" " + w}</label>{/each}
</div>
<p class="muted small" id="usage-errors">Errors are included: with Basic or Detailed, when something fails an error report goes within minutes (the error's type, where in Kranto's code it happened, and its message with every word that could be yours removed), as well as one report a day, to a relay the maintainer runs on AWS in the EU. With Nothing, or until you choose, nothing leaves this machine. You can change this in Settings › Privacy & access at any time. Every field: <a href={href("settings/privacy", { sel: "enotice" })}>What Kranto sends</a> (also <a href={p.docs || DOCS} target="_blank" rel="noopener noreferrer">on GitHub</a> and <code>kranto telemetry docs</code>).</p>
