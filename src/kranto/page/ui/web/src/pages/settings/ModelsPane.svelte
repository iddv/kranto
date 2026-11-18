<script lang="ts">
  // Settings › Watching › Models, the pane: the endpoint and the models offered with nothing
  // selected; a role's model (the choice, the judge's gate, Save: nothing is written until Save),
  // the models offered.
  import Detail from "../../ui/Detail.svelte";
  import ModelCatalog from "./ModelCatalog.svelte";
  import FLabel from "../../ui/FLabel.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Kv from "../../ui/Kv.svelte";
  import Pane from "../../ui/Pane.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { app, ui } from "../../lib/shell.svelte";
  import { groupOf, kindLine, SET_ST } from "../../ui/settings";
  import { saveUndo } from "../../ui/save";
  import { AFK_MODELS, CATALOG, changed, lastCall, modelEntry, modelName, PICK, pickOf, roleSpecs, type AfkModels, type Spec, watchingVia } from "./models.svelte";

  let { view }: { view: View } = $props();
  const id = $derived(groupOf(view.w));
  const host = $derived(!!ui.facts?.header.host);
  const a = $derived.by(() => {
    void view.tick;
    return host ? read<AfkModels>(AFK_MODELS, 30000) : null;
  });
  const xs = $derived(a?.data ? roleSpecs(a.data) : null);
  const x = $derived(xs && id ? xs.find((y) => "role:" + y.key === id) || null : null);

  /** one role's model (and the judge's gate) written; what was saved, in words */
  async function saveRole(r: Spec, pick: string, gate: number | undefined): Promise<string> {
    const L = app()!;
    if (gate !== undefined && !(gate > 0 && gate <= 1)) throw new Error("The gate is a signal above 0 and at most 1.");
    await L.api(AFK_MODELS, { role: r.role.role, model: pick, ...(gate !== undefined ? { gate } : {}) });
    L.afkDrop();
    return `${r.role.name} uses ${modelName(r.cat, pick)}` + (gate !== undefined ? ` and keeps items at signal ${gate} or above` : "");
  }
  function save(btn: HTMLElement, r: Spec): void {
    const pick = pickOf(r), gk = r.key + ":gate", hasGate = r.role.gate != null;
    const gate = hasGate ? Number(gk in PICK ? PICK[gk] : String(r.role.gate)) : undefined;
    // Undo writes the role's model (and gate) as they were before this Save
    const was = r.current || r.role.default || "";
    const wasGate = hasGate ? r.role.gate ?? undefined : undefined;
    void saveUndo(btn, {
      write: () => saveRole(r, pick, gate),
      undo: () => saveRole(r, was, wasGate),
      what: (said) => said as string,
      effect: "now",
      after: () => {
        delete PICK[r.key];
        delete PICK[gk];
      },
    });
  }
</script>


<Detail back={view.back}>
  {#if !host}
    <div class="pane-empty"><p class="empty">Watching's models are the server's, which is not answering.</p></div>
  {:else if !xs}
    <div class="pane-in"><p class="empty">Loading…</p></div>
  {:else if !id}
    <Pane title="Which model each part calls" lede="Watching runs through the provider chosen under Settings › Watching. Select a role to change it."
      sections={[{ id: "endpoint", w: "Endpoint" }, { id: "offered", w: "Models offered", n: CATALOG.length }]}>
      {#snippet kind()}<Glyph name="dot" colour="blue" word="Models" />{kindLine("watching", "models")}{/snippet}
      {#snippet section(s)}{#if s.id === "endpoint"}<Kv rows={[["Watching", a?.data ? watchingVia(a.data) : "the server's endpoint", "mono"], ...(a?.data?.last_call ? [["Last call", lastCall(a.data.last_call)] as [string, string]] : [])]} />{:else}<ModelCatalog cat={CATALOG} />{/if}{/snippet}
    </Pane>
  {:else if !x}
    <div class="pane-empty"><p class="empty">No such role.</p></div>
  {:else}
    {@const r = x}
    {@const st = changed(r) ? SET_ST.changed : SET_ST.set}
    {@const pick = pickOf(r)}
    {@const shown = modelEntry(r.cat, pick)}
    {@const gk = r.key + ":gate"}
    {@const isChanged = changed(r)}
    <Pane title={r.role.name} lede={r.role.does || null} right={r.role.setting || null}
      sections={[{ id: "model", w: "Model" }, { id: "offered", w: "Models offered", n: r.cat.length }]}>
      {#snippet kind()}<Glyph name={st[0]} colour={st[1]} word={st[2]} />{kindLine("watching", "models")}{/snippet}
      {#snippet section(s)}
        {#if s.id === "model"}<div class="field"><label for={"model-" + r.key}>Calls</label><div class="inline"><select id={"model-" + r.key} aria-label={r.role.name + " model"} onchange={(e) => (PICK[r.key] = e.currentTarget.value)}>{#each r.opts as [v, t] (v)}<option value={v} selected={v === pick}>{t}</option>{/each}</select>{#if isChanged}<span class="pill c-amber">changed: from the next call</span>{/if}</div></div>{#if r.role.gate != null}<div class="field"><FLabel forId={"gate-" + r.key} text="Gate (keep at signal ≥)" hint={r.role.gate_note ? { text: r.role.gate_note, docs: "models.gate" } : null} tipId={r.role.gate_note ? null : "models.gate"} /><input id={"gate-" + r.key} type="number" min="0.001" max="1" step="0.01" value={gk in PICK ? PICK[gk] : String(r.role.gate)} style="width:7em" oninput={(e) => (PICK[gk] = e.currentTarget.value)} /></div>{/if}<div class="inline"><button class="btn primary" id={"save-" + r.key} disabled={!isChanged} onclick={(e) => save(e.currentTarget, r)}>Save</button><span class="muted small">{isChanged ? "Nothing is written until you click Save." : "Choose a model; Save writes it."}</span></div><Kv rows={[["Good for", shown ? shown.note : "not in the list"], ["Endpoint", r.endpoint, "mono"], ["Written to", r.file, "mono"]]} />
        {:else}<ModelCatalog cat={r.cat} />{/if}
      {/snippet}
    </Pane>
  {/if}
</Detail>
