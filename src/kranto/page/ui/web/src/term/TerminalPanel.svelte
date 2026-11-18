<script lang="ts">
  // Open in Claude Code (src/kranto/page/term): the real Claude Code for one subject, in a terminal
  // in the page. Glance: docked at the bottom of the detail pane; focus: a right split. The
  // head says where it runs and what it may do; proposal cards (the session's asks to Kranto,
  // and hosts it wants to reach) wait above the terminal for Confirm or Dismiss. While the
  // terminal has the focus every key goes to it; ctrl+] gives the focus back to the page.
  import { onDestroy, onMount, tick } from "svelte";
  import * as T from "./api";
  import { socketUrl, TermSocket } from "./socket";

  let { subject, title = "", onclose }: {
    subject: T.Subject;
    title?: string;
    onclose?: () => void;
  } = $props();

  type Phase = "loading" | "unavailable" | "ready" | "starting" | "running" | "ended" | "full";
  let phase = $state<Phase>("loading");
  let listing = $state<T.Listing | null>(null);
  let session = $state<T.Session | null>(null);
  let error = $state("");
  let full = $state<T.Session[]>([]);
  let outside = $state<T.Outside | null>(null);
  let confirmEnd = $state(false);
  let screenEl = $state<HTMLDivElement>();
  let headEl = $state<HTMLElement>();
  let hasTerm = $state(false);

  // xterm.js, loaded on first use (its own chunk)
  let term: import("@xterm/xterm").Terminal | null = null;
  let fit: import("@xterm/addon-fit").FitAddon | null = null;
  let sock: TermSocket | null = null;
  let ro: ResizeObserver | null = null;
  let poll: ReturnType<typeof setInterval> | null = null;

  const words = $derived(
    !session
      ? ""
      : session.sandboxed === false
        ? "no sandbox on this machine"
        : "its own copy, asks before edits and commands",
  );
  const waiting = $derived((session?.proposals ?? []).filter((p) => p.status === "proposed"));
  const decided = $derived(
    (session?.proposals ?? []).filter((p) => p.status !== "proposed").slice(-2),
  );

  async function refresh(): Promise<void> {
    try {
      listing = await T.list();
    } catch (e) {
      error = String((e as Error).message ?? e);
      return;
    }
    const s = T.about(listing, subject);
    if (s) session = { ...s, ticket: session?.ticket };
    if (phase === "loading") {
      if (!listing.available || !listing.socket) phase = "unavailable";
      else phase = "ready";
    }
    if (phase === "running" && s && s.state !== "running") ended();
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
      // the terminal is dark in both themes, but the program draws its own colours: Claude Code in
      // its light theme draws near-black text, and ANSI black is near this background. xterm
      // lightens any colour under 4.5:1 against what it is drawn on (WCAG AA), so every line reads
      minimumContrastRatio: 4.5,
    });
    hasTerm = true;
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
      return true;
    });
    term.onData((d) => sock?.input(d));
    ro = new ResizeObserver(() => resize());
    ro.observe(screenEl!);
    resize();
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

  async function start(): Promise<void> {
    error = "";
    outside = null;
    phase = "starting";
    await ensureTerm();
    let s: T.Session;
    try {
      s = await T.open(subject, term!.cols, term!.rows);
    } catch (e) {
      const err = e as Error & { status?: number; sessions?: T.Session[] };
      if (err.status === 429) {
        full = err.sessions ?? [];
        phase = "full";
      } else {
        error = err.message;
        phase = "ready";
      }
      return;
    }
    session = s;
    connect(s.tid, s.ticket!);
  }

  function connect(tid: string, ticket: string): void {
    sock?.close();
    term!.reset();
    sock = new TermSocket(socketUrl(tid, ticket), (ev) => {
      if (ev.kind === "data") term?.write(ev.bytes);
      else if (ev.kind === "dropped") void start();      // fell behind: reattach
      else if (ev.kind === "exit") ended();
      else if (phase === "running") {
        error = `The terminal's connection closed: ${ev.reason}`;
        ended();
      }
    });
    sock.open();
    phase = "running";
    setTimeout(() => {
      resize();
      term?.focus();
    }, 50);
  }

  function ended(): void {
    sock?.close();
    sock = null;
    phase = "ended";
    void refresh();
  }

  async function endSession(): Promise<void> {
    if (!session) return;
    confirmEnd = false;
    sock?.close();
    sock = null;
    try {
      await T.end(session.tid);
    } catch (e) {
      error = (e as Error).message;
    }
    session = null;
    phase = "ready";
    term?.reset();
    await refresh();
  }

  async function continueOutside(): Promise<void> {
    if (!session) return;
    try {
      outside = await T.outside(session.tid);
      sock?.close();
      sock = null;
      phase = "ended";
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function answerCard(p: T.Proposal, confirm: boolean): Promise<void> {
    if (!session) return;
    try {
      await T.reply(session.tid, p.n, confirm);
    } catch (e) {
      error = (e as Error).message;
    }
    await refresh();
  }

  async function answerHost(host: string, allow: boolean): Promise<void> {
    if (!session) return;
    try {
      await T.net(session.tid, host, allow);
    } catch (e) {
      error = (e as Error).message;
    }
    await refresh();
  }

  async function endOther(tid: string): Promise<void> {
    await T.end(tid).catch(() => undefined);
    full = full.filter((s) => s.tid !== tid);
    if (!full.length) phase = "ready";
  }

  /** Use the API key: the owner's choice (term.allow_api_key), then the session starts */
  async function useApiKey(): Promise<void> {
    error = "";
    try {
      await T.useApiKey();
    } catch (e) {
      error = (e as Error).message;
      return;
    }
    phase = "loading";
    await refresh();
    if ((phase as Phase) === "ready") await start();
  }

  function copy(text: string): void {
    void navigator.clipboard?.writeText(text);
  }

  function fields(p: T.Proposal): string {
    return JSON.stringify(p.fields, null, 1);
  }

  onMount(async () => {
    await refresh();
    if (phase === "ready" && session?.state === "running") await start();
    poll = setInterval(() => void refresh(), 3000);
  });

  onDestroy(() => {
    if (poll) clearInterval(poll);
    ro?.disconnect();
    sock?.close();
    term?.dispose();
  });
</script>

<section class="term" aria-label="Open in Claude Code">
  <header class="term-head" tabindex="-1" bind:this={headEl}>
    <b>Claude Code</b>
    <span class="dim">· about {title || `${subject.kind} ${subject.id}`}</span>
    {#if words}<span class="dim">· {words}</span>{/if}
    {#if session?.on || (subject.kind === "sources" ? listing?.sources_on : listing?.on)}
      <span class="dim" id="term-on">· {session?.on || (subject.kind === "sources" ? listing?.sources_on : listing?.on)}</span>{/if}
    {#if session && session.usd}<span class="dim">· ${session.usd.toFixed(2)}</span>{/if}
    {#if phase === "running"}<span class="dim">· <kbd>Ctrl+]</kbd> back to the page</span>{/if}
    <span class="grow"></span>
    {#if session && phase !== "loading" && phase !== "unavailable"}
      <!-- an earlier session of this subject too, before it is opened again -->
      <a class="btn" id="term-trace" href={"#/sessions/" + encodeURIComponent(session.tid) + "/trace"}
        title="The conversation as a trace: its turns, tool calls and their output">Trace</a>
    {/if}
    {#if session && (phase === "running" || phase === "ended")}
      <button type="button" class="btn" onclick={continueOutside}>Continue outside</button>
      {#if confirmEnd}
        <span class="dim">End removes its copy{session.branch ? ` and ${session.branch}` : ""}
          unless a proposal uses it.</span>
        <button type="button" class="btn danger" onclick={endSession}>End it</button>
        <button type="button" class="btn" onclick={() => (confirmEnd = false)}>Keep</button>
      {:else}
        <button type="button" class="btn" onclick={() => (confirmEnd = true)}>End</button>
      {/if}
    {/if}
    {#if onclose}
      <button type="button" class="btn icon" aria-label="Close the panel (the session keeps running)"
        title="Close the panel (the session keeps running)" onclick={onclose}>×</button>
    {/if}
  </header>

  {#if session?.sandboxed === false}
    <p class="term-warn">bubblewrap does not work on this machine: this session runs without
      Kranto's sandbox, as Claude Code would in this folder.</p>
  {/if}
  {#if error}<p class="term-err" role="alert">{error}</p>{/if}
  {#if session?.refused}<p class="term-err" id="term-refused" role="alert">The Claude API refused
    this session's last request: {session.refused}</p>{/if}

  {#if session && (session.net.asked.length || waiting.length || decided.length)}
    <div class="term-cards">
      {#each session.net.asked as host (host)}
        <div class="term-card">
          <div><b>The session wants to reach {host}</b>
            <span class="dim">Kranto refused it; allow it for this session only?</span></div>
          <div class="acts">
            <button type="button" class="btn primary" onclick={() => answerHost(host, true)}>
              Allow {host}</button>
            <button type="button" class="btn" onclick={() => answerHost(host, false)}>Deny</button>
          </div>
        </div>
      {/each}
      {#each waiting as p (p.n)}
        <div class="term-card" class:warn={p.confirm_class}>
          <div><b>{p.title}</b>
            <span class="dim">({p.kind} on {p.subject.kind}
              {p.subject.id ?? ""})</span>
            {#if p.confirm_class}<span class="tag">can't be taken back</span>{/if}
          </div>
          {#if p.why}<blockquote class="why"><span class="dim">The session says:</span>
            {p.why}</blockquote>{/if}
          {#if Object.keys(p.fields).length}
            <pre class="fields">{fields(p)}</pre>
          {/if}
          <div class="acts">
            <button type="button" class="btn primary" onclick={() => answerCard(p, true)}>Confirm</button>
            <button type="button" class="btn" onclick={() => answerCard(p, false)}>Dismiss</button>
          </div>
        </div>
      {/each}
      {#each decided as p (p.n)}
        <div class="term-card done">
          <span><b>{p.title}</b>: {p.status}{p.result?.say ? `: ${p.result.say}` : ""}
            {p.result?.error ? `: ${p.result.error}` : ""}</span>
          {#if p.result?.url}<a href={p.result.url} target="_blank" rel="noopener">open</a>{/if}
        </div>
      {/each}
    </div>
  {/if}

  {#if outside}
    <div class="term-outside">
      <p><b>Continue in your own terminal.</b> The session has ended here; its conversation and
        its copy{outside.branch ? ` (${outside.branch})` : ""} are where these commands find
        them.</p>
      <p class="dim">Your own Claude Code, your own permissions, with Kranto's tools (reads and
        proposals) while Kranto runs:</p>
      <div class="cmd"><code>{outside.plain}</code>
        <button type="button" class="btn" onclick={() => copy(outside!.plain)}>Copy</button></div>
      <p class="dim">Or with exactly the page's limits:</p>
      <div class="cmd"><code>{outside.kranto}</code>
        <button type="button" class="btn" onclick={() => copy(outside!.kranto)}>Copy</button></div>
    </div>
  {/if}

  <div class="term-body">
    {#if phase === "loading"}
      <p class="dim pad">Loading…</p>
    {:else if phase === "unavailable"}
      <p class="pad">{listing && !listing.socket
        ? "Open in Claude Code needs Kranto itself (kranto up): this server has no terminal."
        : (listing?.why ?? "Open in Claude Code is not available here.")}</p>
      {#if listing?.socket && listing.ask === "api_key"}
        <p class="pad"><button type="button" class="btn" id="term-use-key" onclick={useApiKey}>Use the API key</button>
          <span class="dim">The choice is kept in your settings (term.allow_api_key).</span></p>
      {/if}
    {:else if phase === "full"}
      <div class="pad">
        <p>{full.length} sessions are open: end one first.</p>
        <ul>
          {#each full as s (s.tid)}
            <li>{s.title} <span class="dim">({s.subject.kind})</span>
              <a class="term-trace-of" href={"#/sessions/" + encodeURIComponent(s.tid) + "/trace"}>Trace ›</a>
              <button type="button" class="btn" onclick={() => endOther(s.tid)}>End it</button></li>
          {/each}
        </ul>
      </div>
    {:else if phase === "ready" || (phase === "ended" && !hasTerm)}
      <div class="pad">
        <p>{session ? `${session.words}. Open again resumes the conversation.`
          : "Claude Code, in its own copy of this folder, with Kranto's context and tools. It asks before every edit and command; Kranto's own actions wait for your Confirm here."}</p>
        <button type="button" class="btn primary" onclick={start}>
          {session ? "Open again" : "Open in Claude Code"}</button>
      </div>
    {/if}
    {#if phase === "ended" && hasTerm}
      <p class="ended">{session?.words ?? "Ended"}.
        <button type="button" class="btn primary" onclick={start}>Open again</button></p>
    {/if}
    <div class="screen" class:hidden={!hasTerm || phase === "ready" || phase === "unavailable"}
      bind:this={screenEl}></div>
    {#if phase === "starting"}<p class="dim pad">Starting…</p>{/if}
  </div>
</section>

<style>
  .term { display: flex; flex-direction: column; height: 100%; min-height: 0;
    background: var(--box); border-top: 1px solid var(--border); }
  .term-head { display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
    padding: 4px 8px; border-bottom: 1px solid var(--border); font-size: 13px; }
  .term-head:focus { outline: 2px solid var(--focus); outline-offset: -2px; }
  .grow { flex: 1; }
  .dim { color: var(--muted); }
  .term-warn, .term-err { margin: 0; padding: 4px 8px; font-size: 13px; }
  .term-warn { background: var(--amber-wash); }
  .term-err { background: var(--red-wash); }
  .term-cards { max-height: 40%; overflow: auto; padding: 6px 8px; display: flex;
    flex-direction: column; gap: 6px; border-bottom: 1px solid var(--border); }
  .term-card { border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px;
    font-size: 13px; }
  .term-card.warn { border-color: var(--amber); }
  .term-card.done { color: var(--muted); }
  .term-card .acts { display: flex; gap: 6px; margin-top: 6px; }
  .tag { font-size: 11px; padding: 0 6px; border-radius: 10px; background: var(--amber-wash); }
  .why { margin: 4px 0; padding-left: 8px; border-left: 3px solid var(--border); }
  pre { margin: 4px 0; max-height: 240px; overflow: auto; font-size: 12px; white-space: pre-wrap;
    font-family: var(--mono); }
  .term-outside { padding: 6px 8px; font-size: 13px; border-bottom: 1px solid var(--border); }
  .cmd { display: flex; gap: 6px; align-items: center; }
  .cmd code { flex: 1; overflow-x: auto; white-space: nowrap; padding: 2px 4px;
    background: var(--inset); font-family: var(--mono); }
  .term-body { position: relative; flex: 1; min-height: 0; display: flex; flex-direction: column; }
  .screen { flex: 1; min-height: 0; padding: 4px; background: var(--term-bg); }
  .screen.hidden { display: none; }
  .pad { padding: 8px; }
  .ended { margin: 0; padding: 4px 8px; font-size: 13px; }
</style>
