<script lang="ts">
  // The console: your own Claude Code (or Codex) as it runs in a terminal, docked on the
  // right, mounted once by App.svelte outside the routed panes: a hash change never touches it,
  // its screen, scroll and connection stay. A reload reattaches to the running process (the
  // server replays its screen); Kranto's restart resumes the conversation. No persona: the head
  // says the assistant's own name and model. Collapsed it is a rail; minimized, a top-bar item;
  // on a phone a sheet. ctrl+] gives the keys back to the page; ⌘J (ctrl+J) brings them here.
  import { onDestroy, onMount, tick } from "svelte";
  import * as C from "./console.svelte";
  import { consoleUi, setPlace } from "./console.svelte";
  import { socketUrl, TermSocket } from "./socket";
  import { confirmThen } from "../ui/dialog.svelte";
  import PhoneSheet from "./PhoneSheet.svelte";
  import { newestTopic, starters, type Starter } from "./starters";
  import { Held, isReply, visibleText } from "./firstrun";
  import { parse } from "../lib/router";
  import { peek } from "../lib/reads.svelte";
  import { app, ui } from "../lib/shell.svelte";
  import { HOME_API, type HomeAnswer } from "../features/home";
  import { keyLabel } from "../lib/keys";

  // off: this server serves no terminal (the page's own test server): the panel is not drawn at all
  type Phase = "loading" | "off" | "none" | "starting" | "running" | "ended";
  let phase = $state<Phase>("loading");
  let st = $state<C.ConsoleState | null>(null);
  let error = $state("");
  let menu = $state(false);
  let full = $state(false);
  let screenEl = $state<HTMLDivElement>();
  let headEl = $state<HTMLElement>();

  let term: import("@xterm/xterm").Terminal | null = null;
  let fit: import("@xterm/addon-fit").FitAddon | null = null;
  let sock: TermSocket | null = null;
  let ro: ResizeObserver | null = null;
  let poll: ReturnType<typeof setInterval> | null = null;

  const harness = $derived(consoleUi.harness ?? st?.harness ?? null);
  const info = $derived(st?.harnesses.find((h) => h.id === harness) ?? null);
  const conv = $derived(harness ? (st?.conversations[harness] ?? null) : null);
  const model = $derived(harness ? (st?.settings.model[harness] ?? "") : "");
  const cost = $derived(
    !info ? "" : !info.extras ? "spend not reported" : conv ? `$${(conv.usd || 0).toFixed(2)} this conversation` : "",
  );

  // a phone: read and approve (PhoneSheet), not a terminal, unless the owner opens it full screen
  let phone = $state(typeof matchMedia === "function" && matchMedia(`(max-width: ${C.PHONE_MAX - 1}px)`).matches);
  // the three starters: shown while the conversation is empty (none yet, or a new one
  // nobody has typed in); a click types its sentence and sends it, starting the session if needed
  let blank = $state(false);
  let pending: string | null = null;
  let quietT: ReturnType<typeof setTimeout> | null = null;
  // the assistant's own first-run prompt (trust Kranto's folder, sign in): one line above the
  // starters, and a starter's sentence waits until the prompt is gone
  let firstRun = $state<string | null>(null);
  const held = new Held((s) => sock?.input(s));
  const list = $derived.by((): Starter[] => {
    void ui.drawn;
    const r = parse();
    const host = (app()?.host() || null) as { topics?: { id: number; name: string }[] } | null;
    const home = peek<HomeAnswer>(HOME_API)?.data;
    return starters({ path: r.path, sel: r.sel, topics: host?.topics || [], newest: newestTopic(home?.briefs) });
  });
  /** a starter: typed and sent, now if the session runs, else once it has started and gone quiet */
  function ask(s: Starter): void {
    if (phase === "running" && sock) {
      // behind a first-run prompt the sentence waits (the prompt is the person's to answer)
      if (held.ask(s.text)) blank = false;
      term?.focus();
      return;
    }
    blank = false;
    pending = s.text;
    endedByYou = false;
    openFailed = false;
    void start();
  }
  /** the session's screen went quiet after starting: the assistant waits at its prompt */
  function sendPending(): void {
    if (!sock) return;
    if (pending) {
      held.hold(pending);
      pending = null;
    }
    if (held.quiet()) blank = false;
  }
  /** what the screen now shows: a first-run prompt holds the starters' sentence */
  function readScreen(): void {
    if (!term) return;
    const was = firstRun;
    firstRun = held.screen(visibleText(term));
    if (firstRun) blank = true;          // the starters stay, with the line above them
    else if (was && held.text) {
      if (quietT) clearTimeout(quietT);
      quietT = setTimeout(sendPending, 1200);
    }
  }

  /** setup is not done yet: the console stays on its rail and starts nothing,
   * so Claude Code's trust prompt is not the first thing a stranger reads; a press still opens it */
  // (boot reads /api/setup once and says so: no request of the console's own)
  async function setupPending(): Promise<boolean> {
    return C.setupWait.v && !C.pressed.v;
  }

  async function load(): Promise<void> {
    try {
      st = await C.state();
    } catch (e) {
      error = (e as Error).message;
      return;
    }
    C.firstPlace(st.settings, undefined, await setupPending());
    consoleUi.served = st.socket !== false;
    if (st.socket === false) phase = "off";
    else if (!st.harness) phase = "none";
    else if (phase === "loading") phase = "ended";
  }

  async function ensureTerm(): Promise<void> {
    if (term) return;
    const [{ Terminal }, { FitAddon }] = await Promise.all([
      import("@xterm/xterm"),
      import("@xterm/addon-fit"),
      import("@xterm/xterm/css/xterm.css"),
    ]);
    const css = getComputedStyle(document.body);
    const v = (n: string, d: string) => css.getPropertyValue(n).trim() || d;
    term = new Terminal({
      cursorBlink: true,
      fontFamily: v("--mono", "ui-monospace, monospace"),
      fontSize: 13,
      scrollback: 5000,
      theme: { background: v("--term-bg", "#0d1117"), foreground: v("--term-fg", "#e6edf3") },
      minimumContrastRatio: 4.5,
    });
    fit = new FitAddon();
    term.loadAddon(fit);
    await tick();
    term.open(screenEl!);
    term.attachCustomKeyEventHandler((e) => {
      if (e.type === "keydown" && e.ctrlKey && e.key === "]") {
        term?.blur();
        headEl?.focus();
        return false;
      }
      // ⌘J is the page's (lib/keyboard.ts): it never reaches the assistant as a newline
      if ((e.metaKey || e.ctrlKey) && !e.altKey && e.key.toLowerCase() === "j") return false;
      return true;
    });
    term.onData((d) => {
      // the owner typed: the starters give way to the conversation; the terminal's own answers to
      // the program's queries (a cursor position, its attributes) are not typing
      if (!isReply(d)) blank = false;
      sock?.input(d);
    });
    ro = new ResizeObserver(() => resize());
    ro.observe(screenEl!);
  }

  function resize(): void {
    if (!term || !fit || !screenEl || !screenEl.offsetParent) return;
    try {
      fit.fit();
    } catch {
      return;
    }
    sock?.resize(term.cols, term.rows);
  }

  async function start(h: string | null = harness): Promise<void> {
    if (!h) return;
    error = "";
    // a session with no conversation behind it starts empty: the starters stand above its prompt
    if (!(st?.conversations[h] ?? null)) blank = !pending;
    phase = "starting";
    await ensureTerm();
    resize();
    try {
      const s = await C.open(h, term!.cols, term!.rows);
      openFailed = false;
      consoleUi.harness = s.harness;
      connect(s.tid, s.ticket);
    } catch (e) {
      // the panel does not start it again by itself: your press does (Start, ⌘J)
      openFailed = true;
      error = (e as Error).message;
      phase = "ended";
    }
  }

  function connect(tid: string, ticket: string): void {
    sock?.close();
    term!.reset();
    sock = new TermSocket(socketUrl(tid, ticket), (ev) => {
      if (ev.kind === "data") {
        term?.write(ev.bytes, readScreen);
        if (pending) {
          if (quietT) clearTimeout(quietT);
          quietT = setTimeout(sendPending, 1200);
        }
      }
      else if (ev.kind === "dropped") void start();
      else if (ev.kind === "exit") ended();
      else if (phase === "running") {
        error = `The connection closed: ${ev.reason}`;
        ended();
      }
    });
    sock.open();
    phase = "running";
    setTimeout(() => {
      resize();
      if (consoleUi.place === "open") term?.focus();
    }, 50);
  }

  function ended(): void {
    sock?.close();
    sock = null;
    phase = "ended";
    void load();
  }

  async function pickHarness(e: Event): Promise<void> {
    const h = (e.target as HTMLSelectElement).value;
    if (h === harness) return;
    try {
      await C.save({ harness: h as "claude" | "codex" });
    } catch (err) {
      error = (err as Error).message;
    }
    consoleUi.harness = h;
    await load();
    await start(h);
  }

  async function pickModel(e: Event): Promise<void> {
    const m = (e.target as HTMLSelectElement).value;
    if (!harness) return;
    try {
      st = await C.save({ model: { [harness]: m || null } as unknown as Record<string, string> });
    } catch (err) {
      error = (err as Error).message;
      return;
    }
    // the running conversation takes it at once: the harness's own command
    if (m && phase === "running") sock?.input(`/model ${m}\r`);
  }

  async function newConversation(): Promise<void> {
    menu = false;
    if (!harness) return;
    try {
      await C.fresh(harness);
      blank = true;
    } catch (e) {
      error = (e as Error).message;
    }
    term?.focus();
  }

  // End this session: the session ends and a fresh one starts here at once, a clean
  // prompt; the one that ended stays under ⋯ › Previous sessions. Minimize (–) only hides the
  // panel: nothing ends.
  function endSession(): void {
    menu = false;
    if (!harness) return;
    confirmThen(
      "End this session?",
      [`${info?.name ?? "The assistant"} stops, and a new conversation starts here with a clean prompt.`, "This conversation is kept: ⋯ › Previous sessions resumes it."],
      "End and start fresh",
      () => void endFresh(),
    );
  }
  async function endFresh(): Promise<void> {
    const h = harness;
    if (!h) return;
    sock?.close();
    sock = null;
    try {
      await C.end(h, true);
    } catch (e) {
      error = (e as Error).message;
      phase = "ended";
      await load();
      return;
    }
    term?.reset();
    term?.clear();
    endedByYou = false;
    openFailed = false;
    await load();
    await start(h);
    blank = !pending;
  }
  async function resumePrevious(session: string): Promise<void> {
    menu = false;
    prevOpen = false;
    const h = harness;
    if (!h) return;
    sock?.close();
    sock = null;
    try {
      await C.resume(h, session);
    } catch (e) {
      error = (e as Error).message;
      await load();
      return;
    }
    term?.reset();
    endedByYou = false;
    openFailed = false;
    await load();
    await start(h);
  }
  let prevOpen = $state(false);
  const previous = $derived(conv?.previous ?? []);
  const prevWords = (p: C.PreviousSession): string => {
    const at = p.ended ? new Date(p.ended * 1000) : null;
    const when = at ? at.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "earlier";
    return `Ended ${when}` + (info?.extras && p.usd ? ` · $${p.usd.toFixed(2)}` : "");
  };

  // the width: dragged on the handle, kept per browser, double-click resets, arrows step it
  let width = $state<number | null>(null);
  const classic = (): boolean => document.body.classList.contains("classic");
  function setWidth(w: number | null, keep = true): void {
    width = w == null ? null : C.clampWidth(w, innerWidth, classic());
    C.applyWidth(width);
    if (keep) C.saveWidth(width);
    setTimeout(resize, 30);
  }
  function drag(e: PointerEvent): void {
    if (e.button !== 0) return;
    e.preventDefault();
    const grip = e.currentTarget as HTMLElement;
    grip.setPointerCapture?.(e.pointerId);
    const move = (m: PointerEvent) => setWidth(innerWidth - m.clientX, false);
    const up = () => {
      grip.removeEventListener("pointermove", move);
      grip.removeEventListener("pointerup", up);
      C.saveWidth(width);
    };
    grip.addEventListener("pointermove", move);
    grip.addEventListener("pointerup", up);
  }
  function gripKey(e: KeyboardEvent): void {
    const step = e.shiftKey ? 64 : 16, now = width ?? C.WIDTH_DEFAULT;
    if (e.key === "ArrowLeft") setWidth(now + step);
    else if (e.key === "ArrowRight") setWidth(now - step);
    else if (e.key === "Home") setWidth(C.WIDTH_MIN);
    else if (e.key === "End") setWidth(C.widthMax(innerWidth, classic()));
    else if (e.key === "Enter" || e.key === "Escape") setWidth(null);
    else return;
    e.preventDefault();
  }
  onMount(() => {
    const kept = C.loadWidth();
    if (kept != null) setWidth(kept, false);
    const fitWin = () => { if (width != null) setWidth(width, false); };
    addEventListener("resize", fitWin);
    return () => removeEventListener("resize", fitWin);
  });

  // full screen: esc leaves it, as ? keys says, unless the keys are in the terminal (esc is
  // the assistant's there: ctrl+] gives them back, then esc); the head's ✕ is the visible way out
  onMount(() => {
    const esc = (e: KeyboardEvent) => {
      if (!full || e.key !== "Escape" || C.inConsole(e.target)) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      full = false;
    };
    addEventListener("keydown", esc, true);
    return () => removeEventListener("keydown", esc, true);
  });

  $effect(() => {
    const shown = phase !== "loading" && phase !== "off";
    document.body.classList.toggle("con-open", consoleUi.place === "open" && shown);
    document.body.classList.toggle("con-rail", consoleUi.place === "rail" && shown);
    document.body.classList.toggle("con-full", full);
  });

  // Restart now (Settings › Assistant): end this session and start it again, resumed, so it
  // takes what was saved (whose configuration, the permission mode, another assistant)
  let restarted = 0;
  $effect(() => {
    const r = consoleUi.restart;
    if (r.n === restarted) return;
    restarted = r.n;
    void (async () => {
      const was = harness;
      const running = phase === "running";
      sock?.close();
      sock = null;
      if (was && running) {
        try {
          await C.end(was);
        } catch {
          /* it may have ended already: it starts all the same */
        }
      }
      endedByYou = false;
      openFailed = false;
      if (r.harness) consoleUi.harness = r.harness;
      await load();
      await start(r.harness ?? was);
    })();
  });

  // ⌘J: open (it reattaches if it had ended) and take the keys
  let seen = 0;
  $effect(() => {
    const n = consoleUi.focusN;
    if (n === seen) return;
    seen = n;
    if (phase === "ended" && harness) void start();
    else setTimeout(() => term?.focus(), 30);
  });
  // opened from the rail or the top bar: it starts (resumed), unless you ended it yourself or
  // its last start failed (else a failed start would start it again, at once, forever)
  let endedByYou = false;
  let openFailed = false;
  let mounted = $state(false);
  $effect(() => {
    if (consoleUi.place !== "open" || !mounted) return;
    setTimeout(resize, 30);
    // a phone opens the read-and-approve sheet: no terminal starts until full screen is asked for
    if (phone && !full) return;
    if (phase === "ended" && !sock && !endedByYou && !openFailed && harness) void start();
  });
  onMount(() => {
    if (typeof matchMedia !== "function") return;
    const mq = matchMedia(`(max-width: ${C.PHONE_MAX - 1}px)`);
    const on = () => (phone = mq.matches);
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  });

  // the minimized chip is the top bar's (Header.svelte), in its row
  $effect(() => {
    consoleUi.chip = phase !== "loading" && phase !== "off" ? info?.name ?? "Console" : null;
  });

  onMount(async () => {
    C.loadPlace();
    // boot says whether setup is done (F-11); a page without the server goes on after a moment
    await Promise.race([C.booted, new Promise((r) => setTimeout(r, 1500))]);
    await load();
    mounted = true;
    poll = setInterval(() => void load(), 10000);
  });

  onDestroy(() => {
    if (poll) clearInterval(poll);
    ro?.disconnect();
    sock?.close();
    term?.dispose();
  });
