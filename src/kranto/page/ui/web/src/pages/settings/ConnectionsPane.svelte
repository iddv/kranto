<script lang="ts">
  // Settings › Sources › Accounts, the pane. With nothing selected, how tokens are kept. An account
  // (sel=eacct:<id>): Test (or Reconnect), Disconnect (a confirm; the old module's dialog), the
  // provider's page, its facts and the sources that read with it. A provider
  // (#/settings/connections/<key>): its steps, the sign-in (from a loopback address only: the site
  // sends the browser back there; Bluesky's from 127.0.0.1), the paste form, GitHub's device box,
  // the accounts connected with it and what it reads. A pasted secret is in a password field,
  // read once when it is sent and cleared then; it is never kept.
  import Detail from "../../ui/Detail.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Kv from "../../ui/Kv.svelte";
  import Loading from "../../ui/Loading.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import Pane, { type Sec } from "../../ui/Pane.svelte";
  import Tip from "../../ui/Tip.svelte";
  import Icon from "../../shell/Icon.svelte";
  import Mark from "../../shell/Mark.svelte";
  import { dt, rel } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { app, ui } from "../../lib/shell.svelte";
  import { groupOf, kindLine, SET_ST } from "../../ui/settings";
  import { ASKS, clientWords, CONNECTIONS_API, DEVICE, devicePoll, howWord, INSTANCE, LOOPBACK, SIGNIN, type Account, type Connections, type Field, type Provider } from "./connections";
  import { safeHref } from "./sources.svelte";
  // a step names Kranto's default port; this Kranto may run on another (17, Codex 15: Bluesky's
  // first step said 8765 on a home at 9960)
  const herePort = (s: string): string => s.replaceAll("127.0.0.1:8765", "127.0.0.1:" + (location.port || "80"));

  let { view }: { view: View } = $props();
  const id = $derived(groupOf(view.w));
  const key = $derived(view.w.object === "connection" && view.w.obj ? String(view.w.obj[2]) : null);
  const host = $derived(!!ui.facts?.header.host);
  const c = $derived.by(() => {
    void view.tick; // each draw may find the reads stale
    return host ? read<Connections>(CONNECTIONS_API, 15000) : null;
  });
  const d = $derived(c?.data || null);
  const a = $derived(d && id ? d.accounts.find((x) => "acct:" + x.id === id) || null : null);
  const p = $derived(d && key ? d.providers.find((x) => x.key === key) || null : null);
  // the device box's state, as the last draw found it
  const dev = $derived.by(() => {
    void view.tick;
    return DEVICE.d && DEVICE.d.key === key ? { ...DEVICE.d } : null;
  });

  // where this page is open: a browser sign-in comes back to a loopback address only
  const port = location.port || (location.protocol === "https:" ? "443" : "80");
  const need = $derived(p ? p.redirect_host || null : null); // Bluesky: 127.0.0.1 only
  const loop = $derived(need ? location.hostname === need : LOOPBACK.includes(location.hostname));
  const callback = $derived(`http://${loop ? location.hostname : need || "localhost"}:${port}/connections/${key}/callback`);
  const here = $derived(`http://${need || "localhost"}:${port}${location.pathname}${location.hash}`);
  const ask = $derived(key ? ASKS[key] || null : null);
  let inst = $state("");
  $effect.pre(() => {
    inst = key ? INSTANCE[key] || "" : "";
  });
  let instEl = $state<HTMLInputElement>();

  /** a write to the server: its cached reads are read again after it */
  function afkAct(btn: HTMLElement | null, f: (L: NonNullable<ReturnType<typeof app>>) => Promise<unknown>, done: (x: { message: string; ok?: boolean }) => void): void {
    const L = app();
    if (L) void L.act(btn, async () => {
      const r = await f(L);
      L.afkDrop();
      return r;
    }, (r) => done(r as { message: string; ok?: boolean }));
  }
  function test(btn: HTMLElement, x: Account): void {
    afkAct(btn, (L) => L.api(`/api/connections/${x.id}/test`, {}), (r) => app()?.say(r.message, r.ok ? "blue" : "red"));
  }
  function disconnect(x: Account): void {
    const L = app();
    if (!L) return;
    const body = document.createElement("p");
    body.textContent = `the server revokes the token at ${x.provider_name} where the site allows it, and deletes it here. The ${x.sources.length} source${x.sources.length === 1 ? "" : "s"} that use it report Needs login until you connect again.`;
    L.dialog(`Disconnect ${x.provider_name}?`, [body], "Disconnect", (btn, close) => afkAct(btn, (M) => M.api(`/api/connections/${x.id}/disconnect`, {}), (r) => {
      close();
      app()?.say(r.message);
    }), "");
  }
  /** Connect: the provider's sign-in, left for by navigation (never a form post) */
  async function connect(btn: HTMLButtonElement, key: string): Promise<void> {
    const L = app();
    if (!L) return;
    if (ask && !inst.trim()) {
      instEl?.focus();
      return;
    }
    btn.disabled = true;
    btn.setAttribute("aria-busy", "true");
    try {
      const x = (await L.api(`/connections/${key}/start`, ask ? { [ask[0]]: inst.trim() } : {})) as { authorize_url: string };
      delete INSTANCE[key];
      location.href = x.authorize_url;
    } catch (e) {
      btn.disabled = false;
      btn.removeAttribute("aria-busy");
      L.say((e as Error).message, "red");
    }
  }
  /** GitHub's device flow: the code to type there, then the poll */
  async function startDevice(btn: HTMLButtonElement, p: Provider): Promise<void> {
    const L = app();
    if (!L) return;
    btn.disabled = true;
    try {
      const x = (await L.api(`/connections/${p.key}/device`, {})) as Omit<NonNullable<typeof DEVICE.d>, "key">;
      DEVICE.d = { key: p.key, ...x };
      devicePoll(p.key);
      L.render();
    } catch (e) {
      btn.disabled = false;
      L.say((e as Error).message, "red");
    }
  }
  /** a pasted secret: sent once, the inputs cleared, never kept */
  function paste(btn: HTMLElement, p: Provider, fields: Field[]): void {
    const box = btn.closest(".paste");
    const inputs = fields.map((f) => box?.querySelector<HTMLInputElement>(`#f-${p.key}-${f.key}`) || null);
    const body: Record<string, string> = {};
    fields.forEach((f, i) => {
      body[f.key] = (inputs[i]?.value || "").trim();
    });
    const missing = fields.findIndex((f) => !body[f.key]);
    if (missing >= 0) {
      inputs[missing]?.focus();
      return;
    }
    afkAct(btn, (L) => L.api(`/api/connections/${p.key}/credentials`, body), (r) => {
      inputs.forEach((i) => {
        if (i) i.value = "";
      });
      app()?.say(r.message);
    });
  }
  function clearClient(btn: HTMLElement, key: string): void {
    afkAct(btn, (L) => L.api(`/api/connections/${key}/credentials`, { clear: true }), (r) => app()?.say(r.message));
  }
  const usedBy = (x: Account, pr: Provider): string =>
    [(x.scopes || []).join(" · "), x.sources.length ? "used by " + x.sources.map((s) => (typeof s === "string" ? undefined : s.label)).join(", ") : "no sources use it yet: add " + (pr.sources || []).join(" or ") + " from the catalog"].join(" · ");
