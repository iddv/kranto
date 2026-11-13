<script lang="ts">
  // Settings › Privacy & access, the pane: what the page is about with nothing selected; a token's file,
  // what it may run and when it was last used, with Rotate (and Revoke for an agent); an
  // agent's own list of actions, ticked from kranto mcp's; and Add an agent.
  import Detail from "../../ui/Detail.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Pane from "../../ui/Pane.svelte";
  import Tip from "../../ui/Tip.svelte";
  import { plural } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { put, read } from "../../lib/reads.svelte";
  import { go } from "../../lib/router";
  import { app } from "../../lib/shell.svelte";
  import { groupOf, kindLine, SET_ST } from "../../ui/settings";
  import { ACCESS_API, AGENT_NAME, DOOR_MAY, isAgent, tokWord, type Token, type Tokens } from "./access";
  import { confirmThen } from "../../ui/dialog.svelte";

  let { view }: { view: View } = $props();
  const id = $derived(groupOf(view.w));
  const c = $derived.by(() => {
    void view.tick;
    return id ? read<Tokens>(ACCESS_API, 15000) : null;
  });
  const d = $derived(c?.data || null);
  const t = $derived(id?.startsWith("tok:") && d ? d.tokens.find((x) => x.name === id.slice(4)) || null : null);
  // an agent's own list, ticked here; Save this list sends it
  let ticked = $state<string[]>([]);
  $effect(() => {
    if (t) ticked = t.actions ? [...t.actions] : [...(d?.default_actions || [])];
  });
  let name = $state("");
  let note = $state("");
  let nameIn = $state<HTMLInputElement>();

  /** a press on a token: its new list of tokens is what the page shows */
  function tokAct(btn: HTMLElement, tk: Token, what: string, said: string, gone = false, body: object = {}): void {
    app()?.act(btn, async () => {
      const r = (await app()!.api(`${ACCESS_API}/${encodeURIComponent(tk.name)}/${what}`, body)) as { tokens: Token[] };
      put<Tokens>(ACCESS_API, { ...(d as Tokens), tokens: r.tokens });
      return r;
    }, () => {
      if (gone) go("settings/access");
      app()?.say(said);
    });
  }
  function rotate(btn: HTMLElement, tk: Token): void {
    confirmThen(tk.name === "ui" ? "Rotate this page's token?" : `Rotate ${tk.name}'s token?`,
      tk.name === "ui" ? "Every other browser signs in again with kranto open; this one stays signed in." : "The old one stops working at once; the new one is in the same file.",
      "Rotate", () => tokAct(btn, tk, "rotate", `${tokWord(tk)} has a new token in ${tk.file}; the old one no longer works.`));
  }
  function revoke(btn: HTMLElement, tk: Token): void {
    confirmThen(`Revoke ${tk.name}?`, "It stops working at once and its file is removed.", "Revoke",
      () => tokAct(btn, tk, "revoke", `${tokWord(tk)} is revoked: its token no longer works.`, true), "danger");
  }
  function saveList(btn: HTMLElement, tk: Token, actions: string[] | null): void {
    tokAct(btn, tk, "actions", `${tokWord(tk)} may now run ${actions ? plural(actions.length, "action") : "what kranto mcp may"}.`, false, { actions });
  }
  function add(btn: HTMLElement): void {
    if (!AGENT_NAME.test(name.trim())) {
      nameIn?.focus();
      return;
    }
    app()?.act(btn, async () => {
      const r = (await app()!.api(ACCESS_API, { name: "agent:" + name.trim(), note: note.trim() })) as { tokens: Token[]; name: string; file: string };
      put<Tokens>(ACCESS_API, { ...(d as Tokens), tokens: r.tokens });
      return r;
    }, (r) => {
      const x = r as { name: string; file: string };
      go("settings/access", { sel: "etok:" + x.name });
      app()?.say(`Added ${x.name}. Its token is in ${x.file}; the agent sends it as Authorization: Bearer $(cat ${x.file}).`);
    });
  }
</script>

