<script lang="ts">
  // Settings › Accounts › Newsletter, the sheet (MAIL): the platform a newsletter cub's issues go out
  // through. The cub never names one; the server's /api/newsletter says which is in use (none until
  // one is connected), whether an issue can go out and what is missing. Connect a provider offers
  // every platform the server lists, each to its own connection page (the key, Save and test); Check
  // again only reads at the platform; Create the audience is the owner's press (a confirm).
  import Detail from "../../ui/Detail.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Kv from "../../ui/Kv.svelte";
  import Loading from "../../ui/Loading.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import Pane from "../../ui/Pane.svelte";
  import Mark from "../../shell/Mark.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { app, ui } from "../../lib/shell.svelte";
  import { NEWSLETTER_API, nlSt, type Newsletter } from "./newsletter";

  let { view }: { view: View } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const r = $derived.by(() => {
    void view.tick;
    return host ? read<Newsletter>(NEWSLETTER_API, 15000) : null;
  });
  const d = $derived(r?.data || null);
  let audience = $state("");

  /** a write to the server, its reads read again after it, its message said */
  function act(btn: HTMLElement, path: string, body: Record<string, unknown>, done?: () => void): void {
    const L = app();
    if (L) void L.act(btn, async () => {
      const x = await L.api(path, body);
      L.afkDrop();
      return x;
    }, (x) => {
      const m = x as { message?: string; ok?: boolean };
      done?.();
      app()?.say(m.message || "Done.", m.ok === false ? "amber" : "blue");
    });
  }
  /** Create the audience: the owner's press, after a confirm that says what it does */
  function create(n: Newsletter): void {
    const L = app();
    const name = audience.trim();
    if (!L || !name) return;
    const body = document.createElement("p");
    body.textContent = `Kranto asks ${n.name} to make an audience named “${name}”, with no subscribers in it yet. Nothing is sent. Import your subscribers into it at ${n.name}.`;
    L.dialog("Create the audience?", [body], "Create", (b, close) => act(b, NEWSLETTER_API + "/audience", { confirm: true, name }, close), "");
  }
</script>

<Detail back={view.back}>
  {#if !host}
    <NeedHost what="The newsletter" />
  {:else if !d}
    <div class="pane-in"><Loading error={r?.error} /></div>
  {:else}
    {@const st = nlSt(d)}
    <Pane title="Newsletter" lede="The platform a newsletter cub's issues go out through. A cub never names one and never sees its key: you choose it here, and every send is still your approval (Send now, in the issue's dialog)."
      sections={[{ id: "use", w: "In use" }, { id: "connect", w: "Connect a provider" }]}>
      {#snippet kind()}<Glyph name={st[0]} colour={st[1]} word={st[2]} />{" newsletter · " + (d.name || d.unnamed)}{/snippet}
      {#snippet acts()}{#if d.connection}<button class="btn sm" id="nl-check" onclick={(e) => act(e.currentTarget, NEWSLETTER_API + "/check", {})}>Check again</button>{/if}{/snippet}
      {#snippet section(s)}
        {#if s.id === "use"}
          {#if !d.platform}
            <p>No newsletter platform is connected. A newsletter cub's drafts wait in Kranto until you connect one below.</p>
          {:else}
            <Kv rows={[["Platform", d.name || ""], ["Connection", d.connection ? `${d.connection.account} (${d.connection.state === "connected" ? "connected" : "needs you"})` : "not connected"],
              ...(d.from_address ? [["From", d.from_address] as [string, string]] : []), ["To", d.audience || "–"], ["Ready", d.ready ? "yes: an issue goes out when you click Send now on it" : "not yet"]]} />
          {/if}
          {#if d.missing.length}<ul class="ctx mt" id="nl-missing">{#each d.missing as m, i (i)}<li><Mark name="warn" colour="amber" word="Missing" /> {m}</li>{/each}</ul>{/if}
          {#if d.platform && d.audiences && d.connection && !d.ready}
            <div class="field mt"><label for="nl-audience">Create the audience at {d.name}</label><div class="inline"><input id="nl-audience" style="width:min(100%,280px)" placeholder="Newsletter" bind:value={audience} /><button class="btn" id="nl-create" disabled={!audience.trim()} onclick={() => create(d)}>Create the audience</button></div></div>
          {/if}
        {:else}
          <p class="muted small">Each opens its own page: the steps, the key to paste, and Save and test, which only reads and says what is missing. Kranto's newsletter guide (docs/newsletter.md) has every step.</p>
          <ul class="ctx">{#each d.platforms as p, i (p.id)}<li><a class={"btn sm" + (i === 0 && !d.platform ? " primary" : "")} id={"nl-connect-" + p.id} href={"#/settings/connections/" + p.id}>{d.platform?.id === p.id ? "Connect " + p.name + " again" : "Connect " + p.name}</a> <span class="muted small">{p.about}{i === 0 ? " The default." : ""}{p.can_schedule ? "" : " Sends now only."}</span></li>{/each}</ul>
        {/if}
      {/snippet}
    </Pane>
  {/if}
</Detail>
