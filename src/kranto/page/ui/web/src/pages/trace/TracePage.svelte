<script lang="ts">
  // A run's agent trace: a full page (a stage route: a console or Open in Claude
  // Code session's #/sessions/<tid>/trace, a research run's #/research/<id>/trace, one of
  // the server's runs' #/afk/<id>/trace; [?span=<id>]). The head: the crumb, the kind line, the title, the facts. The left: the spans
  // as a Tree (folds), a Timeline (bars over the run's wall time) or a Log (every span, one line
  // each; the phone's form), windowed (ui/Virtual). The right: the selected span's inspector (on
  // the phone, a sheet over the list). Filters: Errors only, a tool, a stage, a kind, and a search
  // (/). Keys: j k move, ← → fold, e next error, t next tool call, 1–6 the inspector's tabs, esc
  // closes the inspector, then goes back. Tokens, never dollars (the owner's ruling).
  import { untrack } from "svelte";
  import type { View } from "../../lib/pages.svelte";
  import { app } from "../../lib/shell.svelte";
  import { href } from "../../lib/router";
  import Virtual from "../../ui/Virtual.svelte";
  import Inspector from "./Inspector.svelte";
  import { safeText } from "./safe";
  import { TraceStore, type Form, type Get } from "./trace.svelte";
  import { factsLine, KIND, mark, rowName, STATE, toks, tokTitle, took } from "./words";
  import type { SpanSummary } from "../../api/types.gen";

  let { view, get = null }: { view: View; get?: Get | null } = $props();

  const fetcher: Get = (p) => (get ? get(p) : app()!.api(p));
  const key = $derived(view.w.r.path[1] || "");
  // a console or Open in Claude Code session's trace (#/sessions/<tid>/trace), a research run's
  // (#/research/<id>/trace), one of the server's runs' (#/afk/<id>/trace)
  const SOURCES: Record<string, string> = { sessions: "session", research: "research", afk: "afk" };
  /** a running run's Stop: with Undo for 9 s before it is asked */
  function stopRun(btn: HTMLElement, id: string): void {
    const L = app();
    if (!L) return;
    let undone = false;
    L.toast("Stopping it at its next step…", () => {
      undone = true;
      L.toast("It goes on.");
    });
    btn.setAttribute("disabled", "");
    setTimeout(() => {
      if (undone) {
        btn.removeAttribute("disabled");
        return;
      }
      void L.act(btn, () => L.api("api/activity/stop", { id }), (y) => L.toast(((y as { words?: string }) || {}).words || "Stopping it."));
    }, 9000);
  }
  const source = $derived(SOURCES[view.w.r.path[0] || ""] || "session");
  let n = $state<number | null>(null);
  let store = $state<TraceStore | null>(null);
  let none = $state<string | null>(null);
  let tab = $state("overview");
  let phone = $state(false);
  let sheet = $state(false);
  let words = $state("");
  let tool = $state("");
  let stage = $state("");
  let kind = $state("");
  let errorsOnly = $state(false);
  let zoom = $state(1);
  let list: { scrollTo(i: number): void } | undefined = $state();
  let searchBox: HTMLInputElement | undefined = $state();

  // a run's trace is its one id: no number to choose
  $effect(() => {
    void key;
    none = null;
    n = 0;
  });
  $effect(() => {
    if (!key || n == null) return;
    const s = new TraceStore(`${source}:${key}`, fetcher);
    store = s;
    s.form = phone ? "log" : "tree";
    void s.load().then(() => {
      if (view.w.r.q.errors) {                    // ⌘K's "Trace: errors in …"
        errorsOnly = true;
        void applyFilter();
      }
    });
  });
  // live: while the run goes on the page asks the server to watch the trace's
  // files (renewed each minute); the feed's change redraws the page, and the page reads on from
  // its cursor: the new spans append, the running one pulses, the head says what runs now
  let followEnd = $state(true);
  let now = $state(Date.now() / 1000);
  $effect(() => {
    const s = store;
    if (!s?.detail || !s.running) return;
    const ask = () => void fetcher(`api/trace/follow?trace=${encodeURIComponent(s.id)}`).catch(() => {});
    ask();
    const renew = setInterval(ask, 60_000), tick = setInterval(() => (now = Date.now() / 1000), 1000);
    // back online after a long drop: the server's watch may have lapsed; ask again at once
    addEventListener("online", ask);
    return () => {
      clearInterval(renew);
      clearInterval(tick);
      removeEventListener("online", ask);
    };
  });
  $effect(() => {
    void view.tick;                               // the app drew again: the feed said something changed
    untrack(() => {
      const s = store;
      if (s && s.done && s.running) void s.refresh();
    });
  });
  const live = $derived.by(() => {
    const s = store;
    if (!s?.running) return null;
    void s.ver;
    const c = s.current();
    if (!c) {
      // between calls: the latest step, and how long ago it ended
      const last = [...s.order].reverse().find((x) => x.kind !== "hook" && x.kind !== "event") || null;
      if (!last || last.kind === "run") return "starting";
      const ago = last.end ?? last.start;
      return [last.stage, last.kind === "session" ? "session " + last.name : last.name, ago ? `${Math.max(0, Math.round(now - ago))} s ago` : null].filter(Boolean).join(" · ");
    }
    const parent = c.parent ? s.spans.get(c.parent) : null;
    return [c.stage, parent?.kind === "turn" ? parent.name : null, c.name + (c.start ? ` running ${Math.max(0, Math.round(now - c.start))} s` : " running")].filter(Boolean).join(" · ");
  });

  // the selection the route names, once its span has arrived: ?span=<id>; ?stage=<name> (a
  // stage's "Trace ›"); ?check=<scenario> and ?hold=<check> (a failed check's "Trace ›": the
  // span the trace links it to, its Output open; or the trace's note when it holds no run)
  let note = $state<string | null>(null);
  let checkWhy = $state<string | null>(null);     // a held check landed on: what the gate read
  const wanted = $derived.by(() => {
    const s = store, rq = view.w.r.q;
    if (!s?.detail) return null;
    void s.ver;
    if (rq.span) return rq.span;
    if (rq.stage) return s.detail.stages.find((x) => x.name === rq.stage)?.id || null;
    if (rq.failed) return s.detail.failed_at || null;   // "see where ›" on a failed run
    const kind = rq.check ? "check" : rq.hold ? "hold" : null;
    if (!kind) return null;
    const lk = s.detail.links.find((l) => l.kind === kind && l.ref === (rq.check || rq.hold));
    return lk?.span || null;
  });
  $effect(() => {
    const s = store, rq = view.w.r.q;
    if (!s?.detail) return;
    const kind = rq.check ? "check" : rq.hold ? "hold" : null;
    const lk = kind ? s.detail.links.find((l) => l.kind === kind && l.ref === (rq.check || rq.hold)) : null;
    note = kind && (!lk || !lk.span) ? (lk?.note || "The trace does not link this check to a span.") : null;
    checkWhy = kind && lk?.span && lk.detail ? `${String(lk.ref).replace("_", " ")} failed: ${lk.detail}` : null;
  });
  // where the note sends the reader: the latest session that verified, else the verify stage
  const VERIFYING = new Set(["verify", "check", "reverify"]);
  const verifyAt = $derived.by(() => {
    const s = store;
    if (!note || !s) return null;
    void s.ver;
    const sess = [...s.order].reverse().find((x) => x.kind === "session" && VERIFYING.has(String(x.stage)));
    return sess?.id || s.detail?.stages.find((x) => VERIFYING.has(x.name))?.id || null;
  });
  let applied: string | null = null;            // the route's target, once: then the reader moves
  $effect(() => {
    const want = wanted, s = store;
    void s?.ver;                                // its span may arrive after the link resolves
    if (!s || !want || !s.spans.has(want) || applied === s.id + want) return;
    applied = s.id + want;
    if (view.w.r.q.check || view.w.r.q.hold || view.w.r.q.failed) tab = "output";
    select(want, false);
  });

  const rows = $derived.by(() => (store ? (void store.ver, store.form, store.filtered, store.rows()) : []));
  const t0 = $derived(store?.detail?.started ?? 0);
  const t1 = $derived.by(() => {
    const d = store?.detail;
    if (!d) return 1;
    return (d.ended ?? (store!.order.reduce((a, s) => Math.max(a, s.end ?? s.start ?? 0), d.started ?? 0))) || 1;
  });
  const toolsHere = $derived.by(() => {
    if (!store) return [] as [string, number][];
    void store.ver;
    const c = new Map<string, number>();
    for (const s of store.order) if (s.tool) c.set(s.tool, (c.get(s.tool) || 0) + 1);
    return [...c.entries()].sort((a, b) => b[1] - a[1]);
  });
  const stagesHere = $derived(store?.detail?.stages.map((s) => s.name) || []);

  function select(id: string, route = true): void {
    if (!store) return;
    store.reveal(id);
    store.selected = id;
    sheet = phone;
    const i = rows.findIndex((s) => s.id === id);
    queueMicrotask(() => list?.scrollTo(i >= 0 ? i : store!.rows().findIndex((s) => s.id === id)));
    if (route) history.replaceState(null, "", href(view.w.r.path.map(encodeURIComponent).join("/"), { span: id }));
  }
  function move(by: number): void {
    if (!store || !rows.length) return;
    const at = store.selected ? rows.findIndex((s) => s.id === store!.selected) : -1;
    const i = Math.max(0, Math.min(rows.length - 1, at < 0 ? 0 : at + by));
    select(rows[i]!.id);
  }
  function jump(test: (s: SpanSummary) => boolean): void {
    const id = store?.next(test, false, true);
    if (id) select(id);
  }
  async function applyFilter(payloads = false): Promise<void> {
    if (!store) return;
    const spec = [errorsOnly ? "errors" : "", tool ? "tool:" + tool : "", stage ? "stage:" + stage : "", kind ? "kind:" + kind : ""].filter(Boolean).join(",");
    await store.filter(spec || null, words.trim() || null, payloads);
  }
  function clearFilter(): void {
    errorsOnly = false;
    tool = stage = kind = words = "";
    void applyFilter();
  }
  function setForm(f: Form): void {
    if (store) {
      store.form = f;
      store.ver++;
    }
  }
  function close(): boolean {
    if (store?.selected) {
      store.selected = null;
      sheet = false;
      history.replaceState(null, "", href(view.w.r.path.map(encodeURIComponent).join("/"), { ...view.w.r.q, span: null }));
      return true;
    }
    history.back();                                // where the trace was opened from
    return true;
  }

  // the page's keys (lib/keys.json's Trace group)
  $effect(() => {
    void view.tick;
    const L = app();
    if (!L) return;
    L.pageKey("j", () => move(1));
    L.pageKey("k", () => move(-1));
    L.pageKey("e", () => jump((s) => s.status === "error" && s.kind !== "run" && s.kind !== "stage"));
    L.pageKey("t", () => jump((s) => s.kind === "tool" || s.kind === "subagent"));
    L.pageKey("/", () => searchBox?.focus());
    L.pageKey("esc", () => void close());
    L.pageKey("f", () => (followEnd = !followEnd));
    ["overview", "input", "output", "chat", "diff", "raw"].forEach((k, i) => L.pageKey(String(i + 1), () => (tab = k)));
  });
  $effect(() => {
    const mq = typeof matchMedia === "function" ? matchMedia("(max-width: 700px)") : null;
    phone = !!mq?.matches;
    const on = () => {
      phone = !!mq?.matches;
      if (store && phone && store.form === "tree") setForm("log");
    };
    mq?.addEventListener?.("change", on);
    const arrows = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (!store?.selected || (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) || e.altKey || e.metaKey || e.ctrlKey) return;
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        const s = store.spans.get(store.selected);
        if (!s) return;
        if (e.key === "ArrowLeft" && (!s.children || store.folded(s)) && s.parent) select(s.parent);
        else store.toggle(s.id, e.key === "ArrowLeft");
        e.preventDefault();
      }
    };
    addEventListener("keydown", arrows);
    return () => {
      mq?.removeEventListener?.("change", on);
      removeEventListener("keydown", arrows);
    };
  });

  const bar = (s: SpanSummary) => {
    const span = Math.max(t1 - t0, 1e-3);
    const a = s.start != null ? (s.start - t0) / span : 0, b = (s.end ?? (s.status === "running" ? t1 : s.start ?? t0)) - t0;
    return { left: Math.max(0, a * 100), width: Math.max(0.15, (b / span - a) * 100) };
  };
  const st = $derived(store?.detail ? STATE[store.detail.state] : null);
  // why a trace is short (the empty states): the server's note (a session with no
  // transcript, one continued outside, a run with no model calls)
  const why = $derived(store?.detail?.note || null);
