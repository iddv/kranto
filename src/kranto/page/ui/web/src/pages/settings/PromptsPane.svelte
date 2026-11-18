<script lang="ts">
  // Settings › Prompts, the pane: with nothing selected what is customised and where it is kept;
  // a prompt's row (eprompt:<id>) is what it is for and where it runs, its placeholders, your
  // additions, the full prompt where it may be replaced (with its diff against the default),
  // Reset, the prompt now, its versions and a preview against a real item (no model call). All of
  // it is the server's /api/prompts. What is typed is a draft (PDRAFT) until its Save; a version
  // opens in place, with Use this version (a restore is undoable, so no confirm) and its note.
  import Icon from "../../shell/Icon.svelte";
  import Detail from "../../ui/Detail.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Kv from "../../ui/Kv.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import Pane, { type Sec } from "../../ui/Pane.svelte";
  import Row from "../../ui/Row.svelte";
  import Tip from "../../ui/Tip.svelte";
  import { ago, dt } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { drop } from "../../lib/reads.svelte";
  import { app, ui } from "../../lib/shell.svelte";
  import { groupOf, SET_ST, type St } from "../../ui/settings";
  import { confirmThen } from "../../ui/dialog.svelte";
  import {
    addTip, cap, diffLines, dropVersions, groupWord, hiSegs, PDRAFT, phLine, PPREV, previewLine, previewWhat, promptBase, promptRead, PROMPTS_API,
    promptsRead, promptState, restored, saved, takes, THREE, versionLine, versionMeta, versionRead, versionTitle, VNOTE, VOPEN,
    type Ph, type Preview, type Prompt, type VersionRow,
  } from "./prompts.svelte";

  let { view }: { view: View } = $props();
  const id = $derived(groupOf(view.w));
  const host = $derived(!!ui.facts?.header.host);
  // a prompt's row: its id
  const k = $derived(id && id.startsWith("prompt:") ? id.slice(7) : null);
  const c = $derived.by(() => {
    void view.tick; // each draw may find the read stale
    return host && k == null ? promptsRead() : null;
  });
  const d = $derived(c?.data || null);
  const pc = $derived.by(() => {
    void view.tick;
    return host && k != null ? promptRead(k) : null;
  });
  // the real items a prompt can be previewed against: the server's cards, topics and observations
  const subs = $derived.by((): [string, string][] => {
    void view.tick;
    const p = pc?.data;
    return p ? app()?.previewSubjects(p) ?? [] : [];
  });

  /* a prompt's writes: its additions, its full prompt, a reset; each answers the prompt again */
  const savedAs = (p: Prompt, key: string, word: string, drops: string[]) => (r: unknown): void => {
    const x = r as Prompt;
    saved(key, x);
    dropVersions(promptBase(key));
    for (const dk of drops) delete PDRAFT[dk];
    app()?.say(`Saved: ${p.title}, version ${x.n}. ${word}`);
  };
  function post(btn: HTMLElement, p: Prompt, key: string, body: Record<string, string>, word: string, drops: string[]): void {
    const L = app();
    if (L) void L.act(btn, () => L.api(promptBase(key), body), savedAs(p, key, word, drops));
  }
  function reset(btn: HTMLElement, p: Prompt, key: string, what: string, word: string): void {
    const L = app();
    if (L) void L.act(btn, () => L.api(promptBase(key) + "/reset", { what }), savedAs(p, key, word, [key + ":add", key + ":tpl"]));
  }

  /* a version: Use this version (undoable from the toast), and its note */
  function useVersion(btn: HTMLElement, v: VersionRow, key: string, cur: VersionRow | undefined): void {
    const L = app();
    if (!L) return;
    const base = promptBase(key);
    const again = (r: unknown): number => {
      restored(base, key);
      saved(key, r as Prompt);
      return (r as Prompt).n;
    };
    const back = cur && cur.n;
    void L.act(btn, () => L.api(base + "/restore", { version: v.n }), (r) => {
      const n = again(r);
      L.toast(`Now using v${v.n} again, saved as v${n} (same as v${v.n}).`, back ? () => void L.act(null, () => L.api(base + "/restore", { version: back }), (r2) => {
        const m = again(r2);
        L.toast(`Back to v${back}, saved as v${m}.`);
      }) : null);
    });
  }
  function saveNote(btn: HTMLElement, v: VersionRow, key: string, nk: string, note: string): void {
    const L = app();
    if (!L) return;
    const base = promptBase(key);
    void L.act(btn, () => L.api(base + "/versions/" + v.n + "/note", { note }), (r) => {
      delete VNOTE[nk];
      drop(base + "/versions/" + v.n, true);
      saved(key, r as Prompt);
      L.toast(note.trim() ? `Note kept on v${v.n}.` : `Note cleared on v${v.n}.`);
    });
  }

  /* the preview: against the item chosen, exactly what would be sent; no model is called */
  function runPreview(btn: HTMLButtonElement, p: Prompt, subject: string | null, hasSel: boolean): void {
    const L = app();
    if (!L) return;
    const pk = p.id;
    PPREV[pk] = { ...(PPREV[pk] || { subject: null }), subject, busy: true, error: null };
    btn.disabled = true;
    L.api(PROMPTS_API + "/preview", { id: p.id, ...(hasSel && subject ? { subject } : {}) })
      .then((x) => { PPREV[pk]!.data = x as Preview; })
      .catch((err: Error) => { PPREV[pk]!.data = null; PPREV[pk]!.error = err.message; })
      .finally(() => { PPREV[pk]!.busy = false; });
  }
  const resetAll = (btn: HTMLElement, p: Prompt, key: string): void => {
    confirmThen(`${p.title} back to the default?`, `Your additions${p.override ? " and your full prompt" : ""} stay listed as versions.`, "Back to the default", () => reset(btn, p, key, "all", "Back to the default."));
  };
  /* a prompt's sections: the full prompt only where it may be replaced */
  const promptSecs = (p: Prompt, full: boolean): Sec[] => {
    const secs: (Sec | null)[] = [{ id: "about", w: "About" }, { id: "placeholders", w: "Placeholders", n: p.placeholders.length || null }, { id: "additions", w: "Your additions" },
      full ? { id: "full", w: "Edit the full prompt" } : null, { id: "active", w: "The prompt now" }, { id: "versions", w: "Versions", n: (p.versions || []).length || null },
      { id: "preview", w: "Preview" }];
    return secs.filter((x): x is Sec => !!x);
  };
  const IN_USE: St = ["check", "green", "In use"];
  const KEPT: St = ["dot", "grey", "Kept"];