<Detail back={view.back}>
  {#if !id}
    <Pane title="Access" sections={[]}>
      {#snippet kind()}<Glyph name={SET_ST.ok[0]} colour={SET_ST.ok[1]} word={SET_ST.ok[2]} />{kindLine("privacy & access", "who may act")}{/snippet}
      {#snippet lede()}Who may act on Kranto.<Tip id="access" about="access" />{/snippet}
    </Pane>
  {:else if id === "new-agent"}
    <Pane title="Add an agent" lede="An agent that drives Kranto (a fleet track, your own coding agent) gets a token of its own, so what it does says its name and stays within what it may run."
      sections={[{ id: "form", w: "The agent" }, { id: "cli", w: "From the command line" }]}>
      {#snippet kind()}<Glyph name={SET_ST.set[0]} colour={SET_ST.set[1]} word={SET_ST.set[2]} />{" token · new agent"}{/snippet}
      {#snippet section(s)}
        {#if s.id === "form"}<div class="field"><label for="agent-name">Name (letters, digits, _ . -)</label><input id="agent-name" type="text" autocomplete="off" placeholder="RC" aria-label="The agent's name" bind:value={name} bind:this={nameIn} /></div><div class="field mt"><label for="agent-note">What it is for</label><input id="agent-note" type="text" autocomplete="off" placeholder="what it is for (optional)" aria-label="What it is for" bind:value={note} /></div><div class="inline mt"><button class="btn sm primary" id="add-agent-go" onclick={(e) => add(e.currentTarget)}>Add</button></div>
        {:else}<p class="small"><code>kranto token add agent:&lt;name&gt;</code> does the same; <code>kranto token list</code> lists them.</p>{/if}
      {/snippet}
    </Pane>
  {:else if !t}
    <div class="pane-empty"><p class="empty">{c && !d ? (c.error ? `Could not read the server: ${c.error}` : "Loading…") : "No such token."}</p></div>
  {:else}
    {@const agent = isAgent(t)}
    {@const tk = t}
    <Pane title={tokWord(t)} lede={t.note || (agent ? "A named agent's token: its actions say agent " + t.name.slice(6) + " in every record." : null)}
      sections={[{ id: "file", w: "Where it is" }, { id: "may", w: "What it may run" }, { id: "used", w: "Last used" }]}>
      {#snippet kind()}<Glyph name={SET_ST.ok[0]} colour={SET_ST.ok[1]} word={SET_ST.ok[2]} />{agent ? " token · agent" : " token · door"}{/snippet}
      {#snippet acts()}<button class="btn sm" id="rotate-token" onclick={(e) => rotate(e.currentTarget, tk)}>Rotate</button>{#if agent}<button class="btn sm quiet" id="revoke-token" onclick={(e) => revoke(e.currentTarget, tk)}>Revoke</button>{/if}{/snippet}
      {#snippet section(s)}
        {#if s.id === "file"}<p class="small">Its value is in <code>{tk.file}</code> (mode 600). It is never shown here.</p>{#if agent}<p class="small">The agent sends it on each request as <code>{`Authorization: Bearer $(cat ${tk.file})`}</code>, never this page's cookie.</p>{/if}
        {:else if s.id === "may"}
          {#if agent}
            {@const all = d?.default_actions || []}
            <p class="small">{tk.actions ? `Its own list: ${tk.actions.length} of ${all.length}.` : "The default: everything kranto mcp may run; the confirm class only with confirm: true."}</p><div class="chips" id="agent-actions">{#each all as k (k)}<label class="chk"><input type="checkbox" value={k} bind:group={ticked} />{" " + k}</label>{/each}</div><div class="inline mt"><button class="btn sm primary" id="save-actions" onclick={(e) => saveList(e.currentTarget, tk, [...ticked])}>Save this list</button>{#if tk.actions}<button class="btn sm" onclick={(e) => saveList(e.currentTarget, tk, null)}>Back to the default</button>{/if}</div>
          {:else}<p class="small">{DOOR_MAY[tk.name] || ""}</p>{/if}
        {:else}<p class="small">{tk.last_used ? new Date(tk.last_used * 1000).toLocaleString("en-GB") : "Not since Kranto started."}</p>{/if}
      {/snippet}
    </Pane>
  {/if}
</Detail>
