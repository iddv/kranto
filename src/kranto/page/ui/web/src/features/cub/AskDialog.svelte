<script lang="ts">
  // What a cub asks, as one plain dialog (SEND; the owner, 2026-10-29: "Not sure what 'ticket #1 is
  // expired' means, I just wanted to post the newsletter. Seems like nothing is connected. The
  // screenshot is a mess again"). the shape (DialogFrame, ReadBack): the question, the title,
  // whom it goes to by name and count, the body drawn and collapsed with Show all, Cancel and the
  // action's own verb (Send now, Post toot), Schedule where the platform can. Every word is
  // the server's, built from the ask's typed fields and its own rows (GET /api/tickets/<id>/ask).
  // What stops it is fixed here, not after: with no account its main button connects one in
  // place and comes back to the same ask (Send waits, one line says why); in practice the cub's
  // own Send for real switch is here, the owner's click. A practice approval says "Nothing was sent
  // (practice)" in the same place, never like a send. The audit facts are behind Details. Only the
  // page's own session approves (the server refuses any other door).
  import { openDetails } from "../../ui/details.svelte";
  import { onMount, untrack } from "svelte";
  import DialogFrame from "../../ui/DialogFrame.svelte";
  import ReadBack from "../../ui/ReadBack.svelte";
  import { app } from "../../lib/shell.svelte";
  import { CONNECTIONS_API, type Connections, type Field } from "../../pages/settings/connections";
  import { NEWSLETTER_API, type Newsletter } from "../../pages/settings/newsletter";
  import { askPath, inputOf, outcomeLine, sameWords, whenOf, type AskView } from "../ask";
  import { CUBS_API } from "../cub";
  import { href } from "../../lib/router";
  import { FEATURES_API } from "../index";

  // retime: a scheduled post's hour (UTC), when the dialog opens from its Change the time: titled
  // so, its When already open and filled with the hour it has, Schedule its button
  let { id, close, retime = null }: { id: number; close: () => void; retime?: string | null } = $props();
  // a post Kranto holds for its hour: the dialog's Schedule is typed in the person's own time
  let v = $state<AskView | null>(null);
  let err = $state<string | null>(null);
  let view = $state<"ask" | "connect" | "done">("ask");
  let result = $state<{ text: string; tone: string } | null>(null);
  const retiming = untrack(() => !!retime);
  let scheduling = $state(untrack(() => !!retime));
  let at = $state("");
  // the hour it has, in the box once the ask says whose clock it is typed in
  $effect(() => {
    const z = v?.ask?.zone;
    if (!retiming || at || !v) return;
    at = inputOf(untrack(() => retime), z);
  });
  let details = $state(false);
  let busy = $state(false);
  // Connect, in place: the newsletter's platforms to choose from, then the provider's own form
  let pick = $state<string | null>(null);
  let platforms = $state<Newsletter["platforms"]>([]);
  let conns = $state<Connections | null>(null);
  let said = $state<{ text: string; ok: boolean } | null>(null);

  const a = $derived(v?.ask || null);
  const needs = $derived(a?.needs || null);
  const provider = $derived(needs && conns ? conns.providers.find((p) => p.key === (pick || needs.connect)) || null : null);

  async function load(): Promise<void> {
    const L = app();
    if (!L) return;
    try {
      v = (await L.api(askPath(id, "ask"))) as AskView;
      err = null;
    } catch (e) {
      err = (e as Error).message;
    }
  }
  onMount(() => void load());

  /** a click that writes: the button busy, its error said in the dialog (never a toast away) */
  async function act(f: (L: NonNullable<ReturnType<typeof app>>) => Promise<unknown>): Promise<unknown> {
    const L = app();
    if (!L || busy) return null;
    busy = true;
    try {
      const r = await f(L);
      L.afkDrop();
      err = null;
      return r;
    } catch (e) {
      err = (e as Error).message;
      return null;
    } finally {
      busy = false;
    }
  }

  async function approve(): Promise<void> {
    if (!a) return;
    const when = a.schedule ? (scheduling ? whenOf(at, a.zone) : "now") : undefined;
    if (scheduling && !when) {
      err = "Choose the day and time to send it.";
      return;
    }
    const r = (await act((L) => L.api(askPath(id, "confirm"), { confirm: true, ...(when ? { when } : {}) }))) as { state?: string; note?: string | null; outcome?: { state?: string; note?: string } } | null;
    if (!r) return;
    // a post held for its hour answers "scheduled": the ask itself still waits
    result = outcomeLine(r.outcome?.state === "scheduled" ? "scheduled" : r.state || "unknown", r.outcome?.note ?? r.note);
    view = "done";
    app()?.render();
  }

  /** Decline, under Details: the owner's no; it is not sent and its row goes */
  async function decline(): Promise<void> {
    const r = await act((L) => L.api(askPath(id, "decline"), { note: "declined on the page" }));
    if (!r) return;
    result = { text: "Declined: it is not sent.", tone: "grey" };
    view = "done";
    app()?.render();
  }

  /** the cub's own Send for real (cubs.<id>.live): the owner's click, here */
  async function setReal(on: boolean): Promise<void> {
    const sw = a?.practice?.switch;
    if (!sw) return;
    const ok = await act((L) => L.api(`${CUBS_API}/${sw.cub}/${on ? "live" : "dry"}`, on ? { kind: sw.kind, confirm: true } : { kind: sw.kind }));
    const L = app();
    L?.afkStale(CUBS_API);
    L?.afkStale(FEATURES_API);
    if (ok) await load();
  }

  async function openConnect(): Promise<void> {
    const L = app();
    if (!L || !needs) return;
    said = null;
    pick = needs.connect === "newsletter" ? null : needs.connect;
    view = "connect";
    try {
      conns = (await L.api(CONNECTIONS_API)) as Connections;
      if (needs.connect === "newsletter") platforms = ((await L.api(NEWSLETTER_API)) as Newsletter).platforms;
    } catch (e) {
      err = (e as Error).message;
    }
  }

  /** Save and test: the pasted fields sent once and cleared; back to the same ask when it is ready */
  async function saveConnect(box: HTMLElement): Promise<void> {
    if (!provider) return;
    const fields = (provider.fields || []) as Field[];
    const inputs = fields.map((f) => box.querySelector<HTMLInputElement>(`#ask-f-${f.key}`));
    const body: Record<string, string> = {};
    fields.forEach((f, i) => (body[f.key] = (inputs[i]?.value || "").trim()));
    const missing = fields.findIndex((f) => !body[f.key]);
    if (missing >= 0) {
      inputs[missing]?.focus();
      return;
    }
    const r = (await act((L) => L.api(`${CONNECTIONS_API}/${provider.key}/credentials`, body))) as { message?: string; ok?: boolean } | null;
    inputs.forEach((i) => i && (i.value = ""));
    if (!r) return;
    await load();
    if (v && !v.ask.needs) {
      view = "ask";
      app()?.say(r.message || `${provider.name} is connected.`);
    } else said = { text: r.message || "Saved; something is still missing.", ok: false };
  }

  const STATE: Record<string, string> = { needs_confirm: "asked", confirmed: "approved", dry: "practiced", done: "done", expired: "ran out of time", declined: "declined", refused: "refused", unknown: "not sure it went out" };
  // what it rests on: the briefs, idea cards and observations, each its page
  const rests = $derived.by((): [string, string][] => {
    const b = (v?.because || {}) as { briefs?: number[]; ideas?: number[]; observations?: number[] };
    return [...(b.briefs || []).map((n): [string, string] => [`brief ${n}`, href("news", { sel: "f" + n })]),
      ...(b.ideas || []).map((n): [string, string] => [`idea card ${n}`, href("ideas/card:" + n)]),
      ...(b.observations || []).map((n): [string, string] => [`observation ${n}`, href("library/o/" + n)])];
  });
  const time = (s: string): string => (s || "").slice(0, 16).replace("T", " ");
  const cut = (s: string): string => (s.length > 160 ? s.slice(0, 160) + "…" : s);