</script>

{#snippet gone(text: string)}<div class="pane-empty"><p class="empty">{text}</p></div>{/snippet}
{#snippet loading(text: string)}<div class="pane-in"><p class="empty">{text}</p></div>{/snippet}
{#snippet kindOf(st: St, w: string)}<Glyph name={st[0]} colour={st[1]} word={st[2]} />{" " + w}{/snippet}
<!-- a prompt's text with its placeholders marked -->
{#snippet hi(text: string | null | undefined, phs: Ph[])}<pre class="file prompt">{#each hiSegs(text, phs) as s, i (i)}{#if s.ph}<mark class="ph" title={s.title}>{s.text}</mark>{:else}{s.text}{/if}{/each}</pre>{/snippet}
{#snippet diff(text: string | null | undefined)}<pre class="file diff">{#each diffLines(text) as l, i (i)}<span class={l.cls}>{l.text}</span>{/each}</pre>{/snippet}
{#snippet note(colour: string, ic: string, text: string)}<div class={"note c-" + colour} role="status"><Icon name={ic} /><div>{text}</div></div>{/snippet}

<!-- a version opened in place: its text, its diff against the one in use, its note, Use this version -->
{#snippet vopen(v: VersionRow, key: string, cur: VersionRow | undefined, phs: Ph[])}
  {@const base = promptBase(key)}
  {@const nk = base + "#" + v.n + "@" + (cur ? cur.n : 0)}
  {@const vc = versionRead(base, v.n)}
  {@const x = vc.data}
  {#if !x}<p class="muted small">{vc.error ? "Could not read this version: " + vc.error : "Loading…"}</p>
  {:else}
    {@const typed = nk in VNOTE ? (VNOTE[nk] as string) : v.note || ""}
    <div class="vbody"><div class="inline">{#if v.active}<span class="muted small">In use now.</span>{:else if x.restorable}<button class="btn primary sm" id="use-version" onclick={(e) => useVersion(e.currentTarget, v, key, cur)}>Use this version</button>{/if}<input type="text" class="vnote" id="version-note" maxlength="80" value={typed} aria-label={`Note on v${v.n}`} placeholder="A short note, so you can find it again" oninput={(e) => (VNOTE[nk] = e.currentTarget.value)} onkeydown={(e) => { if (e.key === "Enter") { e.preventDefault(); saveNote(e.currentTarget, v, key, nk, e.currentTarget.value); } }} /><button class="btn sm" id="save-version-note" onclick={(e) => saveNote(e.currentTarget, v, key, nk, nk in VNOTE ? (VNOTE[nk] as string) : v.note || "")}>Save note</button></div>{#if !x.restorable}{@render note("amber", "warn", cap(x.why_not || "") + ".")}{/if}<p class="muted small mt">{versionLine(x)}</p>{#if !x.same_as_active}<h4 class="mt">{`Against the version in use (v${x.active_n})`}</h4>{@render diff(x.diff)}{/if}<h4 class="mt">{`The prompt v${x.n} gives`}</h4>{@render hi(x.text, phs)}</div>
  {/if}
{/snippet}
<!-- the versions of a prompt, newest first; nothing is ever deleted -->
{#snippet versionList(vs: VersionRow[] | undefined, key: string, phs: Ph[])}
  {#if !vs || !vs.length}<p class="muted small">No versions yet.</p>
  {:else}
    {@const base = promptBase(key)}
    {@const open = VOPEN[base]}
    {@const cur = vs.find((v) => v.active)}
    <p class="muted small">Open a version to see its text and what differs from the one in use. Using an old version saves it again as a new one, so nothing is lost.</p><ul class="lst pl versions">{#each vs.slice().reverse() as v (v.n)}{@const g = v.active ? IN_USE : KEPT}<Row title={versionTitle(v)} meta={versionMeta(v)} age={ago(dt(v.at))} cur={open === v.n} on={() => (VOPEN[base] = open === v.n ? null : v.n)}>{#snippet st()}<Glyph name={g[0]} colour={g[1]} word={g[2]} />{/snippet}{#snippet num()}{"v" + v.n}{/snippet}</Row>{#if open === v.n}<li class="vopen" id="version-open">{@render vopen(v, key, cur, phs)}</li>{/if}{/each}</ul>
  {/if}
{/snippet}

<Detail back={view.back}>
  {#if !host}
    {#if id}<NeedHost what="Prompts" />{:else}{@render gone("Prompts are the server's, which is not answering.")}{/if}
  {:else if !id}
    {#if !d}{@render loading(c?.error ? "Could not read the prompts: " + c.error : "Loading…")}
    {:else}
      {@const mine = d.prompts.filter((p) => p.customised)}
      {@const moved = d.prompts.filter((p) => p.default_changed)}
      <Pane title="Prompts you can see and steer" lede="Every save is a new version and nothing is deleted." sections={[{ id: "now", w: "Now" }]}>
        {#snippet kind()}{@render kindOf(moved.length ? SET_ST.warn : ["dot", "blue", "Prompts"], "settings · prompts")}{/snippet}
        {#snippet section()}<Kv rows={[["Customised", mine.length ? mine.map((p) => p.title).join(", ") : "nothing: every prompt is the default"], ["Default changed", moved.length ? moved.map((p) => p.title).join(", ") : "none"],
          ["Prompts", String(d.prompts.length)], ["Kept in", d.store, "mono"]]} />{/snippet}
      </Pane>
    {/if}
  {:else if k == null}
    {@render gone("Nothing to show here.")}
  {:else if !pc?.data}
    {#if pc?.error}{@render gone("Could not read this prompt: " + pc.error)}{:else}{@render loading("Loading…")}{/if}
  {:else}
    {@const p = pc.data}
    {@const full = p.editable === "full"}
    {@const ka = k + ":add"}
    {@const kt = k + ":tpl"}
    {@const add = ka in PDRAFT ? (PDRAFT[ka] as string) : p.additions_text || ""}
    {@const tpl = kt in PDRAFT ? (PDRAFT[kt] as string) : p.template != null ? p.template : p.default}
    {@const P = PPREV[k] || { subject: null }}
    {@const subject = P.subject ?? subs[0]?.[0] ?? null}
    {@const px = P.data && P.data.id === p.id ? P.data : null}
    {@const st = promptState(p)}
    <Pane title={p.title} lede={p.purpose} right={`version ${p.version}`} sections={promptSecs(p, full)}>
      {#snippet kind()}{@render kindOf(st, `prompt · ${groupWord(p.group)}`)}{/snippet}
      {#snippet acts()}{#if p.customised}<button class="btn sm" id="reset-prompt" onclick={(e) => resetAll(e.currentTarget, p, k)}>Reset</button>{/if}{/snippet}
      {#snippet top()}{#if p.notice}<div class="note c-amber" role="status"><Icon name="warn" /><div><strong>{cap(p.notice) + ". "}</strong>Your full prompt still applies. Read what changed in the default below, then keep yours, edit it, or Reset.{#if p.three_way}<details class="fold mt" id={"three-" + k} open={THREE[k]} ontoggle={(e) => (THREE[k] = e.currentTarget.open)}><summary>What changed in the default</summary>{@render diff(p.three_way.diff_default)}</details>{/if}</div></div>{/if}{#if p.checker_note}<div class="note c-grey" role="status"><Icon name="note" /><div><strong>{cap(p.checker_note) + "."}</strong>{" You can add to it; you cannot replace it."}</div></div>{/if}{#if p.defaults_only}{@render note("amber", "warn", "This process runs on the defaults (KRANTO_PROMPTS=defaults): what you save here does not apply to it.")}{/if}{/snippet}
      {#snippet section(s)}
        {#if s.id === "about"}<Kv rows={[["Runs", p.where], ["Step", p.step], ["Takes", takes(p)], ["Can change", full ? "additions, or the full prompt" : "additions only"],
          ["File", p.file, "mono"], ["Version", `${p.version}${p.n ? ` (yours, v${p.n})` : " (the default)"}`, "mono"]]} />
        {:else if s.id === "placeholders"}{#if p.placeholders.length}<ul class="phs">{#each p.placeholders as x (x.token)}<li><mark class="ph mono">{x.token}</mark>{" "}<span>{x.description}</span>{#if !x.required}<span class="muted small">{" (may go)"}</span>{/if}</li>{/each}</ul><p class="muted small mt">{phLine(p)}</p>{#each p.notes || [] as n, i (i)}<p class="muted small">{n}</p>{/each}{:else}<p class="muted small">None: the context follows it.</p>{/if}
        {:else if s.id === "additions"}<textarea id="prompt-add" class="prompt-ta" rows="5" aria-label="Your additions" placeholder="What to add to this prompt, in plain words." value={add} oninput={(e) => (PDRAFT[ka] = e.currentTarget.value)}></textarea><div class="inline mt"><Tip id={{ text: addTip(p) }} about="your additions" /><button class="btn primary" id="save-additions" onclick={(e) => post(e.currentTarget, p, k, { additions: add }, add.trim() ? "Your additions apply from its next call." : "No additions now.", [ka])}>Save additions</button>{#if p.additions}<button class="btn sm quiet" onclick={(e) => reset(e.currentTarget, p, k, "additions", "Your additions are cleared.")}>Clear them</button>{/if}</div>
        {:else if s.id === "full"}<textarea id="prompt-tpl" class="prompt-ta tall" rows="16" spellcheck="false" aria-label="The full prompt" value={tpl} oninput={(e) => (PDRAFT[kt] = e.currentTarget.value)}></textarea><div class="inline mt"><Tip id={{ text: "Replaces the default text; your additions still go where they go. Saving the default's exact text drops your version." }} about="the full prompt" /><button class="btn" id="save-template" onclick={(e) => post(e.currentTarget, p, k, { template: tpl }, "Your full prompt applies from its next call.", [kt])}>Save the full prompt</button>{#if p.override}<button class="btn sm quiet" onclick={(e) => reset(e.currentTarget, p, k, "template", "Back to the default text; your additions stay.")}>Back to the default text</button>{/if}</div>{#if p.diff}<h4 class="mt">Against the default</h4>{@render diff(p.diff)}{:else}<p class="muted small mt">No full prompt of yours: this is the default.</p>{/if}
        {:else if s.id === "active"}<p class="muted small">What the next call gets, before the placeholders are filled. Placeholders are marked.</p>{@render hi(p.active, p.placeholders)}
        {:else if s.id === "versions"}{@render versionList(p.versions, k, p.placeholders)}
        {:else}<p class="small">{previewWhat(p)}</p><div class="inline mt">{#if subs.length}<select id="preview-subject" aria-label="Preview against" onchange={(e) => (PPREV[k] = { ...P, subject: e.currentTarget.value })}>{#each subs as [v, w] (v)}<option value={v} selected={v === subject}>{w}</option>{/each}</select>{/if}<button class="btn" id="preview-prompt" disabled={!!P.busy} onclick={(e) => runPreview(e.currentTarget, p, subject, subs.length > 0)}>{P.busy ? "Previewing…" : "Preview"}</button></div>{#if P.error}{@render note("red", "x", "The preview failed: " + P.error)}{/if}{#if px}<p class="muted small mt">{previewLine(px)}</p>{@render hi(px.text, p.placeholders)}{/if}{/if}
      {/snippet}
    </Pane>
  {/if}
</Detail>
