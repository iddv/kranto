<script lang="ts">
  // The selected span: its title line, then tabs Overview · Input · Output ·
  // Chat · Diff · Raw (keys 1–6). The error first, as a red flash. Payloads are read when their
  // tab opens (api/trace/payload), redacted by the server, and drawn as text (safe.ts). Raw is
  // the file and its line to copy: the raw text is never drawn here (decision D-3; the CLI's
  // --raw prints it at the owner's own terminal).
  import type { SpanDetail, TracePayload } from "../../api/types.gen";
  import ChatView from "./ChatView.svelte";
  import DiffView from "./DiffView.svelte";
  import TextOut from "./TextOut.svelte";
  import { safeText } from "./safe";
  import type { TraceStore } from "./trace.svelte";
  import { KIND, mark, secs, toks, tokTitle, took } from "./words";

  let { store, id, tab = $bindable("overview"), onpick, onclose = null }: {
    store: TraceStore;
    id: string;
    tab?: string;
    onpick: (span: string) => void;
    onclose?: (() => void) | null;
  } = $props();

  const q = (path: string, o: Record<string, string | number>) => path + "?" + new URLSearchParams(Object.entries(o).map(([k, v]) => [k, String(v)]));

  let span = $state<SpanDetail | null>(null);
  let spanErr = $state<string | null>(null);
  let pay = $state<Record<string, TracePayload | { error: string }>>({});
  let more = $state<{ part: string; busy: boolean } | null>(null);

  const EDITS = ["Edit", "MultiEdit", "Write", "NotebookEdit"];
  const tabs = $derived.by(() => {
    const s = span;
    const out: [string, string][] = [["overview", "Overview"]];
    if (!s) return out;
    if (["tool", "subagent", "turn"].includes(s.kind)) out.push(["input", "Input"], ["output", "Output"]);
    if (["tool", "subagent", "turn", "session"].includes(s.kind)) out.push(["chat", "Chat"]);
    if (s.tool && EDITS.includes(s.tool)) out.push(["diff", "Diff"]);
    out.push(["raw", "Raw"]);
    return out;
  });

  $effect(() => {
    const sid = id;
    span = null;
    spanErr = null;
    pay = {};
    store.get(q("api/trace/span", { trace: store.id, span: sid })).then(
      (d) => { if (sid === id) span = d as SpanDetail; },
      (e: Error) => { if (sid === id) spanErr = e.message; },
    );
  });
  // a tab the span has not got falls back to the overview
  $effect(() => {
    if (span && !tabs.some(([k]) => k === tab)) tab = "overview";
  });
  $effect(() => {
    const part = tab, sid = id;
    if (!span || !["input", "output", "chat", "diff"].includes(part) || pay[part]) return;
    store.get(q("api/trace/payload", { trace: store.id, span: sid, part })).then(
      (d) => { if (sid === id) pay = { ...pay, [part]: d as TracePayload }; },
      (e: Error) => { if (sid === id) pay = { ...pay, [part]: { error: e.message } }; },
    );
  });

  async function next(part: string): Promise<void> {
    const cur = pay[part] as TracePayload;
    if (!cur || cur.next == null) return;
    more = { part, busy: true };
    try {
      const d = (await store.get(q("api/trace/payload", { trace: store.id, span: id, part, offset: cur.next }))) as TracePayload;
      if (part === "chat") pay = { ...pay, chat: { ...d, messages: [...(cur.messages || []), ...(d.messages || [])] } };
      else pay = { ...pay, [part]: { ...d, text: (cur.text || "") + (d.text || "") } };
    } finally {
      more = null;
    }
  }

  const copy = (s: string) => void navigator.clipboard?.writeText(s);
  const when = (ts: number | null | undefined) => {
    if (ts == null) return "–";
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) + "." + String(d.getMilliseconds()).padStart(3, "0");
  };
  const m = $derived(span ? mark(span) : null);
  const attr = (k: string): unknown => span?.attributes?.[k];
  const ids = $derived(span ? ([["tool_use_id", attr("call_id")], ["request", attr("request_id")], ["message", attr("message_id")], ["session", attr("session_id")]] as [string, unknown][]).filter(([, v]) => typeof v === "string" && v) as [string, string][] : []);
  const isErr = (p: unknown): p is { error: string } => !!p && typeof p === "object" && "error" in p && typeof (p as { error: unknown }).error === "string" && !("redactions" in p);
</script>

