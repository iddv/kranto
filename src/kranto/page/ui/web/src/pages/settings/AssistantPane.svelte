<script lang="ts">
  // Settings › Assistant, the pane: one console setting's form (it saves into loop.yaml's ask:),
  // one ladder kind's three choices (the locks say why they cannot change), or the install lines
  // for your own client. The page says plainly that the ladder governs Kranto's own tools only.
  import Detail from "../../ui/Detail.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Pane from "../../ui/Pane.svelte";
  import PageAbout from "./PageAbout.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { drop, read } from "../../lib/reads.svelte";
  import { api } from "../../lib/app/data";
  import { app, ui } from "../../lib/shell.svelte";
  import { groupOf, kindLine, SET_ST } from "../../ui/settings";
  import * as C from "../../term/console.svelte";
  import { confirmThen } from "../../ui/dialog.svelte";
  import { CHOICE_WORDS, CONFIG_WORDS, CONSOLE_API, GLOBAL_API, globalLines, HARNESS_NAME, LADDER_API, OUTSIDE_LINES, PERMISSION_WORDS, withKind, type GlobalPlan, type Ladder } from "./assistant";

  let { view }: { view: View } = $props();
  const id = $derived(groupOf(view.w) || "");
  const c = $derived.by(() => {
    void view.tick;
    return read<C.ConsoleState>(CONSOLE_API, 30000);
  });
  // the ladder is the server's: read where Kranto hosts the page (brb alone has none)
  const host = $derived(!!ui.facts?.header.host);
  const l = $derived.by(() => {
    void view.tick;
    return host ? read<Ladder>(LADDER_API, 30000) : { data: null, error: null, at: 0, loading: false };
  });
  let said = $state("");
  let busy = $state(false);
  // a change the running console takes only at its start offers the restart
  let offer = $state<{ harness: string | null; word: string } | null>(null);

  async function saveConsole(body: Partial<C.ConsoleSettings>): Promise<void> {
    busy = true;
    said = "";
    try {
      const st = await C.save(body);
      const other = body.harness && body.harness !== C.consoleUi.harness && C.consoleUi.harness ? body.harness : null;
      offer = st.restart ? { harness: null, word: "Restart the console now" }
        : other ? { harness: other, word: `Switch the console to ${HARNESS_NAME[other] || other} now` } : null;
      said = offer ? "Saved. The console takes it when it starts again; your conversation is resumed." : "Saved.";
    } catch (e) {
      said = (e as Error).message;
    }
    busy = false;
    drop(CONSOLE_API, true);
    app()?.render();
  }

  async function saveKind(kind: string, choice: string): Promise<void> {
    if (!l.data) return;
    busy = true;
    said = "";
    try {
      await api(LADDER_API, withKind(l.data, kind, choice));
      said = `Saved: ${CHOICE_WORDS[choice]}. It applies to the console and to your own Claude Code or Codex from the next action.`;
    } catch (e) {
      said = (e as Error).message;
    }
    busy = false;
    drop(LADDER_API, true);
    app()?.render();
  }

  function restartNow(): void {
    if (!offer) return;
    C.restartConsole(offer.harness);
    said = "Restarting the console: the same conversation, with what you saved.";
    offer = null;
  }

  // Q6: add Kranto to your own Claude Code or Codex, the change shown before anything is written
  async function addGlobal(harness: string): Promise<void> {
    said = "";
    let p: GlobalPlan;
    try {
      p = (await api(`${GLOBAL_API}?harness=${harness}`)) as GlobalPlan;
    } catch (e) {
      said = (e as Error).message;
      return;
    }
    if (p.missing.length) {
      said = `${p.missing.join(", ")} is not installed on this computer.`;
      return;
    }
    confirmThen(`Add Kranto to your own ${HARNESS_NAME[harness]}?`, globalLines(p), "Add", async () => {
      busy = true;
      try {
        const done = (await api(GLOBAL_API, { harness })) as GlobalPlan;
        said = done.says;
      } catch (e) {
        said = (e as Error).message;
      }
      busy = false;
    });
  }

  const lad = $derived(id.startsWith("lad-") && l.data ? l.data.kinds.find((k) => k.kind === id.slice(4)) || null : null);
  const st = $derived(c.data?.settings || null);
  const harness = $derived(c.data?.harnesses.find((h) => h.id === c.data?.harness) || null);
  const cs = $derived(c.data);
  const tone = SET_ST.dflt;
</script>