</script>

{#snippet more()}
  {#if view === "ask" && a?.open}
    {#if needs}<button class="btn" disabled title={needs.words}>{a.verb}</button>
    {:else if a.schedule && !scheduling}<button class="btn" id="ask-schedule" onclick={() => (scheduling = true)}>Schedule</button>{/if}
  {:else if view === "connect"}
    <button class="btn" id="ask-back" onclick={() => (pick && needs?.connect === "newsletter" ? (pick = null) : (view = "ask"))}>Back</button>
  {/if}
{/snippet}

<DialogFrame title={a ? (retiming && a.open ? "Change the time" : a.question) : "Loading…"} {more} close={close} cancelText={view === "done" || (a && !a.open) ? "Close" : "Cancel"}
  okText={!a || view === "done" || !a.open ? "" : view === "connect" ? (provider ? "Save and test" : "") : needs ? needs.button : scheduling ? "Schedule" : a.verb}
  disabled={busy}
  ok={(btn) => (view === "connect" ? saveConnect(btn.closest("dialog") || document.body) : needs ? openConnect() : approve())}>
  {#if !v}
    <p class="muted">{err || "Reading it…"}</p>
  {:else if view === "connect" && needs}
    {#if needs.connect === "newsletter" && !pick}
      <p>Choose the account your issues go out through. Kranto keeps its key and shows it to nothing else.</p>
      <ul class="ask-choose">{#each platforms as p, i (p.id)}<li><button class={"btn" + (i === 0 ? " primary" : "")} id={"ask-pick-" + p.id} onclick={() => (pick = p.id)}>{p.name}</button> <span class="muted small">{p.about}</span></li>{/each}</ul>
    {:else if provider}
      <p class="pd-subject"><strong>{`Connect ${provider.name}`}</strong></p>
      <ol class="ask-steps">{#each provider.steps || [] as s, i (i)}<li>{s}</li>{/each}</ol>
      <div class="ask-paste">{#each (provider.fields || []) as f (f.key)}<div class="field"><label for={"ask-f-" + f.key}>{f.label}</label><input id={"ask-f-" + f.key} type={f.secret ? "password" : "text"} autocomplete="off" spellcheck="false" placeholder={f.placeholder || ""} /></div>{/each}</div>
      {#if said}<p class={"ask-line " + (said.ok ? "c-green" : "c-amber")} id="ask-said">{said.text}</p>{/if}
    {:else}
      <p class="muted">Reading the accounts…</p>
    {/if}
  {:else if a}
    <ReadBack subject={a.title} keys={a.to ? [["To", a.to]] : a.facts || []} longs={a.body ? [["body", a.body]] : []} />
    {#if view === "done" && result}
      <p class={"ask-result c-" + result.tone} id="ask-result" role="status">{result.text}</p>
    {:else if !a.open}
      <p class="ask-line" id="ask-said">{a.said || "This was answered already."}</p>
    {:else}
      {#if needs}<p class="ask-line c-amber" id="ask-needs">{needs.words}</p>{/if}
      {#if a.practice}
        {#if a.practice.switch}
          <label class="ask-real" for="ask-real"><input id="ask-real" type="checkbox" checked={!a.practice.on} disabled={busy} onchange={(e) => void setReal(e.currentTarget.checked)} /> <span><b>Send for real</b> <span class="muted small">{a.practice.switch.words}</span></span></label>
        {/if}
        <!-- a refusal in the same words as this line (the preview's) is said once: this line, in red -->
        {#if a.practice.on}<p class={"ask-line " + (err && sameWords(err, a.practice.words) ? "c-red" : "muted")} id="ask-practice" role={err && sameWords(err, a.practice.words) ? "alert" : null}>{a.practice.words}</p>{/if}
      {/if}
      {#if scheduling}
        <div class="field ask-when"><label for="ask-at">{a.zone === "local" ? "When (your time)" : "When, in UTC"}</label><input id="ask-at" type="datetime-local" bind:value={at} /></div>
      {/if}
    {/if}
    {#if err && !(a.practice?.on && a.open && view === "ask" && sameWords(err, a.practice.words))}<p class="ask-line c-red" role="alert">{err}</p>{/if}
    <button type="button" class="linkish small" id="ask-details" aria-expanded={details} onclick={() => (details = !details)}>Details</button>
    {#if details}
      <dl class="ask-facts" id="ask-facts">
        {#each v.readback as [k, x] (k)}<dt>{k}</dt><dd>{cut(x)}</dd>{/each}
        <dt>Asked</dt><dd>{time(v.created_at)}{v.run_uuid ? " · " : ""}{#if v.run_uuid}<a href={`#/afk/${v.run_uuid}/trace`} onclick={close}>the run that drafted it</a>{/if}</dd>
        <!-- a draft's ask has no time limit (the server stores 9999-12-31): it waits for your answer -->
        <dt>Open until</dt><dd>{String(v.expires_at || "").startsWith("9999") ? "you answer it: a draft waits until it is seen" : time(v.expires_at) + " UTC"}</dd>
        {#if rests.length}<dt>Rests on</dt><dd>{#each rests as [w, to], i (w)}{i ? ", " : ""}<a href={to} onclick={close}>{w}</a>{/each}</dd>{/if}
        <dt>History</dt><dd>{v.history.map((h) => `${time(h.created_at)} ${h.state === "expired" && /^replaced by #/.test(h.note || "") ? "replaced by a newer draft (" + (h.note || "").slice(12) + ")" : (STATE[h.state] || h.state) + (h.note ? ": " + h.note : "")}`).join(" · ")}</dd>
        <!-- the whole record, the one the console reads: the drawer -->
        <dt>Everything</dt><dd><button type="button" class="linkish small" id="ask-record" onclick={() => openDetails("ask:" + id)}>The full record ›</button><span class="muted">{" (the console: "}<code>{"kranto_details ask:" + id}</code>{")"}</span></dd>
        {#if a.open && view === "ask"}<dt>Not this one</dt><dd><button type="button" class="linkish small" id="ask-decline" onclick={() => void decline()}>Decline it</button><span class="muted">{" (it is not sent, and its row goes)"}</span></dd>{/if}
      </dl>
    {/if}
  {/if}
</DialogFrame>

<style>
  .pd-subject { margin: 0 0 8px; }
  .ask-line { font-size: 13px; margin: 8px 0 0; }
  .ask-result { font-size: 14px; font-weight: 600; margin: 10px 0 0; }
  .ask-real { display: flex; gap: 8px; align-items: baseline; margin: 10px 0 0; font-size: 13px; }
  .ask-when { margin: 10px 0 0; }
  .ask-choose { list-style: none; padding: 0; margin: 8px 0; display: flex; flex-direction: column; gap: 8px; font-size: 13px; }
  .ask-steps { font-size: 13px; padding-left: 18px; margin: 0 0 10px; }
  .ask-paste input { width: min(100%, 360px); }
  #ask-details { margin-top: 10px; display: block; }
  .ask-facts { display: grid; grid-template-columns: max-content 1fr; gap: 2px 12px; margin: 6px 0 0; font-size: 12px; color: var(--muted); }
  .ask-facts dd { margin: 0; overflow-wrap: anywhere; }
</style>