<div class="insp">
  {#if spanErr}
    <p class="flash red" role="status">{spanErr}</p>
  {:else if !span}
    <p class="empty">Loading the span…</p>
  {:else}
    <div class="ih">
      <span class={"tone-" + m?.tone} title={m?.word}>{m?.glyph}</span>
      <b>{safeText(span.name)}</b>
      <span class="muted">{" · "}{took(span) || (span.status === "running" ? "running" : "")}{" · "}{m?.word}{#if span.stage}{" · "}{span.stage}{/if}</span>
      {#if onclose}<button type="button" class="btn sm quiet close" onclick={onclose} aria-label="Close the span">✕</button>{/if}
    </div>
    <nav class="tabs itabs" aria-label="The span">
      {#each tabs as [k, w], i (k)}
        <button type="button" class="tab" aria-current={tab === k ? "page" : undefined} onclick={() => (tab = k)}>{w} <kbd>{i + 1}</kbd></button>
      {/each}
    </nav>
    <div class="ib">
      {#if span.error && tab === "overview"}
        <div class="flash red" role="status"><div><b>{safeText(span.error_detail?.type as string || "error")}</b>{" · "}{safeText(span.error)}</div></div>
      {/if}
      {#if tab === "overview"}
        <dl class="t-kv">
          <dt>kind</dt><dd>{KIND[span.kind] || span.kind}{#if span.tool}{" · "}{span.tool}{#if attr("server")}{" · MCP server "}{attr("server")}{/if}{/if}{#if attr("agent_type")}{" · "}{attr("agent_type")}{/if}</dd>
          {#each ids as [k, v] (k)}<dt>{k}</dt><dd><span class="mono">{v}</span> <button type="button" class="btn sm quiet" title="Copy" onclick={() => copy(v)}>copy</button></dd>{/each}
          {#if attr("model")}<dt>model</dt><dd>{attr("model")}</dd>{/if}
          <dt>started</dt><dd class="mono">{when(span.start)}</dd>
          <dt>ended</dt><dd class="mono">{span.end != null ? when(span.end) : span.status === "running" ? "still running" : "–"}</dd>
          {#if took(span)}<dt>took</dt><dd>{took(span)}{#if attr("hook_ms") != null}{" · the hook says "}{secs(Number(attr("hook_ms")) / 1000)}{/if}</dd>{/if}
          {#if span.tokens}<dt>tokens</dt><dd title={tokTitle(span.tokens)}>{toks(span.tokens)} <span class="muted small">(in, cached included / out)</span></dd>{/if}
          {#if attr("turns") != null}<dt>turns</dt><dd>{attr("turns")}</dd>{/if}
          {#if attr("file_path")}<dt>file</dt><dd class="mono">{safeText(String(attr("file_path")))}{#if attr("lines_added") != null}{" · +"}{attr("lines_added")}{/if}{#if attr("lines_removed") != null}{" −"}{attr("lines_removed")}{/if}</dd>{/if}
          {#if attr("terminal_reason") || attr("subtype")}<dt>ended as</dt><dd>{attr("subtype") || ""}{#if attr("terminal_reason")}{" · "}{attr("terminal_reason")}{/if}</dd>{/if}
          {#if span.inputs?.bytes}<dt>input</dt><dd>{Number(span.inputs.bytes).toLocaleString("en-GB")} bytes</dd>{/if}
          {#if span.outputs?.bytes != null}<dt>output</dt><dd>{Number(span.outputs.bytes).toLocaleString("en-GB")} bytes</dd>{/if}
          <dt>source</dt><dd class="mono">{span.source.file || "–"}:{span.source.line ?? "–"}</dd>
          <dt>links</dt><dd>{#if span.links.length}{#each span.links as lk, i (i)}{#if i}{", "}{/if}{#if lk.span && lk.trace === store.id}<button type="button" class="linkish" onclick={() => onpick(String(lk.span))}>{lk.kind}</button>{:else}{lk.kind} {lk.trace}{/if}{/each}{:else}none{/if}</dd>
        </dl>
        {#if typeof attr("summary") === "string"}<h4>Summary</h4><pre class="t-sum mono small">{safeText(String(attr("summary")))}</pre>{/if}
        {#if span.events.length}
          <h4>Events</h4>
          <ul class="t-ev">{#each span.events as e, i (i)}<li><span class="mono">{when(e.ts as number)}</span> {safeText(String(e.name))}</li>{/each}</ul>
        {/if}
        {#if span.preview && span.kind !== "tool"}<p class="small muted t-pv">{safeText(span.preview)}</p>{/if}
      {:else if tab === "raw"}
        <p class="small">The span's line is in <span class="mono">{span.path || span.source.file}</span> at line {span.source.line ?? "?"}. The page never draws a raw line: it may hold what redaction hides. Read it at your own terminal:</p>
        <p><code class="mono">kranto trace show {store.id} --span {span.id} --raw</code> <button type="button" class="btn sm" onclick={() => copy(`kranto trace show ${store.id} --span ${span!.id} --raw`)}>Copy</button></p>
        {#if span.path}<p><button type="button" class="btn sm" onclick={() => copy(`${span!.path}:${span!.source.line ?? ""}`)}>Copy the file and line</button></p>{/if}
      {:else}
        {@const p = pay[tab]}
        {#if !p}
          <p class="empty">Reading…</p>
        {:else if isErr(p)}
          <p class="flash amber" role="status">{p.error}</p>
        {:else if tab === "input"}
          {#if p.fields}
            <dl class="t-kv t-wide">{#each p.fields as f (f.key)}<dt>{f.key}</dt><dd><pre class="pre">{safeText(f.value)}</pre></dd>{/each}</dl>
          {:else}
            <TextOut text={p.text || ""} next={p.next ?? null} onmore={() => next("input")} busy={more?.part === "input"} />
          {/if}
        {:else if tab === "output"}
          {#if p.running}<p class="empty">Still running: the output arrives with its result.</p>{:else}
            <TextOut text={p.text || ""} stderr={p.stderr || null} error={!!p.is_error} next={p.next ?? null} onmore={() => next("output")} busy={more?.part === "output"} />
          {/if}
        {:else if tab === "chat"}
          <ChatView messages={p.messages || []} focus={p.focus ?? null} onpick={onpick} />
          {#if p.next != null}<button type="button" class="btn" disabled={more?.part === "chat"} onclick={() => next("chat")}>Show more of the conversation</button>{/if}
        {:else if tab === "diff"}
          <DiffView d={p} />
        {/if}
        {#if p && !isErr(p)}
          {@const n = (p.redactions || []).reduce((a, r) => a + r.n, 0)}
          <p class="small muted red-n">{#if n}{n} redaction{n === 1 ? "" : "s"} here: {(p.redactions || []).map((r) => `${r.n} ${r.kind}`).join(", ")} (the kinds, never the values){:else}nothing redacted here{/if}</p>
        {/if}
      {/if}
      {#if tab === "overview"}
        {@const n = span.redactions.reduce((a, r) => a + r.n, 0)}
        <p class="small muted red-n">{n ? `${n} redaction${n === 1 ? "" : "s"} in this span's facts: ${span.redactions.map((r) => `${r.n} ${r.kind}`).join(", ")}` : "nothing redacted in this span's facts"}</p>
      {/if}
    </div>
  {/if}
</div>

<style>
  .insp {
    display: flex;
    flex-direction: column;
    min-height: 0;
    height: 100%;
  }
  .ih {
    display: flex;
    align-items: baseline;
    gap: 6px;
    padding: 12px 16px 6px;
    font-size: 15px;
    min-width: 0;
  }
  .ih b {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .close {
    margin-left: auto;
  }
  .itabs {
    padding: 0 12px;
    border-bottom: 1px solid var(--line);
    flex-wrap: wrap;
  }
  .itabs .tab {
    background: none;
    border: 0;
    font: inherit;
    font-size: 13px;
    cursor: pointer;
  }
  .itabs .tab[aria-current="page"] {
    border-bottom-color: var(--blue);
    font-weight: 600;
  }
  .ib {
    padding: 12px 16px;
    overflow: auto;
    min-height: 0;
    flex: 1;
  }
  .t-kv {
    display: grid;
    grid-template-columns: max-content minmax(0, 1fr);
    gap: 4px 16px;
    font-size: 13px;
    margin: 0 0 12px;
  }
  .t-kv dt {
    color: var(--muted);
  }
  .t-kv dd {
    margin: 0;
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .t-sum {
    margin: 0 0 12px;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    max-height: 24em;
    overflow: auto;
  }
  .pre {
    margin: 0;
    white-space: pre-wrap;
    word-break: break-word;
    font: 12px/1.45 var(--mono);
    max-height: 40vh;
    overflow: auto;
  }
  .t-ev {
    font-size: 12px;
    padding-left: 16px;
  }
  .t-pv,
  .red-n {
    margin-top: 12px;
    border-top: 1px solid var(--line);
    padding-top: 8px;
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
  kbd {
    font-size: 10px;
  }
</style>
