<script lang="ts">
  // Settings › Appearance, the pane: light or dark and the theme picker, with nothing selected
  // and on the theme's row; the custom theme's five colours, its preview and its contrast checks,
  // Save waiting until every pair reads. A pick applies at once; nothing is sent anywhere.
  import Detail from "../../ui/Detail.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Pane from "../../ui/Pane.svelte";
  import Mark from "../../shell/Mark.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { app } from "../../lib/shell.svelte";
  import { customNow, customTokens, removeCustom, saveCustom, setTheme, themeNow, type Base } from "../../lib/theme";
  import { groupOf, kindLine, SET_ST } from "../../ui/settings";
  import { BASES, CUSTOM_FIELDS, CUSTOM_SEED, DRAFT } from "./appearance.svelte";
  import LookGrid from "./LookGrid.svelte";
  import LookPreview from "./LookPreview.svelte";

  let { view }: { view: View } = $props();
  const id = $derived(groupOf(view.w));
  const now = $derived.by(() => {
    void view.tick; // a pick redraws
    return { t: themeNow(), saved: customNow(), base: document.documentElement.getAttribute("data-theme") };
  });
  // the five colours being picked, kept until Save
  const c = $derived(DRAFT.c || { ...(now.saved ? now.saved.in : CUSTOM_SEED) });
  const t = $derived(customTokens(c));

  function pickBase(k: string): void {
    setTheme(k as Base);
    app()?.render();
  }
  function save(): void {
    if (!t.ok) return;
    saveCustom(c, t.vars);
    DRAFT.c = null;
    app()?.say("Custom theme saved and in use, in this browser.");
    app()?.render();
  }
  function remove(): void {
    removeCustom();
    DRAFT.c = null;
    app()?.say("Custom theme removed.");
    app()?.render();
  }
</script>

{#snippet box()}<div class="inline" id="appearance"><div class="appearance" role="group" aria-label="Theme">{#each BASES as [k, w] (k)}<button class="btn sm" data-theme-choice={k} aria-pressed={now.t === k ? "true" : "false"} onclick={() => pickBase(k)}>{w}</button>{/each}</div><span class="muted small">Auto follows this device's setting. Kept in this browser only.</span></div>{/snippet}
{#snippet looks(s: { id: string })}
  {#if s.id === "layout"}<p class="small" id="layout-one">One layout: the home and its doors. A file that says Classic opens in it too, and keeps what it says.</p>
  {:else if s.id === "mode"}{@render box()}
  {:else if s.id === "looks"}<LookGrid tick={view.tick} base={now.base} />
  {:else}<p class="small">In this browser's storage, the only things the page ever stores. The ◐ button in the top bar switches light and dark; the palette (⌘K) has every theme.</p>{/if}
{/snippet}

<Detail back={view.back}>
  {#if !id}
    <Pane title="Appearance" sections={[{ id: "mode", w: "Light or dark" }, { id: "looks", w: "Theme" }, { id: "kept", w: "Where it is kept" }]} section={looks}>
      {#snippet kind()}<Glyph name={SET_ST.set[0]} colour={SET_ST.set[1]} word={SET_ST.set[2]} />{kindLine("appearance")}{/snippet}
    </Pane>
  {:else if id === "theme"}
    <Pane title="Theme" sections={[{ id: "mode", w: "Light or dark" }, { id: "looks", w: "Theme" }]} section={looks}>
      {#snippet kind()}<Glyph name={SET_ST.set[0]} colour={SET_ST.set[1]} word={SET_ST.set[2]} />{kindLine("appearance", "theme")}{/snippet}
    </Pane>
  {:else if id === "layout"}
    <Pane title="Layout" lede="The frame around every page: the home and its doors." sections={[{ id: "layout", w: "Layout" }]} section={looks}>
      {#snippet kind()}<Glyph name={SET_ST.set[0]} colour={SET_ST.set[1]} word={SET_ST.set[2]} />{kindLine("appearance", "layout")}{/snippet}
    </Pane>
  {:else if id === "custom"}
    {@const st = now.saved ? SET_ST.set : SET_ST.dflt}
    <Pane title="Custom theme" lede="Five colours of your own: the sidebar, its current row, its text, the accent and the badge. Every pair is checked for contrast before it is saved."
      sections={[{ id: "colours", w: "Colours" }, { id: "checks", w: "Contrast" }, { id: "save", w: "Use it" }]}>
      {#snippet kind()}<Glyph name={st[0]} colour={st[1]} word={st[2]} />{kindLine("appearance", "custom theme")}{/snippet}
      {#snippet section(s)}
        {#if s.id === "colours"}<div class="cust">{#each CUSTOM_FIELDS as [k, w] (k)}<label><input type="color" value={c[k]} data-custom={k} oninput={(e) => (DRAFT.c = { ...c, [k]: e.currentTarget.value })} /><span>{w}</span></label>{/each}</div><div class="cust-pv"><LookPreview id="custom" base={now.base} vars={t.vars} /></div>
        {:else if s.id === "checks"}<ul class="ctx">{#each t.checks as [w, r, n] (w)}<li>{#if r >= n}<Mark name="check" colour="green" word={w} />{:else}<Mark name="x" colour="red" word={w} />{/if}<span class="n">{`${r.toFixed(2)}:1, needs ${n}:1`}</span></li>{/each}</ul><p class="small muted mt-s">{!t.ok ? "Save waits until every pair reads: change the colours marked ✕." : t.moved.length ? `The accent is drawn ${t.moved.join(" and ")}, so links read.` : ""}</p>
        {:else}<div class="inline"><button class="btn primary" id="save-custom" type="button" disabled={!t.ok} onclick={save}>Save and use</button>{#if now.saved}<button class="btn" type="button" onclick={remove}>Remove</button>{/if}</div>{/if}
      {/snippet}
    </Pane>
  {:else}
    <div class="pane-empty"><p class="empty">Nothing to show here.</p></div>
  {/if}
</Detail>
