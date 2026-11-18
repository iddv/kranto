<script lang="ts">
  // The top bar, 40 px: ☰ (the navigator's drawer, under
  // 1180 px), the mark and wordmark (→ Home), the doors, the search button (the palette), then
  // the state: what Kranto is doing, one item (D-2: "Quiet · next: reading your
  // sources at 18:00", "2 running · writing the News brief", "Paused"),
  // opening Activity; an update; Pause (its tooltip and its flash say what it stops); Feedback
  // (FB: an issue on Kranto's GitHub, from you); light or dark (◐). No spend chip: dollars live in
  // Settings › Spend and Activity. one state item in a word (its detail is its
  // tooltip), "Update ready" while one is staged, Pause, ⚙, ◐; Feedback is ⚙'s (D-5) where there
  // is a ⚙, a button of its own otherwise.
  import ActivityIndicator from "./ActivityIndicator.svelte";
  import Brand from "./Brand.svelte";
  import Icon from "./Icon.svelte";
  import Mark from "./Mark.svelte";
  import { app, navDrawer, openPalette, ui } from "../lib/shell.svelte";
  import { frameNew, shellDoors } from "../features/shell";
  import { baseWords, flipTo } from "../lib/theme";
  import { openFeedback } from "../ui/sendFeedback";
  import { consoleUi, setPlace } from "../term/console.svelte";
  import { DOORS } from "./doors";
  import { needsTotal, waitsWords } from "../pages/front/needstotal";
  import type { Host } from "../pages/front/needs";
  import { keyLabel } from "../lib/keys";

  const f = $derived(ui.facts?.header);
  // the doors' pages (either layout): the mark goes home; in the new layout Settings is the gear
  // (the classic one has it in its tree)
  const home = $derived(!!f && shellDoors(!!f.host) && ui.drawn >= 0);
  const gear = $derived(!!f && frameNew(!!f.host) && ui.drawn >= 0);
  const paused = $derived(!!f && !!f.host?.paused);
  // the door the page is in (lib/app/chrome.ts doorId), lit in the top bar
  const door = $derived(ui.facts?.door?.id ?? null);
  // with the doors on Pause asks nothing (it offers Resume), so its word has no ellipsis (D-6)
  const asks = $derived(!(f && shellDoors(!!f.host) && ui.drawn >= 0));
  // the lanes' facts, for the indicator until the activity read arrives
  const lanes = $derived({
    paused,
    afkRunning: f?.host?.running ?? null,
    reading: f?.host?.reading ?? null,
    next: f?.host?.next ?? null,
  });
  // what waits for you, counted as Needs you counts it (nothing drawn at 0)
  const waiting = $derived.by(() => {
    void ui.drawn;
    return f?.host ? needsTotal((app()?.host() as Host | null | undefined) || null) : 0;
  });
  const theme = $derived(f ? `${f.theme.name}, ${f.theme.dark ? "dark" : "light"}` : "");
  const other = $derived.by(() => { void f; return flipTo() === "auto" ? "Auto (your device)" : f?.theme.dark ? "light" : "dark"; });

  function toggleTheme(): void {
    const L = app();
    if (!L) return;
    const to = flipTo(); // back to Auto when the other scheme is the device's
    L.setTheme(to);
    L.render();
    L.toast(baseWords(to));
  }
</script>