</script>

{#snippet spanRow(s: SpanSummary, i: number)}
  {@const m = mark(s)}
  {@const hit = store?.filtered?.hits.includes(s.id)}
  <div class="sr" role="treeitem" aria-selected={store?.selected === s.id} aria-level={s.depth + 1} aria-expanded={s.children ? !store?.folded(s) : undefined}
       class:t-sel={store?.selected === s.id} class:failed={store?.detail?.failed_at === s.id} class:t-hit={hit} data-span={s.id} data-i={i}
       style:padding-left={(store?.form === "log" ? 8 : 8 + s.depth * 14) + "px"}>
    {#if store?.form !== "log"}
      {#if s.children}<button type="button" class="t-tw" aria-label={store?.folded(s) ? "Unfold" : "Fold"} onclick={() => store?.toggle(s.id)}>{store?.folded(s) ? "▸" : "▾"}</button>{:else}<span class="t-tw"></span>{/if}
    {/if}
    <button type="button" class="pick" onclick={() => select(s.id)}>
      <span class={"g tone-" + m.tone + (s.status === "running" ? " pulse" : "")} title={m.word} aria-label={m.word}>{m.glyph}</span>
      <span class="t-kind">{KIND[s.kind] || s.kind}</span>
      <span class="t-nm"><b>{safeText(rowName(s))}</b>{#if s.preview && s.kind !== "stage"}<span class="t-pv">{" "}{safeText(s.preview)}</span>{/if}{#if s.kind === "subagent"}<span class="t-pv">{" "}(sub-agent · {s.children} spans)</span>{/if}</span>
      {#if store?.detail?.failed_at === s.id}<span class="fa">← failed here</span>{/if}
    </button>
    {#if store?.form === "timeline"}
      {@const b = bar(s)}
      <span class="lane" style:width={zoom * 100 + "%"}><span class={"t-bar k-" + s.kind + " tone-bg-" + m.tone} style:left={b.left + "%"} style:width={b.width + "%"}></span></span>
    {:else}
      <span class="num">{took(s) || (s.status === "running" ? "…" : "")}</span>
      <span class="num" title={tokTitle(s.tokens)}>{toks(s.tokens)}</span>
    {/if}
  </div>
{/snippet}

<div class="trace" data-title={store?.detail ? "Trace · " + store.detail.title : "Trace"}>
  <header class="th">
    <nav class="crumb" aria-label="Where you are"><a href={href("home")}>Home</a> › {#if source === "afk"}<a href={href("activity")}>Activity</a>{:else}{source === "research" ? "Research" : "Open in Claude Code"}{/if} › <b>Trace</b></nav>
    <div class="dk">{source} · trace{#if store?.detail?.started}{" · "}{new Date(store.detail.started * 1000).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}{/if}</div>
    <h1 class="dt">{store?.detail ? safeText(store.detail.title) : "Trace"}</h1>
    {#if store?.detail && st}
      {#if live}<p class="t-live" role="status"><span class="tone-blue pulse" aria-hidden="true">◔</span> running · {safeText(live)}{" · "}<button type="button" class="linkish" onclick={() => (followEnd = !followEnd)}>{followEnd ? "following the end (f)" : "follow the end (f)"}</button></p>{/if}
      <!-- a run in one line, with its Stop while it runs -->
      {#if store.detail.line}<p class="t-live" id="trace-line" role="status">{#if store.detail.running}<span class="tone-blue pulse" aria-hidden="true">◔</span>{" "}{/if}{safeText(store.detail.line)}{#if store.detail.stop}{@const sid = store.detail.stop.id}{" · "}<button type="button" class="linkish" id="trace-stop" title="Stop it at its next step; what it did so far stays" onclick={(e) => stopRun(e.currentTarget, sid)}>Stop</button>{/if}</p>{/if}
      <p class="facts-line"><span class={"tone-" + st.tone}>{st.glyph} {st.word}{#if store.detail.outcome === "held"} (held){/if}</span>{#each factsLine(store.detail) as f (f)}{" · "}{f}{/each}{#if store.detail.failed_label}{" · failed at "}<button type="button" class="linkish" onclick={() => { const f = store?.failing(); if (f) { tab = "output"; select(f); } }}>{store.detail.failed_label}</button>{/if}</p>
    {/if}
    <div class="tools">
      <div class="t-seg" role="group" aria-label="The form">
        {#each [["tree", "Tree"], ["timeline", "Timeline"], ["log", "Log"]] as [f, w] (f)}
          <button type="button" class="btn sm" aria-pressed={store?.form === f} onclick={() => setForm(f as Form)}>{w}</button>
        {/each}
      </div>
      <form class="find" onsubmit={(e) => { e.preventDefault(); void applyFilter(); }}>
        <input bind:this={searchBox} type="search" placeholder="Search in this trace" aria-label="Search in this trace" bind:value={words} onkeydown={(e) => { if (e.key === "Escape") { clearFilter(); (e.currentTarget as HTMLInputElement).blur(); } }} />
      </form>
      <button type="button" class="chip" aria-pressed={errorsOnly} onclick={() => { errorsOnly = !errorsOnly; void applyFilter(); }}>✕ Errors only</button>
      <select aria-label="Tool" bind:value={tool} onchange={() => void applyFilter()}><option value="">Tool</option>{#each toolsHere as [t, c] (t)}<option value={t}>{t} ({c})</option>{/each}</select>
      <select aria-label="Stage" bind:value={stage} onchange={() => void applyFilter()}><option value="">Stage</option>{#each stagesHere as s (s)}<option value={s}>{s}</option>{/each}</select>
      <select aria-label="Kind" bind:value={kind} onchange={() => void applyFilter()}><option value="">Kind</option>{#each ["session", "turn", "tool", "subagent", "hook", "call", "event"] as k (k)}<option value={k}>{KIND[k]}</option>{/each}</select>
      {#if store?.form === "timeline"}<span class="t-seg"><button type="button" class="btn sm" aria-label="Zoom out" onclick={() => (zoom = Math.max(1, zoom / 2))}>−</button><button type="button" class="btn sm" aria-label="Zoom in" onclick={() => (zoom = Math.min(64, zoom * 2))}>+</button></span>{/if}
      <a class="btn sm quiet dl" href={`api/trace/download?trace=${encodeURIComponent(store?.id || "")}`} download={`trace-${key}.json`}>Download (redacted)</a>
      <span class="t-hint small muted">j k move · ← → fold · e next error · t next tool · / search</span>
    </div>
    {#if note}<p class="flash amber small" role="status">{verifyAt ? note.replace(/;?\s*open the verify session\.?$/i, ".") : note}{#if verifyAt}{" "}<button type="button" class="linkish" id="open-verify" onclick={() => { tab = "overview"; select(verifyAt!); }}>Open the verify session ›</button>{/if}{#if view.w.r.q.check}{" "}<button type="button" class="linkish" onclick={() => { words = view.w.r.q.check || ""; void applyFilter(); }}>Search the trace for {view.w.r.q.check}</button>{/if}</p>{/if}
    {#if why}<p class="small fl" id="trace-note" role="note">{safeText(why)}</p>{/if}
    {#if checkWhy}<p class="small muted fl" id="check-why">{safeText(checkWhy)}</p>{/if}
    {#if store?.filtered}
      <p class="small fl">{store.filtered.hits.length} match{store.filtered.hits.length === 1 ? "" : "es"} for {store.filtered.label}{#if store.filtered.words}{" · "}<button type="button" class="linkish" id="search-payloads" title="Read the trace's files: every tool's whole input and output, every turn's words and thinking (redacted, at most 500 matches)" onclick={() => void applyFilter(true)}>Search every payload…</button>{/if}{" · "}<button type="button" class="linkish" onclick={clearFilter}>Show everything</button></p>
    {/if}
  </header>
  {#if none}
    <p class="empty">{none}</p>
  {:else if store?.error && !store.detail}
    <div class="flash red" role="status"><div>{store.error}</div></div>
  {:else if !store?.detail}
    <p class="empty">Reading the trace…</p>
  {:else}
    <div class="body" class:with={!!store.selected && !phone}>
      <div class="left">
        {#if !rows.length}
          <p class="empty">{store.filtered ? "Nothing matches." : store.done ? "This run has no spans yet: its trace starts with its first session." : "Reading a large trace… " + store.order.length + " spans so far"}</p>
        {:else}
          <Virtual bind:this={list} items={rows} row={spanRow} label="Spans" height={30} follow={store.running && followEnd && !store.selected}
                   onscrolled={(atEnd) => { if (store?.running) followEnd = atEnd; }} />
        {/if}
        {#if !store.done}<p class="small muted t-more">Reading… {store.order.length} of {store.total} spans</p>{/if}
      </div>
      {#if store.selected && (!phone || sheet)}
        <aside class="right" class:t-sheet={phone} aria-label="The selected span">
          {#key store.selected}
            <Inspector {store} id={store.selected} bind:tab onpick={(id) => select(id)} onclose={phone ? () => { sheet = false; store!.selected = null; } : null} />
          {/key}
        </aside>
      {/if}
    </div>
  {/if}
</div>

<style>
  .trace {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
  }
  /* a stage page is held to a reading column (base.css); the trace's two panes need the width */
  :global(body.stage #rows > .trace) {
    max-width: none;
    margin: 0;
  }
  .th {
    padding: 16px 24px 10px;
    border-bottom: 1px solid var(--line);
  }
  .t-live {
    margin: 2px 0;
    font-size: 13px;
    color: var(--blue);
  }
  .facts-line {
    margin: 2px 0 10px;
    font-size: 13px;
    color: var(--muted);
  }
  .tools {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
  }
  .t-seg {
    display: inline-flex;
  }
  .find input {
    font: inherit;
    font-size: 13px;
    padding: 3px 8px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--box);
    color: var(--text);
    min-width: 14em;
  }
  select {
    font: inherit;
    font-size: 12px;
    padding: 2px 6px;
    border: 1px solid var(--border);
    border-radius: 12px;
    background: var(--violet-wash);
    color: var(--text);
  }
  .t-hint {
    margin-left: auto;
  }
  .fl {
    margin: 8px 0 0;
  }
  .body {
    flex: 1;
    min-height: 0;
    display: grid;
    grid-template-columns: minmax(0, 1fr);
  }
  .body.with {
    grid-template-columns: minmax(0, 1.6fr) minmax(320px, 1fr);
  }
  .left {
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .left :global(.virt) {
    flex: 1;
  }
  .right {
    border-left: 1px solid var(--line);
    min-height: 0;
    overflow: hidden;
    background: var(--box);
  }
  .right.t-sheet {
    position: fixed;
    inset: 0;
    z-index: 30;
    border: 0;
  }
  .sr {
    display: flex;
    align-items: center;
    gap: 6px;
    height: 30px;
    padding-right: 12px;
    font-size: 13px;
    border-left: 3px solid transparent;
    white-space: nowrap;
  }
  .sr.t-sel {
    background: var(--sel);
    border-left-color: var(--selbar);
  }
  .sr.failed .t-nm b {
    color: var(--red);
  }
  .sr.t-hit .t-nm b {
    text-decoration: underline;
    text-decoration-color: var(--amber);
  }
  .t-tw {
    width: 16px;
    flex: none;
    background: none;
    border: 0;
    padding: 0;
    color: var(--muted);
    cursor: pointer;
    font-size: 11px;
  }
  .pick {
    display: flex;
    align-items: center;
    gap: 6px;
    flex: 1;
    min-width: 0;
    height: 100%;
    overflow: hidden;
    white-space: nowrap;
    background: none;
    border: 0;
    padding: 0;
    font: inherit;
    color: var(--text);
    text-align: left;
    cursor: pointer;
  }
  .g {
    width: 14px;
    flex: none;
    text-align: center;
  }
  .t-kind {
    font: 10px var(--mono);
    color: var(--muted);
    text-transform: uppercase;
    width: 6.2em;
    flex: none;
  }
  .t-nm {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .t-pv {
    color: var(--muted);
  }
  .fa {
    color: var(--red);
    font-size: 12px;
    flex: none;
  }
  .num {
    font: 12px var(--mono);
    color: var(--muted);
    width: 6.5em;
    text-align: right;
    flex: none;
  }
  .lane {
    position: relative;
    height: 12px;
    flex: 0 0 45%;
    min-width: 45%;
    background: var(--subtle);
    border-radius: 3px;
  }
  .t-bar {
    position: absolute;
    top: 2px;
    height: 8px;
    border-radius: 2px;
    background: var(--blue);
  }
  .tone-bg-green {
    background: var(--green);
  }
  .tone-bg-red {
    background: var(--red);
  }
  .tone-bg-amber {
    background: var(--amber);
  }
  .tone-bg-grey {
    background: var(--muted);
  }
  .tone-green {
    color: var(--green);
  }
  .tone-red {
    color: var(--red);
  }
  .tone-blue {
    color: var(--blue);
  }
  .tone-amber {
    color: var(--amber);
  }
  .tone-grey {
    color: var(--muted);
  }
  .pulse {
    animation: breathe 1.2s ease-in-out infinite;
  }
  @keyframes breathe {
    50% {
      opacity: 0.35;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .pulse {
      animation: none;
      outline: 1px solid var(--blue);
      border-radius: 50%;
    }
  }
  .t-more {
    padding: 4px 12px;
    margin: 0;
  }
  @media (max-width: 700px) {
    .th {
      padding: 12px;
    }
    .t-hint,
    .dl,
    .t-kind {
      display: none;
    }
    .num:last-child {
      display: none;
    }
  }
</style>