<Detail back={view.back}>
  {#if !id}
    <PageAbout {view} />
  {:else if lad}
    <Pane title={lad.words} lede={lad.locked ? `Locked: ${lad.why}. No setting changes it.` : "What an assistant does with this kind of action: the console in Kranto and your own Claude Code or Codex alike. What you do yourself on the page is never asked."} sections={[{ id: "form", w: "Choose" }]}>
      {#snippet kind()}<Glyph name={tone[0]} colour={tone[1]} word={tone[2]} />{kindLine("assistant", "what it does by itself")}{/snippet}
      {#snippet section()}
        <fieldset class="choices" disabled={lad.locked || busy}>
          {#each ["do", "ask", "never"] as ch (ch)}
            <label><input type="radio" name={"lad-" + lad.kind} checked={lad.choice === ch} onchange={() => saveKind(lad.kind, ch)} /> {CHOICE_WORDS[ch]}{ch === lad.default ? " (Kranto's default)" : ""}</label>
          {/each}
        </fieldset>
        <p class="muted small">Ask me in the UI: the assistant prepares it and nothing happens until you approve it on its page or in Needs you. Kranto's ladder governs Kranto's own tools only; your assistant's own permission mode governs its edits and commands.</p>
        {#if said}<p class="small" role="status">{said}</p>{/if}
      {/snippet}
    </Pane>
  {:else if id === "outside"}
    <Pane title="Use Kranto from your own client" lede="The same tools and the same ladder as the console, from your own Claude Code or Codex. Kranto writes nothing outside its folder unless you ask: kranto assistant global claude|codex shows the change first." sections={[{ id: "lines", w: "One line each" }]}>
      {#snippet kind()}<Glyph name={tone[0]} colour={tone[1]} word={tone[2]} />{kindLine("assistant", "your own client")}{/snippet}
      {#snippet section()}
        {#if host}<p class="acts">{#each ["claude", "codex"] as h (h)}<button type="button" class="btn sm" id={"add-global-" + h} disabled={busy} onclick={() => void addGlobal(h)}>{`Add Kranto to my own ${HARNESS_NAME[h]}…`}</button>{/each}</p>
          <p class="muted small">Each shows the exact change first; nothing outside Kranto's folder is written until you click Add. Or ask the console: it prepares the same change for you here.</p>{/if}
        {#if said}<p class="small" role="status">{said}</p>{/if}
        <p class="muted small">Or one line in your terminal:</p>
        {#each OUTSIDE_LINES as x (x)}<pre class="file">{x}</pre>{/each}{/snippet}
    </Pane>
  {:else if st && cs}
    <Pane title="The console" lede="Your own Claude Code (or Codex) as it runs in a terminal, in Kranto's folder, with Kranto's tools; its own permission prompts. Kranto adds its plugin (a skill, its tools, hooks) and nothing else." sections={[{ id: "form", w: "Set" }]}>
      {#snippet kind()}<Glyph name={tone[0]} colour={tone[1]} word={tone[2]} />{kindLine("assistant", "the console")}{/snippet}
      {#snippet section()}
        <div class="form" aria-busy={busy}>
          {#if id === "con-open"}
            <label><input type="checkbox" checked={st.open} onchange={(e) => saveConsole({ open: e.currentTarget.checked })} /> Open the console when Kranto opens</label>
            <p class="muted small">Each browser remembers if you fold it to the rail or the top bar.</p>
          {:else if id === "con-harness"}
            {#each cs.harnesses as h (h.id)}
              <label><input type="radio" name="harness" checked={cs.harness === h.id} disabled={!h.installed} onchange={() => saveConsole({ harness: h.id })} /> {h.name}{h.installed ? "" : " (not installed)"}{h.extras ? "" : " · fewer extras: no status line, its spend is not reported"}</label>
            {/each}
          {:else if id === "con-model" && harness}
            <select aria-label="Model" value={st.model[harness.id] || ""} onchange={(e) => saveConsole({ model: { [harness.id]: e.currentTarget.value || null } as unknown as Record<string, string> })}>
              <option value="">{harness.name}'s own default</option>
              {#each harness.models as m (m.id)}<option value={m.id}>{m.name}</option>{/each}
            </select>
          {:else if id === "con-permission"}
            {#each Object.entries(PERMISSION_WORDS) as [k, w] (k)}
              <label><input type="radio" name="perm" checked={st.permission === k} onchange={() => saveConsole({ permission: k as C.ConsoleSettings["permission"] })} /> {w}</label>
            {/each}
            <p class="muted small">shift+tab in the console changes it for the conversation. Bypassing permissions is refused.</p>
          {:else if id === "con-config"}
            {#each Object.entries(CONFIG_WORDS) as [k, w] (k)}
              <label><input type="radio" name="cfg" checked={st.config === k} onchange={() => saveConsole({ config: k as C.ConsoleSettings["config"] })} /> {w}</label>
            {/each}
            <p class="muted small">With your own, the MCP servers you added load too{cs.outside?.length ? ` (now: ${cs.outside.join(", ")})` : ""}; Kranto's ladder and locks govern Kranto's tools only.</p>
          {:else if id === "con-cap"}
            <label>Dollars a day (empty: no cap) <input type="number" min="0" step="0.5" value={st.daily_usd ?? ""} onchange={(e) => saveConsole({ daily_usd: e.currentTarget.value ? Number(e.currentTarget.value) : null })} /></label>
          {/if}
          {#if said}<p class="small" role="status">{said}</p>{/if}
          {#if offer}<button type="button" class="btn sm primary" id="console-restart" onclick={restartNow}>{offer.word}</button>{/if}
        </div>
      {/snippet}
    </Pane>
  {:else}
    <div class="pane-empty"><p class="empty">{c.error || l.error || "Loading…"}</p></div>
  {/if}
</Detail>

<style>
  .choices { border: 0; padding: 0; margin: 0 0 8px; display: grid; gap: 6px; }
  .form { display: grid; gap: 8px; }
  label { display: block; }
</style>