</script>

{#snippet startersBox()}
  {#if firstRun}<p class="con-firstrun" id="console-firstrun" role="status">{firstRun}</p>{/if}
  <ul class="con-starters" id="console-starters" aria-label="Ask">
    {#each list as s (s.label)}<li><button type="button" class="con-starter" data-text={s.text} onclick={() => ask(s)}><span class="cs-q">{s.label}</span><span class="cs-says">{s.says}</span></button></li>{/each}
  </ul>
{/snippet}

<aside id="console" class="console" aria-label="Console" hidden={consoleUi.place === "min" || phase === "loading" || phase === "off"}
  class:rail={consoleUi.place === "rail"} class:sheet={phone && !full}>
  {#if consoleUi.place === "rail"}
    <button type="button" class="con-rail" title={`Open the console (${keyLabel("⌘J")})`} aria-label="Open the console"
      onclick={() => setPlace("open")}>
      <span class="glyph" aria-hidden="true">✦</span>
      <span class="vert">{info?.name ?? "Console"}</span>
    </button>
  {/if}
  {#if consoleUi.place === "open" && !full}
    <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
    <div class="con-grip" id="console-grip" role="separator" aria-orientation="vertical" tabindex="0"
      aria-label="Console width: drag, or the arrow keys; double-click or Enter resets"
      title="Drag to widen or narrow the console · double-click resets"
      aria-valuemin={C.WIDTH_MIN} aria-valuemax={C.widthMax(innerWidth, classic())} aria-valuenow={width ?? C.WIDTH_DEFAULT}
      onpointerdown={drag} ondblclick={() => setWidth(null)} onkeydown={gripKey}></div>
  {/if}
  <div class="con-body" hidden={consoleUi.place === "rail"}>
    <header class="con-head" bind:this={headEl} tabindex="-1">
      {#if st && st.harnesses.length}
        <select aria-label="Assistant" value={harness ?? ""} onchange={pickHarness}>
          <!-- with none installed the select said nothing at all (3, G14: "blank") -->
          {#if !harness}<option value="" disabled>No assistant installed</option>{/if}
          {#each st.harnesses as h (h.id)}
            <option value={h.id} disabled={!h.installed}>{h.name}{h.installed ? "" : " (not installed)"}</option>
          {/each}
        </select>
        {#if info && info.models.length}
          <select aria-label="Model" value={model} onchange={pickModel}>
            <option value="">default model</option>
            {#each info.models as m (m.id)}<option value={m.id}>{m.name}</option>{/each}
          </select>
        {/if}
      {/if}
      <span class="con-words muted small">
        {#if cost}<span>{cost}</span>{/if}
        {#if st?.head}<span title={st.head.mode}>· {st.settings.permission === "auto" ? "auto mode" : st.settings.permission === "ask" ? "asks first" : "accepts edits"}</span>{/if}
      </span>
      <span class="con-acts">
        {#if full}<button type="button" class="btn sm" id="console-unfull" title="Back to the side (esc)" onclick={() => (full = false)}>✕ Exit full screen</button>{/if}
        <button type="button" class="btn sm quiet" aria-haspopup="menu" aria-expanded={menu} title="More"
          onclick={() => (menu = !menu)}>⋯</button>
        <button type="button" class="btn sm quiet" title="Collapse to the rail" aria-label="Collapse"
          onclick={() => setPlace("rail")}>›</button>
        <button type="button" class="btn sm quiet" title="Minimize to the top bar" aria-label="Minimize"
          onclick={() => setPlace("min")}>–</button>
      </span>
      {#if menu}
        <ul class="con-menu" role="menu">
          <li role="none"><button type="button" role="menuitem" disabled={phase !== "running"} onclick={newConversation}>New conversation</button></li>
          <li role="none"><button type="button" role="menuitem" id="console-end" disabled={phase !== "running"} title="Ends this session and starts a fresh one here; this one stays under Previous sessions" onclick={endSession}>End this session</button></li>
          <li role="none"><button type="button" role="menuitem" id="console-previous" aria-expanded={prevOpen} disabled={!previous.length} title={previous.length ? "Resume a session you ended" : "No ended sessions yet"} onclick={() => (prevOpen = !prevOpen)}>{`Previous sessions${previous.length ? ` (${previous.length})` : ""}`}</button></li>
          {#if prevOpen}
            {#each previous as p (p.session)}<li role="none" class="con-prev"><button type="button" role="menuitem" data-session={p.session} onclick={() => void resumePrevious(p.session)}>{prevWords(p)}</button></li>{/each}
          {/if}
          <li role="none"><button type="button" role="menuitem" onclick={() => { menu = false; full = !full; }}>{full ? "Back to the side" : "Open full screen"}</button></li>
          <li role="none"><button type="button" role="menuitem" onclick={() => { menu = false; location.hash = "#/settings/assistant"; }}>Settings › Assistant</button></li>
          {#if st?.settings.config === "own"}
            <li role="none" class="con-outside" id="console-outside"><span class="muted small">{st.outside?.length ? `Also loaded from your configuration: ${st.outside.join(", ")}` : "No other MCP servers in your configuration"}</span></li>
          {/if}
        </ul>
      {/if}
    </header>
    {#if st?.head?.note}<p class="con-note muted small">{st.head.note}</p>{/if}
    {#if phone && !full}
      <PhoneSheet name={info?.name ?? "The assistant"} onfull={() => { full = true; endedByYou = false; if (phase === "ended" && harness) void start(); }} />
    {:else}
      {#if phone}<p class="con-phone muted small">On a phone you can read and approve · <button type="button" class="linkish" onclick={() => (full = false)}>Back</button></p>{/if}
      {#if phase === "none"}
        <div class="con-empty">
          <p>{st?.why ?? "No assistant is installed on Kranto's PATH."}</p>
          <p class="muted small">Install Claude Code (<code>curl -fsSL https://claude.ai/install.sh | bash</code>) or Codex, then open this panel again.</p>
        </div>
      {:else if phase === "ended"}
        <div class="con-empty">
          {#if conv?.state === "ended"}<p class="muted small">{conv.words}</p>{/if}
          <!-- the screen is empty: the starters lead (a click starts or resumes, then asks), and
               Start or Resume is a plain button beside them (no primary here) -->
          {@render startersBox()}
          <button type="button" class="btn" onclick={() => { endedByYou = false; void start(); }}>{conv ? `Resume ${info?.name ?? ""}` : `Start ${info?.name ?? ""}`}</button>
        </div>
      {:else if phase === "running" && blank}
        <div class="con-starters-run">{@render startersBox()}</div>
      {/if}
      {#if error}<p class="con-error small" role="alert">{error}</p>{/if}
    {/if}
    <div class="screen" bind:this={screenEl} hidden={phase === "none" || (phone && !full)}></div>
  </div>
</aside>

<style>
  .console { position: fixed; top: 0; right: 0; bottom: 0; width: var(--conw, 380px); z-index: 30;
    display: flex; flex-direction: column; background: var(--term-bg); border-left: 1px solid var(--border); }
  .console[hidden] { display: none; }
  .console.rail { width: 36px; background: var(--head); }
  .con-rail { all: unset; cursor: pointer; display: flex; flex-direction: column; align-items: center; gap: 10px;
    padding: 12px 0; width: 36px; height: 100%; color: var(--text); }
  .con-rail:focus-visible { outline: 2px solid var(--focus); outline-offset: -2px; }
  .con-rail .vert { writing-mode: vertical-rl; font-size: 12px; color: var(--muted); }
  .glyph { color: var(--violet); }
  .con-body { display: flex; flex-direction: column; min-height: 0; flex: 1; }
  .con-grip { position: absolute; left: -3px; top: 0; bottom: 0; width: 6px; cursor: col-resize; z-index: 32; }
  .con-grip:hover, .con-grip:focus-visible { background: var(--focus); outline: none; opacity: 0.6; }
  .con-body[hidden], .screen[hidden] { display: none; }
  .con-head { position: relative; display: flex; align-items: center; gap: 6px; height: 40px; padding: 0 8px;
    background: var(--head); border-bottom: 1px solid var(--border); outline: none; flex: none; }
  /* the page's own colours, either theme (3, G14: white on white in light mode) */
  .con-head select { font-size: 12px; max-width: 132px; color: var(--text); background: var(--bg); border: 1px solid var(--border); border-radius: 6px; }
  .con-words { flex: 1; min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  .con-acts { display: flex; gap: 2px; }
  .con-menu { position: absolute; right: 8px; top: 38px; z-index: 31; list-style: none; margin: 0; padding: 4px 0;
    background: var(--bg); border: 1px solid var(--border); border-radius: 6px; min-width: 190px; }
  .con-menu button { all: unset; display: block; padding: 6px 12px; cursor: pointer; font-size: 13px; color: var(--text); }
  .con-menu button:disabled { color: var(--muted); cursor: default; }
  .con-menu .con-prev button { padding-left: 24px; font-size: 12px; }
  .con-menu button:hover:not(:disabled), .con-menu :focus-visible { background: var(--subtle); }
  .con-note, .con-phone { margin: 0; padding: 4px 10px; background: var(--head); border-bottom: 1px solid var(--border); }
  .con-phone { display: none; }
  .con-empty { padding: 24px 16px; color: var(--term-fg); }
  /* the three starters: a question in the terminal's own colours, its one muted line under it */
  .con-starters { list-style: none; margin: 0 0 14px; padding: 0; display: flex; flex-direction: column; gap: 8px; }
  .con-starters-run { padding: 10px 12px 4px; background: var(--term-bg); flex: none; }
  .con-starter { all: unset; box-sizing: border-box; width: 100%; cursor: pointer; display: flex; flex-direction: column; gap: 2px;
    padding: 8px 10px; border: 1px solid color-mix(in srgb, var(--term-fg) 22%, transparent); border-radius: 8px; color: var(--term-fg); }
  .con-starter:hover, .con-starter:focus-visible { border-color: var(--violet); outline: none; }
  .con-firstrun { margin: 0 0 8px; font-size: 13px; color: var(--term-fg); }
  .cs-q { font-weight: 600; font-size: 13px; }
  .cs-says { font-size: 12px; color: color-mix(in srgb, var(--term-fg) 70%, transparent); }
  .con-empty code { font-size: 12px; }
  .con-error { margin: 0; padding: 6px 10px; color: var(--red); background: var(--head); }
  .screen { flex: 1; min-height: 0; padding: 4px 0 0 6px; }
  .linkish { all: unset; cursor: pointer; text-decoration: underline; }
  :global(body.con-open #app) { margin-right: var(--conw, 380px); }
  :global(body.con-rail #app) { margin-right: 36px; }
  /* New's sheet opens beside the console, never under it */
  :global(body.con-open.doors:not(.classic).show-detail #detail) { right: var(--conw, 380px); }
  :global(body.con-rail.doors:not(.classic).show-detail #detail) { right: 36px; }
  :global(body.con-full) .console { width: 100vw; }
  /* Classic with the console docked (at 1400 px the list keeps 224 + 6 + 784 and
     the console 380; a real install's list fell to 320 px, Needs you's titles to "Add …"): while
     no object is open, the empty detail column gives its width to the list */
  @media (min-width: 1180px) {
    :global(body.classic.con-open:not(.show-detail):not(.focus):not(.stage) #app) {
      grid-template-columns: var(--nav-w, 224px) 6px minmax(320px, 1fr); grid-template-areas: "top top top" "nav sn list" "bar bar bar"; }
    :global(body.classic.con-open:not(.show-detail):not(.focus):not(.stage) #detail),
    :global(body.classic.con-open:not(.show-detail):not(.focus):not(.stage) #split-detail) { display: none; }
  }
  @media (max-width: 759px) {
    .con-grip { display: none; }               /* a sheet on a phone: no width to drag */
    /* over the preview's strip (z 40), which covered its text (14, Gemini 19) */
    .console { top: auto; left: 0; width: auto; height: 70vh; border-left: 0; border-top: 1px solid var(--border); z-index: 45; }
    .console.rail { height: 44px; width: auto; }
    .con-rail { flex-direction: row; width: 100%; height: 44px; padding: 0 16px; }
    .con-rail .vert { writing-mode: horizontal-tb; }
    .con-phone { display: block; }
    /* the read-and-approve sheet: as tall as what it says, over the bar of doors, never a dock */
    .console.sheet { height: auto; max-height: 70vh; bottom: calc(56px + env(safe-area-inset-bottom)); background: var(--bg);
      border-radius: 12px 12px 0 0; border: 1px solid var(--border); border-bottom: 0; }
    .console.sheet .con-head select, .console.sheet .con-words { display: none; }
    .console.sheet .con-head::before { content: "✦ Console"; flex: 1; font-weight: 600; font-size: 13px; color: var(--text); }
    :global(body.con-open #app), :global(body.con-rail #app) { margin-right: 0; }
    :global(body.con-full) .console { height: 100dvh; }
  }
</style>
