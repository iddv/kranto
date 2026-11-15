<script lang="ts">
  // Settings › Watching › Live search, a row's pane. Search with: the backend,
  // tested at the press and kept only when the test passes; a key (Exa's optional, Brave's and
  // Tavily's needed) is a password field read once at the press and cleared then, kept in the
  // workspace's .env by the server, never in a page or your settings. Who searches: each caller on
  // or off (off: it runs from model memory and says so). Recent means: the weeks every grounded
  // prompt calls recent.
  import Detail from "../../ui/Detail.svelte";
  import FLabel from "../../ui/FLabel.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Kv from "../../ui/Kv.svelte";
  import Loading from "../../ui/Loading.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import Pane from "../../ui/Pane.svelte";
  import SaveBar from "../../ui/SaveBar.svelte";
  import SettingField from "../../ui/SettingField.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { drop, read } from "../../lib/reads.svelte";
  import { app, ui } from "../../lib/shell.svelte";
  import { href } from "../../lib/router";
  import { groupOf, kindLine, SET_ST } from "../../ui/settings";
  import { saveUndo } from "../../ui/save";
  import { CALLERS, CALLERS_API, callersLine, choicesOf, SEARCH_API, SEARCH_FORM, searchWords, weeksValue, type SearchSetup } from "./search.svelte";

  let { view }: { view: View } = $props();
  const id = $derived(groupOf(view.w));
  const host = $derived(!!ui.facts?.header.host);
  const r = $derived.by(() => {
    void view.tick;
    return host ? read<SearchSetup>(SEARCH_API, 10000) : null;
  });
  const s = $derived(r?.data || null);
  let keyIn = $state<HTMLInputElement>();
  const pick = $derived(SEARCH_FORM.provider ?? s?.provider ?? "exa");
  const choice = $derived(s?.choices.find((c) => c.provider === pick) || null);
  const label = (p: string) => s?.choices.find((c) => c.provider === p)?.label || p;

  function reread(): void {
    drop(SEARCH_API);
    app()?.afkDrop();
  }

  function saveProvider(btn: HTMLElement): void {
    const L = app();
    if (!L || !s) return;
    const chose = pick, was = s.provider, word = label(pick);
    const key = keyIn ? keyIn.value.trim() : "";
    if (keyIn) keyIn.value = "";
    if (choice?.key_env && chose !== "exa" && !key && !choice.key_set) {
      keyIn?.focus();
      return;
    }
    void saveUndo(btn, {
      write: () => L.api(SEARCH_API, { provider: chose, ...(key ? { key } : {}) }),
      undo: chose !== was ? () => L.api(SEARCH_API, { provider: was }) : null,
      what: (x) => `live search with ${word}, ${((x as { test?: { detail?: string } }).test?.detail || "tested").replace(/\.$/, "")}${key ? "; the key is kept in this workspace's .env (readable by you only)" : ""}`,
      effect: "now",
      after: () => {
        SEARCH_FORM.provider = null;
        reread();
      },
    });
  }

  function saveCallers(btn: HTMLElement): void {
    const L = app();
    if (!L || !s) return;
    const was = { ...s.callers }, now = { ...s.callers, ...SEARCH_FORM.callers };
    void saveUndo(btn, {
      write: () => L.api(CALLERS_API, { callers: now }),
      undo: () => L.api(CALLERS_API, { callers: was }),
      what: () => `who searches, ${callersLine(now)}`,
      effect: "run",
      after: () => {
        SEARCH_FORM.callers = {};
        reread();
      },
    });
  }

  function saveWeeks(btn: HTMLElement, to: number | null): void {
    const L = app();
    if (!L || !s) return;
    const was = s.recent_weeks;
    let n = was;  // read at the press, inside the write: a bad number is refused in red
    void saveUndo(btn, {
      write: () => {
        n = to ?? weeksValue(SEARCH_FORM.weeks ?? String(was));
        return L.api(CALLERS_API, { recent_weeks: n });
      },
      undo: () => L.api(CALLERS_API, { recent_weeks: was }),
      what: () => `recent means the last ${n} weeks`,
      effect: "run",
      after: () => {
        SEARCH_FORM.weeks = null;
        reread();
      },
    });
  }
</script>

