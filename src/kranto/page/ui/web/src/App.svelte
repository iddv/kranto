<script lang="ts">
  // The frame (WORKSPACE.md 1;): five regions, #app's children in a CSS grid (kranto.css):
  // the top bar, the navigator, the list pane, the detail pane and the status bar, with the two
  // splitters between the panes. The shell draws the chrome; every page draws itself into #rows
  // and #dscroll (lib/pages.svelte.ts); #dlg is the one dialog (DialogHost); #term holds Open in
  // Claude Code; the toast is at the foot. The ids, roles and labels are
  // the DOM contract the browser tests and the click stories use (ui/web/CONTRACT.md).
  import { onMount } from "svelte";
  import Header from "./shell/Header.svelte";
  import TabBar from "./shell/TabBar.svelte";
  import ListHead from "./shell/ListHead.svelte";
  import Nav from "./shell/Nav.svelte";
  import Palette from "./shell/Palette.svelte";
  import Splitter from "./shell/Splitter.svelte";
  import StatusBar from "./shell/StatusBar.svelte";
  import PreviewStrip from "./shell/PreviewStrip.svelte";
  import { onKeydown } from "./lib/keyboard";
  import { live } from "./lib/live";
  import { markLoaded } from "./lib/mark";
  import { frame, iconsNow, LAYOUT, app, navDrawer, splitAria, ui } from "./lib/shell.svelte";
  import TerminalPanel from "./term/TerminalPanel.svelte";
  import TermSplit, { loadTermw } from "./term/TermSplit.svelte";
  import Console from "./term/Console.svelte";
  import { consoleUi, here as consoleHere } from "./term/console.svelte";
  import { reflect } from "./term/reflect.svelte";
  import { afkStale } from "./lib/app/data";
  import DialogHost from "./ui/DialogHost.svelte";
  import Details from "./ui/Details.svelte";
  import PreparedLine from "./ui/PreparedLine.svelte";
  import PressLine from "./shell/PressLine.svelte";
  import PreparedToast from "./ui/PreparedToast.svelte";
  import { noticePrepared } from "./ui/prepared.svelte";
  import Toast from "./ui/Toast.svelte";
  import { closeTerm, loadTermStatus, termUi } from "./term/state.svelte";
  import { href, parse } from "./lib/router";
  import { noteError } from "./ui/feedback";
  import { openFeedback, sendError } from "./ui/sendFeedback";

  onMount(() => {
    markLoaded(document.documentElement);
    const L = app();
    if (!L) return;
    L.initFrame();
    splitAria();
    loadTermw();
    // the console's status line says the page you are on (never sent to the model)
    let hereT: ReturnType<typeof setTimeout> | null = null;
    const hash = () => {
      ui.navOpen = false; // the drawer closes on a choice
      L.onHash();
      feedbackAsked();
      if (hereT) clearTimeout(hereT);
      if (consoleUi.served) hereT = setTimeout(() => void consoleHere(location.hash, document.title).catch(() => undefined), 800);
    };
    // Feedback (FB): the page's own errors are among the last few its details name, and
    // ?feedback=1 on any address (the help page's Send feedback) opens the sheet there
    const oops = (e: ErrorEvent) => noteError(e.message || "a script error");
    const rejected = (e: PromiseRejectionEvent) => noteError((e.reason && (e.reason as Error).message) || String(e.reason || "a promise was rejected"));
    addEventListener("error", oops);
    addEventListener("unhandledrejection", rejected);
    const resize = () => {
      const was = iconsNow();
      LAYOUT.apply();
      splitAria();
      if (iconsNow() !== was) frame();
    };
    addEventListener("hashchange", hash);
    addEventListener("keydown", onKeydown);
    addEventListener("keydown", trap);
    addEventListener("resize", resize);
    let feed: { stop(): void } | null = null;
    void L.boot().then((ok) => {
      // what an assistant did is the server's to say: only where Kranto hosts the page
      const host = !!ui.facts?.header.host;
      // an item an assistant prepared, or one approved on another page: Needs you, its count and the
      // home read again at once, and the toast says it
      if (ok) feed = live(L, "api/stream", host ? () => reflect(undefined, noticePrepared).then((any) => {
        if (any) afkStale("/");
        return any;
      }) : undefined);
      void loadTermStatus().then((on) => on && L.render());
      feedbackAsked();
    });
    return () => {
      removeEventListener("error", oops);
      removeEventListener("unhandledrejection", rejected);
      removeEventListener("hashchange", hash);
      removeEventListener("keydown", onKeydown);
      removeEventListener("keydown", trap);
      removeEventListener("resize", resize);
      feed?.stop();
    };
  });
  $effect(() => {
    document.body.classList.toggle("nav-open", ui.navOpen);
  });
  $effect(() => {
    document.body.classList.toggle("term-open", !!termUi.subject);
  });
  // the doors' one sheet: opened by a press, the cursor goes into it (j and k
  // leave it on the list, the sheet following); closed, it goes back to the chosen row
  let wasSheet = false;
  $effect(() => {
    const open = ui.sheet;
    if (open === wasSheet) return;
    wasSheet = open;
    const L = app();
    if (open && !(L && L.stepping())) document.getElementById("dscroll")?.focus({ preventScroll: true });
    if (!open) {
      const row = document.querySelector<HTMLElement>("#rows li.row.sel a, #rows li.row.focus a");
      (row || document.getElementById("rows"))?.focus({ preventScroll: true });
    }
  });
  const FOCUSABLE = "a[href], button:not([disabled]), input:not([disabled]), select, textarea, summary";
  /** tab stays inside the open sheet: from its last control to its first, and back */
  function trap(e: KeyboardEvent): void {
    if (e.key !== "Tab" || !ui.sheet) return;
    const box = document.getElementById("detail")!;
    const all = [...box.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((x) => x.offsetParent !== null);
    if (!all.length) return;
    const first = all[0]!, last = all[all.length - 1]!, at = document.activeElement;
    if (!box.contains(at)) {
      e.preventDefault();
      first.focus();
    } else if (e.shiftKey && (at === first || at === document.getElementById("dscroll"))) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && at === last) {
      e.preventDefault();
      first.focus();
    }
  }
  /** ?feedback=1: the sheet, and the address without it (a reload does not open it again);
   * ?send_error=<id> (Kranto's error page's Send this error, RCA B3): the sheet with that error's report */
  function feedbackAsked(): void {
    const r = parse();
    const err = /^[0-9a-f]{8}$/.test(r.q.send_error || "") ? r.q.send_error! : null;
    if (r.q.feedback !== "1" && !err) return;
    const q = { ...r.q };
    delete q.feedback;
    delete q.send_error;
    history.replaceState(null, "", href(r.path.map(encodeURIComponent).join("/"), { ...q, sel: r.sel }));
    if (err) sendError(err, "A page Kranto could not answer");
    else openFeedback();
  }
  function skip(e: MouseEvent): void {
    e.preventDefault();
    document.getElementById("rows")?.focus();
  }
