<script lang="ts">
  // One setting's field: its label and ?, the input its kind calls for, then
  // "now: …" and "Default: … · from a to b · empty: …" under it. The page keeps what is typed
  // (oninput) and writes it with SaveBar; a field never saves by itself.
  import FLabel from "./FLabel.svelte";

  type Kind = "text" | "number" | "money" | "bool" | "enum" | "list" | "model";
  let { id, label, kind = "text", value, input, hint = null, choices = null, now = null, dflt = null, min = null, max = null, step = null, empty = null, placeholder = null, width = null }: {
    id: string; label: string; kind?: Kind; value: string; input: (text: string) => void; hint?: string | null;
    choices?: [string, string][] | null; now?: string | null; dflt?: string | null; min?: number | null; max?: number | null;
    step?: string | null; empty?: string | null; placeholder?: string | null; width?: string | null;
  } = $props();
  const numeric = $derived(kind === "number" || kind === "money");
  const opts = $derived(kind === "bool" ? [["true", "true"], ["false", "false"]] as [string, string][] : choices);
  const under = $derived([dflt != null ? `Default: ${dflt}` : null, min != null && max != null ? `from ${min} to ${max}` : null, empty ? `empty: ${empty}` : null].filter(Boolean).join(" · "));
</script>

<div class="field sfield">
  <FLabel forId={id} text={label} hint={hint ? { text: hint } : null} />
  <div class="inline">
    {#if opts}
      <select {id} onchange={(e) => input(e.currentTarget.value)}>{#each opts as [v, w] (v)}<option value={v} selected={v === value}>{w}</option>{/each}</select>
    {:else}
      {#if kind === "money"}<span class="muted">$</span>{/if}
      <input {id} type={numeric ? "number" : "text"} {value} min={min ?? (kind === "money" ? 0 : null)} max={max ?? null} step={step ?? (kind === "money" ? "0.01" : null)}
        inputmode={kind === "money" ? "decimal" : kind === "number" ? "numeric" : null} placeholder={placeholder ?? (kind === "money" ? "no cap" : null)} autocomplete="off"
        style={`width:${width || (kind === "list" ? "24em" : "10em")}`} oninput={(e) => input(e.currentTarget.value)} />
    {/if}
    {#if now != null}<span class="muted small">{`now: ${now}`}</span>{/if}
  </div>
  {#if under}<p class="muted small">{under}</p>{/if}
</div>