<Detail back={view.back}>
  {#if !host}
    <NeedHost what="Live search" />
  {:else if !s}
    <div class="pane-in"><Loading error={r?.error} /></div>
  {:else if id === "search"}
    {@const w = searchWords(s)}
    <Pane title="Search with" lede="The backend that answers every caller asking what exists, what is new or what is prior art. Hacker News, GitHub and arXiv are searched too, always free." right={s.web_label || "none"} sections={[{ id: "pick", w: "Backend" }, { id: "now", w: "Now" }]}>
      {#snippet kind()}<Glyph name={w.st[0]} colour={w.st[1]} word={w.st[2]} />{kindLine("watching", "live search")}{/snippet}
      {#snippet section(sec)}
        {#if sec.id === "pick"}
          <SettingField id="search-provider" label="Search with" kind="enum" value={pick} input={(v) => (SEARCH_FORM.provider = v)} choices={s.choices.map((c) => [c.provider, c.label] as [string, string])} now={label(s.provider)} dflt="Exa" />
          {#if choice?.key_env}
            <div class="field">
              <FLabel forId="search-key" text={pick === "exa" ? "Key (optional)" : "Key"} />
              <input id="search-key" type="password" autocomplete="off" bind:this={keyIn} style="width:24em" placeholder={choice.key_set ? `set in $${choice.key_env}; paste to replace` : `$${choice.key_env}`} />
            </div>
            {#if pick === "exa"}<p class="muted small">Without a key: Exa's free mode, rate-limited, no account. A key from a free Exa account gives you your own limits.</p>{/if}
          {/if}
          {#if pick === "none"}<p class="muted small">{`Every caller then says "${s.no_search}".`}</p>{/if}
          <SaveBar id="search-save" label="Test and save" effect="now" save={(b) => saveProvider(b)} />
        {:else}
          <Kv rows={[["Backend", w.line], ["Cached", s.cache_hours ? `the same query within ${s.cache_hours} h (titles, links, dates and snippets)` : "never"], ["Cap", s.monthly_usd == null ? "no cap" : `$${s.monthly_usd} a month`]]} />
          {#if s.free_mode_words}<p class="muted small mt">{s.free_mode_words}.</p>{/if}
          <p class="small mt">Its cap and this month's searches: <a href={href("settings/spend", { sel: "ecap:search" })}>Settings › Spend › Live search a month</a>.</p>
        {/if}
      {/snippet}
    </Pane>
  {:else if id === "search:callers"}
    <Pane title="Who searches" lede="Each caller that asks what exists, what is new or what is prior art. Off: it runs from model memory and says so." right={callersLine(s.callers)} sections={[{ id: "callers", w: "Callers" }]}>
      {#snippet kind()}<Glyph name={SET_ST.set[0]} colour={SET_ST.set[1]} word={SET_ST.set[2]} />{kindLine("watching", "live search")}{/snippet}
      {#snippet section()}
        {#each CALLERS as [k, w, why] (k)}
          <SettingField id={"search-" + k} label={w} kind="enum" hint={why} value={SEARCH_FORM.callers[k] ?? s.callers[k] ?? choicesOf(k)[0]![0]} input={(v) => (SEARCH_FORM.callers[k] = v)} choices={choicesOf(k)} />
        {/each}
        <SaveBar id="search-callers-save" effect="run" save={(b) => saveCallers(b)} />
      {/snippet}
    </Pane>
  {:else if id === "search:weeks"}
    <Pane title="Recent means" lede="Every grounded prompt calls results from these last weeks recent, and asks for them first." right={`${s.recent_weeks} weeks`} sections={[{ id: "weeks", w: "Weeks" }]}>
      {#snippet kind()}<Glyph name={SET_ST.set[0]} colour={SET_ST.set[1]} word={SET_ST.set[2]} />{kindLine("watching", "live search")}{/snippet}
      {#snippet section()}
        <SettingField id="search-weeks" label="Recent means the last" kind="number" value={SEARCH_FORM.weeks ?? String(s.recent_weeks)} input={(v) => (SEARCH_FORM.weeks = v)} now={`${s.recent_weeks} weeks`} dflt="12 weeks" min={1} max={520} />
        <SaveBar id="search-weeks-save" effect="run" save={(b) => saveWeeks(b, null)} dflt={s.recent_weeks !== 12 ? (b) => saveWeeks(b, 12) : null} />
      {/snippet}
    </Pane>
  {:else}
    <div class="pane-empty"><p class="empty">No such setting.</p></div>
  {/if}
</Detail>