{#if f}
  <button class="menu" id="menu" type="button" aria-label="Sections" aria-controls="nav" aria-expanded={ui.navOpen ? "true" : "false"} onclick={() => navDrawer(!ui.navOpen)}>☰</button>
  <a class="brand" href="#/home" aria-label="Kranto, Home"><Brand /><span class="word">Kranto</span>{#if home && waiting > 0}<span class="needs-dot" title={waitsWords(waiting)}></span>{/if}</a>
  {#if home}
    <!-- the doors: News, Ideas, Watch, Post on every page, in the order of a day;
         on a phone they are the bar at the bottom (TabBar) -->
    <nav class="hd-doors" id="hd-doors" aria-label="Doors">{#each DOORS as [id, word, to] (id)}<a href={to} id={"door-" + id} aria-current={door === id ? "page" : null}>{word}</a>{/each}</nav>
  {:else}
    <span class="host" title="the page, on this machine">on this machine</span>
  {/if}
  <button class="search" id="hd-search" type="button" aria-label={`Search and commands (${keyLabel("⌘K")})`} onclick={() => openPalette("")}><Icon name="search" /><span class="grow">{home ? "Search" : "Search ideas, evidence, sources…"}</span><kbd>{keyLabel("⌘K")}</kbd></button>
  <!-- Needs you's count, only when something waits: the same number as
       Needs you's head and the home's sentence (needstotal.ts) -->
  {#if home && waiting > 0}<a class="hd-needs" id="hd-needs" href="#/needs" aria-current={door === "needs" ? "page" : null} title={waitsWords(waiting)}>Needs you <span class="n">{waiting}</span></a>{/if}
  <div class="hd-status" role="status">
    <span class="lanes">
      <!-- what Kranto is doing, one item for both lanes: its words are the
           lanes' folded in; Activity has the rest -->
      <ActivityIndicator {lanes} tick={ui.drawn} />
      {#if f.update}{@const u = f.update}<a class="hd-st" id="hd-update" href="#/settings/updates" title={u.title + (u.detail ? ": " + u.detail : "")}><Mark name={u.icon} colour={u.colour} word={u.word} /></a>{/if}
    </span>
    <button class="btn sm" id="pause" title={paused ? `Resume ${f.pauses}` : `Pause everything: stops ${f.pauses}.`} onclick={(e) => app()?.togglePause(e.currentTarget, !paused)}>{paused ? "Resume" : asks ? "Pause" : "Pause"}</button>
    {#if consoleUi.place === "min" && consoleUi.chip}<button type="button" class="btn sm quiet" id="console-min" title={`Open the console (${keyLabel("⌘J")})`} aria-label={`Open ${consoleUi.chip}`} onclick={() => setPlace("open")}><span class="glyph" aria-hidden="true">✦</span><span class="cm-w"> {consoleUi.chip}</span></button>{/if}
    {#if gear}<button type="button" class="btn sm quiet" id="hd-gear" aria-haspopup="menu" title="Settings (g s) and Send feedback" aria-label="Settings and feedback" onclick={(e) => app()?.menu(e.currentTarget, [
        { label: "Settings", title: "Settings (g s)", run: () => { location.hash = "#/settings"; } },
        { label: "Send feedback", title: "A bug, an idea or a question, as an issue on Kranto's GitHub, from you", run: () => openFeedback() }])}>⚙</button>
    {:else}<button class="btn sm quiet" id="hd-feedback" type="button" aria-label="Feedback" title="Send feedback: a bug, an idea or a question, as an issue on Kranto's GitHub, from you (the palette's Send feedback too)" onclick={() => openFeedback()}><span class="fb-w">Feedback</span><span class="fb-i" aria-hidden="true"><Icon name="chat" /></span></button>{/if}
    <button class="btn sm quiet" id="theme" type="button" title={`Theme: ${theme}. Click for ${other} (also under Settings › Appearance).`} aria-label={`Theme: ${theme}; switch to ${other}`} onclick={toggleTheme}>◐</button>
  </div>
{:else}
  <a class="brand" href="#/home">Kranto</a>
{/if}

<style>
  /* Feedback is its word on a wide screen and the chat glyph on a phone, beside ⚙ and ◐ */
  .fb-i { display: none; }
  /* the minimized console, a top-bar item in the bar's own row; ✦ alone on a phone */
  #console-min .glyph { color: var(--violet); }
  /* the doors: four words beside the brand, the current one in the text colour and bold */
  .hd-doors { display: flex; gap: 2px; margin: 0 10px 0 6px; flex: none; }
  .hd-doors a { padding: 4px 9px; border-radius: 6px; font-size: 13.5px; font-weight: 600; color: var(--muted); white-space: nowrap; }
  .hd-doors a:hover { color: var(--text); background: var(--subtle); text-decoration: none; }
  .hd-doors a[aria-current="page"] { color: var(--text); background: var(--subtle); }
  .hd-needs { flex: none; margin: 0 8px; padding: 3px 8px; border-radius: 6px; font-size: 13px; font-weight: 600; color: var(--text); white-space: nowrap; }
  .hd-needs .n { display: inline-block; min-width: 1.4em; padding: 0 5px; margin-left: 2px; border-radius: 9px; background: var(--amber, var(--accent)); color: var(--bg); text-align: center; font-size: 12px; }
  .hd-needs:hover { background: var(--subtle); text-decoration: none; }
  /* on a phone the count is a dot on the wordmark (the home's one thing says what) */
  .needs-dot { display: none; width: 7px; height: 7px; border-radius: 50%; background: var(--amber, var(--accent)); margin-left: 3px; align-self: flex-start; }
  @media (max-width: 759px) {
    /* on a phone the doors are the bar at the bottom, with ✦; the top bar keeps Kranto, the search,
       the state word and ⚙ */
    .hd-doors { display: none; }
    .hd-needs { display: none; }
    .needs-dot { display: inline-block; }
    :global(body.doors) #pause, :global(body.doors) #theme { display: none; }
    /* the console is ✦ in the bar of doors at the foot: not twice */
    :global(body.doors) #console-min { display: none; }
    .fb-w, .cm-w { display: none; }
    .fb-i { display: inline-flex; }
    /* the lanes' words end at their own edge, never under Pause */
    .lanes { overflow: hidden; }
  }
</style>
