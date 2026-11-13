<script lang="ts">
  // Feedback (FB): the sheet. The kind, one box for the words, and Include details (on), which
  // shows exactly what it adds before anything is sent. File it (the person's own gh can file on
  // the repository) confirms the whole issue first; Open on GitHub opens GitHub's new-issue page,
  // prefilled, where the person presses Submit. The draft is kept in this browser while the sheet
  // is closed, and cleared once filed. With no network, it says so and keeps the draft. Send this
  // error (RCA B3) opens it with an error's id: its report (the server's /api/errors/<id>: the id,
  // its kind, Kranto's own code lines, the version, the OS, the doctor's summary) is shown here
  // whole, and goes in the issue as shown.
  import { onMount, untrack } from "svelte";
  import { ISSUE_API, KINDS, REPORT_API, clearDraft, fitted, issue, loadDraft, saveDraft, withError, type Draft, type ErrorReport, type FeedbackStatus, type Machine } from "./feedback";
  import { backToSheet, confirmFiling, factsNow, namesNow } from "./sendFeedback";
  import { host } from "../lib/app/data";

  type Filed = { number: number; url: string; repo: string; dropped: string[] };
  let { error = null, report = null, hash, back = null, close }: { error?: string | null; report?: string | null; hash: string; back?: { filed?: Filed | null; error?: string | null } | null; close: () => void } = $props();

  let st = $state<FeedbackStatus | null>(null);
  let stErr = $state<string | null>(null);
  let online = $state(typeof navigator === "undefined" || navigator.onLine !== false);
  let upd = $state<{ version: string; update: NonNullable<ReturnType<typeof factsNow>["update"]> } | null>(null);
  let opened = $state(false);
  // the error's report (Send this error): read when the sheet opens; null while reading or without one
  const reportId = untrack(() => report);
  let rep = $state<ErrorReport | null>(null);
  let repErr = $state<string | null>(null);
  const repText = $derived(rep ? `${rep.title}\n\n${rep.body}` : reportId && repErr ? `Error ${reportId} (its report could not be read here: ${repErr})` : null);
  const filed = untrack(() => (back && back.filed) || null);
  const said = untrack(() => (back && back.error) || null);
  const names = namesNow();
  const base = untrack(() => factsNow(hash));
  const machine = $derived<Machine>(st ? { places: st.places, host: st.host, login: st.login } : { places: [], host: null, login: null });
  if (filed) clearDraft();
  const first = untrack(() => error);
  let draft = $state<Draft>(first ? withError(loadDraft(), first, { places: [], host: null, login: null }, names) : loadDraft());
  $effect(() => saveDraft({ kind: draft.kind, text: draft.text, include: draft.include }));

  const repo = $derived(st ? st.repo : "iddv/kranto");
  // hosted, the version and the update state are the server's (read when the sheet opens); the page
  // alone, its own version and no update state
  let updRead = $state(false);
  const facts = $derived({ ...base, version: upd ? upd.version : host() && !updRead ? "reading…" : st ? `the page ${st.version}` : "reading…", update: upd ? upd.update : null });
  const reach = $derived(online && (!st || st.reachable));
  const can = $derived(!!st && st.can_file && reach);
  // the page's version of the issue: what File it files, and (fitted) what the link carries
  const full = $derived(issue(draft, facts, machine, names, 0, repText));
  const fit = $derived(fitted(draft, facts, machine, names, repo, undefined, repText));
  const shown = $derived(can ? full : fit.issue);
  const empty = $derived(!draft.text.trim());
  // nothing is sent while the details are still being read: what is shown is what goes
  const readying = $derived((draft.include && ((!!host() && !updRead) || (!st && !stErr))) || (!!reportId && !rep && !repErr));

  async function readStatus(fresh = false): Promise<void> {
    stErr = null;
    online = navigator.onLine !== false;
    try {
      const r = await fetch(ISSUE_API + (fresh ? "?fresh=1" : ""), { cache: "no-store" });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
      st = (await r.json()) as FeedbackStatus;
    } catch (e) {
      stErr = (e as Error).message || "Kranto did not answer";
    }
  }
  async function readUpdate(): Promise<void> {
    if (!host()) return;
    try {
      const r = await fetch("/api/update", { cache: "no-store" });
      if (!r.ok) return;
      const d = (await r.json()) as { installed?: { version?: string; channel?: string }; checked_at?: string | null; ok?: boolean; error?: string | null; available?: string | null };
      upd = { version: d.installed && d.installed.version ? `${d.installed.version}${d.installed.channel ? ` (${d.installed.channel})` : ""}` : "unknown", update: { checked_at: d.checked_at, ok: d.ok, error: d.error, available: d.available } };
    } catch {
      /* the update state is said as not known */
    } finally {
      updRead = true;
    }
  }
  async function readReport(): Promise<void> {
    if (!reportId) return;
    if (!host()) {
      repErr = "the server keeps the reports, and it is not here";
      return;
    }
    try {
      const r = await fetch(REPORT_API(reportId), { cache: "no-store" });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
      const j = (await r.json()) as ErrorReport | null;
      if (!j || !j.title) throw new Error("the server sent no report for it");
      rep = j;
    } catch (e) {
      repErr = (e as Error).message || "Kranto did not answer";
    }
  }
  onMount(() => {
    void readStatus();
    void readUpdate();
    void readReport();
    const on = () => (online = true), off = () => (online = false);
    addEventListener("online", on);
    addEventListener("offline", off);
    return () => {
      removeEventListener("online", on);
      removeEventListener("offline", off);
    };
  });
  function fileIt(): void {
    if (!st || empty) return;
    confirmFiling(st, $state.snapshot(draft) as Draft, full, hash);
  }
  function startOver(): void {
    clearDraft();
    draft = { kind: "bug", text: "", include: true };
    opened = false;
  }