</script>

{#snippet gone(text: string)}<div class="pane-empty"><p class="empty">{text}</p></div>{/snippet}
{#snippet steps(xs: string[] | undefined, label: string | null = null)}<ol class="steps-list" aria-label={label}>{#each xs || [] as s, i (i)}<li>{herePort(s)}</li>{/each}</ol>{/snippet}
{#snippet pasteForm(x: Provider, button: string)}
  {@const fields = x.fields || []}
  <div class="paste">{#each fields as f (f.key)}<div class="field"><label for={"f-" + x.key + "-" + f.key}>{f.label}</label><input id={"f-" + x.key + "-" + f.key} type={f.secret ? "password" : "text"} autocomplete="off" spellcheck="false" style="width:min(100%,360px)" placeholder={f.placeholder || ""} /></div>{/each}<div class="inline mt"><button class="btn" id={"save-" + x.key} onclick={(e) => paste(e.currentTarget, x, fields)}>{button}</button></div></div>
{/snippet}

<Detail back={view.back}>
  {#if key}
    <div data-title="Connection">
      {#if !host}
        <NeedHost what="Connections" />
      {:else if !d}
        <div class="pane-in"><Loading error={c?.error} /></div>
      {:else if !p}
        {@render gone("No such provider.")}
      {:else if p.state !== "available"}
        <Pane title={p.name} lede={p.blurb || p.reason} sections={[{ id: "about", w: "Not offered" }]}>
          {#snippet kind()}<Glyph name="closed" colour="grey" word="Not offered" />{` connection · ${howWord(p)}`}{/snippet}
          {#snippet section()}<p>{p.blurb || p.reason}</p>{/snippet}
        </Pane>
      {:else}
        {@const mine = d.accounts.filter((x) => x.provider === p.key)}
        {@const off = !!d.unavailable}
        {@const browser = ["browser", "both", "client"].includes(p.flow || "")}
        {@const ready = p.flow !== "client" || !!p.client_set}
        {@const st = mine.some((x) => x.state === "needs_login") ? (["warn", "amber", "Needs you"] as const) : mine.length ? (["check", "green", "Connected"] as const) : (["open", "grey", "Not connected"] as const)}
        {@const n = (p.steps || []).length}
        {@const secs = [...(mine.length ? [{ id: "connected", w: "Connected", n: mine.length }] : []),
          ...(p.flow === "browser" ? [{ id: "signin", w: "Steps" }] : p.flow === "both" ? [{ id: "signin", w: "Sign in (read-only scopes)" }, { id: "password", w: "Or: an app password" }]
            : p.flow === "client" ? [{ id: "project", w: p.client_section || "1. Your own client" }, { id: "signin", w: "2. Connect" }]
              : [{ id: "token", w: p.key === "github" ? "Paste a fine-grained token" : "Steps" }, ...(p.key === "github" ? [{ id: "device", w: "Sign in with GitHub (device flow)" }] : [])]),
          { id: "reads", w: "What it reads" }] as Sec[]}
        {#snippet go1()}<button class="btn primary" id="connect" disabled={!loop || off || !ready} onclick={(e) => connect(e.currentTarget, p.key)}>{mine.length ? "Connect again" : "Connect"}</button>{/snippet}
        <Pane title={"Connect " + p.name} lede={p.blurb || p.reason} sections={secs}>
          {#snippet kind()}<Glyph name={st[0]} colour={st[1]} word={st[2]} />{` connection · ${howWord(p)}`}{/snippet}
          {#snippet top()}
            {#if off}<div class="note c-amber" role="status"><Icon name="warn" /><div>{"Connected accounts are off: " + d.unavailable + "."}</div></div>{/if}
            {#if browser && !loop}<div class="note c-amber" role="status"><Icon name="warn" /><div>{need ? `${p.name} only sends your browser back to ${need}. ` : ""}{"Open Kranto as "}<a href={safeHref(here)}>{here.replace(/#.*$/, "")}</a>{need ? "" : " (or 127.0.0.1)"}{` to connect: the site sends your browser back to that address, through your SSH tunnel. This page is open as ${location.hostname}.`}</div></div>{/if}
          {/snippet}
          {#snippet section(s)}
            {#if s.id === "connected"}
              {#each mine as x (x.id)}<div class="acct"><p>{#if x.state === "needs_login"}<Mark name="warn" colour="amber" word="Needs you" />{:else}<Mark name="check" colour="green" word="Connected" />{/if}{" "}<strong>{x.account}</strong></p><p class="muted small">{usedBy(x, p)}</p><div class="inline"><button class="btn sm" onclick={(e) => test(e.currentTarget, x)}>Test</button><button class="btn sm" onclick={() => disconnect(x)}>Disconnect</button></div></div>{/each}
            {:else if s.id === "signin" && p.flow === "client"}
              {@render steps((p.steps || []).slice(n - 2))}<div class="inline mt">{@render go1()}</div><p class="muted small mono">{(p.client_set ? "" : (p.client_ready || "Save the client first.") + " ") + "Callback: " + callback}</p>
            {:else if s.id === "signin"}
              {@render steps(p.steps)}
              {#if ask}<div class="field mt"><label for="instance">{ask[1]}</label><div class="inline"><input id="instance" style="width:min(100%,320px)" placeholder={ask[2]} value={inst} bind:this={instEl} oninput={(e) => { inst = e.currentTarget.value; INSTANCE[p.key] = inst; }} />{@render go1()}</div></div>{:else}<div class="inline mt">{@render go1()}</div>{/if}
              <p class="muted small mono">{"Callback: " + callback}</p>
            {:else if s.id === "password"}
              {@render steps(p.alt_steps)}{@render pasteForm(p, "Save and test")}
            {:else if s.id === "project"}
              {@const cw = clientWords(p)}
              {#if p.cost}<p class="muted small" id="cost">{p.cost}</p>{/if}
              {@render steps((p.steps || []).slice(0, n - 2))}
              {#if p.client_set}<p><Mark name="check" colour="green" word={cw[0]} /><button class="btn sm" id="clear-client" onclick={(e) => clearClient(e.currentTarget, p.key)}>{cw[1]}</button></p>{:else}{@render pasteForm(p, "Save")}{/if}
            {:else if s.id === "token"}
              {@render steps(p.steps)}{@render pasteForm(p, "Save and test")}
            {:else if s.id === "device"}
              {#if !p.device}
                <p><span class="label plan">needs an OAuth app</span></p><p class="mt">GitHub's device flow needs an OAuth app that you register once; it carries no secret. Until then, connect with a token above. Once its client id is in your settings (written by hand; the setting is under Advanced below), a Sign in with GitHub button appears here.</p>{@render steps(p.device_steps)}<details class="advanced"><summary>Advanced</summary><p class="muted small">The setting: <code>connections.github_client_id</code>, in kranto.yaml.</p></details>
              {:else if dev}
                <p>{"Open "}<a href={safeHref(dev.verification_uri)} target="_blank" rel="noopener">{dev.verification_uri}</a>{" and type this code:"}</p><p class="device-code mono" id="user-code">{dev.user_code}</p><p class="muted small"><Mark name="running" colour="grey" word={`Waiting for GitHub; checking every ${dev.interval} s. The code expires in ${Math.round((dev.expires_in || 900) / 60)} minutes.`} /></p>
              {:else}
                <p>No token to paste: GitHub shows a code page, you type the code there and allow read:user. The page here notices by itself.</p><button class="btn primary" id="device" disabled={off} onclick={(e) => startDevice(e.currentTarget, p)}>Sign in with GitHub</button>
              {/if}
            {:else}
              <Kv rows={[["Scopes", (p.scopes || []).join(" · ") || "–", "mono"], ["Reads", p.reads || ""], ["Sources", (p.sources || []).join(", ") + ", from Add source"],
                ["Never", (p.never || "").replace(/^Never /, "")], ["Revoke", "Disconnect here, and on the site: " + (p.revoke_at || "")], ["Kept", p.expiry || ""], ["Sign-in", SIGNIN[p.flow || ""] || ""],
                ...(p.cost ? [["Cost", p.cost] as [string, string]] : [])]} />
            {/if}
          {/snippet}
        </Pane>
      {/if}
    </div>
  {:else if !host}
    {@render gone("Connections need the server, which is not answering.")}
  {:else if !d}
    <div class="pane-in"><Loading error={c?.error} /></div>
  {:else if id}
    {#if !a}{@render gone("No such account: it was disconnected.")}
    {:else}
      {@const pr = d.providers.find((x) => x.key === a.provider)}
      {@const needs = a.state === "needs_login"}
      {@const st = needs ? (["warn", "amber", "Needs you"] as const) : (["check", "green", "Connected"] as const)}
      <Pane title={a.account || a.provider_name} lede={needs ? (a.note || "The token was refused.") + " Connect again to resume its sources." : `Read-only, connected ${(a.connected_at || "").slice(0, 10)}.`}
        sections={[{ id: "account", w: "Account" }, { id: "sources", w: "Its sources", n: a.sources.length }]}>
        {#snippet kind()}<Glyph name={st[0]} colour={st[1]} word={st[2]} />{" account · " + a.provider_name}{/snippet}
        {#snippet acts()}{#if needs}<a class="btn sm primary" href={"#/settings/connections/" + a.provider}>Reconnect</a>{:else}<button class="btn sm" id="test-account" onclick={(e) => test(e.currentTarget, a)}>Test</button>{/if}<button class="btn sm" onclick={() => disconnect(a)}>Disconnect</button><a class="btn sm quiet" href={"#/settings/connections/" + a.provider}>{pr?.name || a.provider_name}</a>{/snippet}
        {#snippet section(s)}
          {#if s.id === "account"}
            <Kv rows={[["Provider", a.provider_name], ["Account", a.account], ["Scopes", (a.scopes || []).join(" · "), "mono"], ["Connected", (a.connected_at || "").slice(0, 10)],
              ["Last used", a.last_used_at ? rel(dt(a.last_used_at)) : "not used yet"], ["Kept", pr?.expiry || ""]]} />
          {:else if a.sources.length}
            <ul class="ctx">{#each a.sources as x, i (i)}<li>{#if typeof x !== "string" && x.id != null}<a href={"#/settings/sources/" + x.id}>{x.label}</a>{:else}<span>{typeof x === "string" ? x : x.label || String(x)}</span>{/if}</li>{/each}</ul>
          {:else}
            <p class="muted small">{`No source uses it yet: add ${(pr?.sources || []).join(" or ") || "one"} from the catalog.`}</p>
          {/if}
        {/snippet}
      </Pane>
    {/if}
  {:else}
    {@const st = d.unavailable ? SET_ST.warn : (["dot", "blue", "Connections"] as const)}
    <Pane title="Accounts Kranto may read with" sections={[{ id: "storage", w: "How tokens are kept" }]}>
      {#snippet kind()}<Glyph name={st[0]} colour={st[1]} word={st[2]} />{kindLine("sources", "connections")}{/snippet}
      {#snippet lede()}Read-only scopes; tokens stay on this machine.<Tip id="connections" about="connections" />{/snippet}
      {#snippet top()}{#if d.unavailable}<div class="note c-amber" role="status"><Icon name="warn" /><div>{"Connected accounts are off: " + d.unavailable + "."}</div></div>{/if}{/snippet}
      {#snippet section()}<Kv rows={Object.entries(d.storage).map(([k, v]) => [(k[0] || "").toUpperCase() + k.slice(1), v])} />{/snippet}
    </Pane>
  {/if}
</Detail>