</script>

<a class="skip" href="#rows" onclick={skip}>Skip to the list</a>
<div id="app">
  <header class="hd" id="top"><Header /></header>
  <nav id="nav" aria-label="Sections"><Nav /></nav>
  <Splitter col="nav" />
  <main id="list" aria-label="List">
    <!-- The page's head (shell/PageHead.svelte) is the column's first child: lib/app/route.ts -->
    <ListHead />
    <div id="rows" tabindex="-1"><p class="empty">Loading…</p></div>
  </main>
  <Splitter col="detail" />
  <section id="detail" aria-label={ui.sheet ? ui.sheetTitle || "Detail" : "Detail"} role={ui.sheet ? "dialog" : null} aria-modal={ui.sheet ? "true" : null}>
    {#if ui.sheet}<button type="button" class="btn sm quiet" id="sheet-x" title="Close (esc)" aria-label="Close" onclick={() => app()?.closeSheet()}>✕</button>{/if}
    {#if ui.sheet}<div class="sheet-prepared"><PreparedLine inSheet /><PressLine /></div>{/if}
    <div id="dscroll" tabindex="-1"></div>
    <!-- Open in Claude Code: docked at the bottom (glance), the right split (focus) -->
    <div id="term" hidden={!termUi.subject}>
      <TermSplit />
      {#if termUi.subject}
        {#key termUi.n}
          <TerminalPanel subject={termUi.subject} title={termUi.title} onclose={closeTerm} />
        {/key}
      {/if}
    </div>
  </section>
  <footer id="bar"><StatusBar /></footer>
  <TabBar />
  <PreviewStrip />
</div>
<!-- the drawer's backdrop, for a pointer (esc closes the drawer from the keys) -->
<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
<div id="scrim" hidden={!ui.navOpen} onclick={() => navDrawer(false)}></div>
<!-- the doors' sheet over a dimmed page: a press on the page closes it (esc does from the keys) -->
<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
<div id="sheet-scrim" hidden={!ui.sheet} onclick={() => app()?.closeSheet()}></div>
<!-- the console: outside the routed panes, mounted once; a hash change never touches it -->
<Console />
<DialogHost />
<Details />
<Palette />
<Toast />
<PreparedToast />