</script>

<div class="dlg-h" id="dlg-t">Feedback</div>
<div class="dlg-b" id="feedback">
  {#if filed}
    <p id="fb-filed"><strong>Filed #{filed.number} on {filed.repo}.</strong> <a href={filed.url} target="_blank" rel="noopener noreferrer">Open it on GitHub ↗</a></p>
    <p class="muted small">Thank you. You will hear back there{filed.dropped.length ? `; the label${filed.dropped.length > 1 ? "s" : ""} ${filed.dropped.join(" and ")} ${filed.dropped.length > 1 ? "are" : "is"} not on the repository yet, so the issue says its kind in its body` : ""}. The draft is cleared.</p>
  {:else}
    {#if said}<div class="flash red" role="status" id="fb-said"><div>{said}</div></div>{/if}
    <div class="seg" role="radiogroup" aria-label="Kind" id="fb-kind">
      {#each KINDS as [k, w] (k)}<button type="button" class="btn sm" role="radio" data-kind={k} aria-checked={draft.kind === k ? "true" : "false"} onclick={() => (draft.kind = k)}>{w}</button>{/each}
    </div>
    <div class="field mt"><label for="fb-text">What happened, or what would you like?</label>
      <!-- svelte-ignore a11y_autofocus -->
      <textarea id="fb-text" style="min-height:120px" autofocus bind:value={draft.text} placeholder={draft.kind === "bug" ? "What you clicked, what you expected, what happened" : draft.kind === "idea" ? "What you would like Kranto to do" : "What you would like to know"}></textarea>
    </div>
    {#if reportId}
      <p class="hint small muted" id="fb-report-what">The error's report goes with it, exactly as below: its id, its kind, the lines of Kranto's own code it went through, the version, your OS and the doctor's summary. Nothing of yours is in it.</p>
      <pre class="cmd" id="fb-report">{repText || "Reading the error's report…"}</pre>
    {/if}
    <label class="check"><input type="checkbox" id="fb-include" bind:checked={draft.include} /> Include details</label>
    {#if draft.include}
      <p class="hint small muted">Added to the issue, exactly as below: Kranto's version, the layout, this page's route (its pattern, no ids), the browser, the update state and the last errors this page said, with paths, tokens and your topics' and ideas' names taken out.</p>
      <pre class="cmd" id="fb-details">{shown.details}</pre>
    {/if}
    {#if !can && fit.trimmed}<p class="small muted" id="fb-trimmed">{fit.trimmed}</p>{/if}
    {#if !reach}
      <div class="flash amber" role="status" id="fb-offline"><div class="grow">GitHub can't be reached from here right now. Your draft is kept: send it when you are back online.</div><button type="button" class="linkish" onclick={() => void readStatus(true)}>Try again</button></div>
    {:else if stErr}
      <p class="small muted" id="fb-where">Kranto could not check your gh ({stErr}); Open on GitHub sends it from the browser, to {repo}.</p>
    {:else if !st}
      <p class="small muted" id="fb-where">Checking how this can be sent…</p>
    {:else}
      <p class="small muted" id="fb-where">{st.line} It goes to <strong>{repo}</strong>, labelled feedback and {draft.kind}.</p>
    {/if}
    {#if opened}<p class="small" id="fb-opened">GitHub's new-issue page is open in a new tab: click <strong>Submit new issue</strong> there. The draft stays here until you <button type="button" class="linkish" id="fb-clear" onclick={startOver}>clear it</button>.</p>{/if}
  {/if}
</div>
<div class="dlg-f">
  {#if filed}
    <button class="btn" onclick={() => { startOver(); backToSheet(hash); }}>Send another</button>
    <!-- svelte-ignore a11y_autofocus -->
    <button class="btn primary" autofocus onclick={close}>Done</button>
  {:else}
    <button class="btn" onclick={close} title="The draft is kept">Close</button>
    {#if reach && !empty && !readying}
      <a class={"btn" + (can ? "" : " primary")} id="fb-open" href={fit.url} target="_blank" rel="noopener noreferrer" title="GitHub's new-issue page, filled in; you click Submit there" onclick={() => (opened = true)}>Open on GitHub ↗</a>
    {:else}
      <button class={"btn" + (can ? "" : " primary")} id="fb-open" disabled title={empty ? "Write what happened first" : readying ? "Reading the details first" : "GitHub can't be reached"}>Open on GitHub ↗</button>
    {/if}
    {#if st && st.can_file}<button class="btn primary" id="fb-file" disabled={!can || empty || readying} title={`Files it on ${repo} as ${st.login}, after you read it`} onclick={fileIt}>File it</button>{/if}
  {/if}
</div>
