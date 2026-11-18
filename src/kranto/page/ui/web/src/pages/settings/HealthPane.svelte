<script lang="ts">
  // Settings › System › Health, the pane: with nothing selected the watcher's state with Run
  // ingest now; a group (model calls, items, where
  // observations come from, retention) or a row (a run, a model error, a message, a strike gate
  // decision). A message's pane is Needs you's (pages/front/MessagePane), with its delivery.
  import { keepOpen, OPENED } from "../../ui/opened.svelte";
  import Detail from "../../ui/Detail.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Kv from "../../ui/Kv.svelte";
  import Loading from "../../ui/Loading.svelte";
  import Pane from "../../ui/Pane.svelte";
  import Icon from "../../shell/Icon.svelte";
  import Mark from "../../shell/Mark.svelte";
  import { cut, memoryWords, n3, nextRead, pct, plural, readingWords, tokText, tokTitle, type Tok, watchPaused } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { app, ui } from "../../lib/shell.svelte";
  import { groupOf, kindLine, SET_ST } from "../../ui/settings";
  import MessagePane from "../front/MessagePane.svelte";
  import { capUsed, HEALTH_API, mb, memSt, pacedWord, runSt, stamp, words, type Health, type Run } from "./health";
  import { confirmThen } from "../../ui/dialog.svelte";

  let { view }: { view: View } = $props();
  const id = $derived(groupOf(view.w));
  const host = $derived(!!ui.facts?.header.host);
  const a = $derived.by(() => {
    void view.tick;
    return host ? read<Health>(HEALTH_API, 20000) : null;
  });
  const d = $derived(a?.data || null);
  const k = $derived(id ? id.split(":")[0] || "" : "");
  const v = $derived(id ? id.slice(k.length + 1) : "");

  function runNow(btn: HTMLElement): void {
    confirmThen("Run ingest now?", "Every active source is read and its new items judged: model calls through your provider, as a scheduled run makes. Activity shows it while it runs, with Stop.", "Run now", () => runIngest(btn));
  }
  function runIngest(btn: HTMLElement): void {
    const L = app();
    void L?.act(btn, async () => {
      const r = await L.hostForm("/run/ingest");
      L.afkDrop();
      return r;
    }, () => L.say("Started an ingest run: Activity shows it while it runs."));
  }
  // a provider's pause (a spend limit reached) ends now: after the limit was raised at the provider
  function resumeWatch(btn: HTMLElement): void {
    const L = app();
    void L?.act(btn, async () => {
      const r = await L.api("/api/watch/resume", {});
      L.afkDrop();
      return r;
    }, () => L.say("Watching goes on at its next run."));
  }
  const hasDetail = (x: Run): boolean => {
    const s = x.summary || {};
    return !!(x.error || (x.kind === "compact" && s.expired) || s.overrides?.rated || s.sponsored || s.sponsor_links || (s.sources || []).length);
  };
</script>

{#snippet tok(t: Tok | null | undefined, cls = "tok")}<span class={cls} title={tokTitle(t)}>{tokText(t)}</span>{/snippet}
{#snippet gone(text: string)}<div class="pane-empty"><p class="empty">{text}</p></div>{/snippet}

<Detail back={view.back}>
  {#if !id || id === "reading"}
    {#if !host}
      {@render gone("Watching's health needs the server, which is not answering.")}
    {:else if !d}
      <div class="pane-in"><Loading error={a?.error} /></div>
    {:else}
      {@const nextAt = d.next_run?.ingest}
      {@const st = d.paused || d.watch_paused ? (["held", "amber", "Paused"] as const) : SET_ST.ok}
      <Pane title="What Kranto did" sections={[{ id: "watching", w: "Watching" }]}>
        {#snippet kind()}<Glyph name={st[0]} colour={st[1]} word={st[2]} />{kindLine("system", "health")}{/snippet}
        {#snippet acts()}{#if d.watch_paused}<button class="btn sm" id="resume-watch" onclick={(e) => resumeWatch(e.currentTarget)}>Resume now</button>{/if}<button class="btn sm" id="run-ingest" disabled={d.busy || !!d.paused || !d.can_run} title={d.can_run ? null : "The scheduler is off (kranto serve --no-scheduler)"} onclick={(e) => runNow(e.currentTarget)}>Run ingest now</button>{/snippet}
        {#snippet section(s)}
          {#if s.id === "watching"}
            {#snippet state()}{#if d.paused}<Mark name="held" colour="amber" word={"Paused: " + d.paused} />{:else if d.watch_paused}<Mark name="held" colour="amber" word={watchPaused(d.watch_paused) + "; it resumes by itself"} />{:else if d.running === "ingest"}<Mark name="running" colour="blue" word={"Reading sources…" + (d.ingest_progress ? " " + readingWords(d.ingest_progress) : "")} />{:else if d.busy}<Mark name="running" colour="blue" word={"Running a job" + (d.running ? ` (${d.running})` : "")} />{:else}<Mark name="waiting" colour="green" word={"Watching" + (nextAt ? " · next read " + nextRead(nextAt) : "")} />{/if}{/snippet}
            {#snippet models()}<a href="#/settings/models">Settings › Watching › Models</a>{/snippet}
            <Kv rows={[["State", state], ["API key", d.api_key ? "set" : "missing"], ["Models", models]]} />
          {/if}
        {/snippet}
      </Pane>
    {/if}
  {:else if !host}
    {@render gone("Watching's health needs the server, which is not answering.")}
  {:else if !d}
    <div class="pane-in"><Loading error={a?.error} /></div>
  {:else if k === "calls"}
    {@const b = d.budget}
    {@const used = capUsed(d)}
    {@const st = d.alarm ? (["warn", "red", "Past the alarm line"] as const) : SET_ST.ok}
    <Pane title={`Model calls in ${d.month}`} lede="Ingest, the map and idea cards, through your model key." sections={[{ id: "used", w: "Used" }]}>
      {#snippet kind()}<Glyph name={st[0]} colour={st[1]} word={st[2]} />{" health · model calls"}{/snippet}
      {#snippet section()}
        <p class="big">{#if d.tokens_month}{@render tok(d.tokens_month)}{:else}None yet{/if}<span class="muted small">{b.monthly_usd == null ? " · no cap" : ` · ${Math.round(used)}% of the monthly cap`}</span></p>
        {#if b.monthly_usd != null}<div class="meter" role="img" aria-label={`${Math.round(used)}% of the monthly cap used`}><span style={`width:${used}%` + (d.alarm ? ";background:var(--red)" : "")}></span></div>{/if}
        {#if d.alarm}<div class="note c-red" role="status"><Icon name="warn" /><div>{`Spend has passed ${Math.round(b.alarm_fraction * 100)}% of the monthly cap. Model calls stop when it is reached.`}</div></div>
        {:else}<p class="muted small mt">{b.monthly_usd == null ? "No monthly cap is set. " : "Model calls for ingest, the map and idea cards stop at the cap. "}<a href="#/settings/spend">Spend and caps</a></p>{/if}
      {/snippet}
    </Pane>
  {:else if k === "items"}
    <Pane title="Items in the last 7 days" lede="What happened to each item the sources gave." sections={[{ id: "outcomes", w: "Outcomes" }]}>
      {#snippet kind()}<Glyph name={SET_ST.ok[0]} colour={SET_ST.ok[1]} word={SET_ST.ok[2]} />{" health · items"}{/snippet}
      {#snippet section()}
        {#if Object.keys(d.outcomes).length}<Kv rows={Object.entries(d.outcomes).sort().map(([x, n]) => [words(x), String(n), "mono"])} /><p class="muted small mt">prefiltered: skipped without a model call (not similar to any topic). gated: judged but below the signal threshold. skipped: Kranto chose not to contribute. duplicate: the same URL was already judged; no model call. near duplicate: the same text was judged recently at a different URL; no model call.</p>
        {:else}<p class="muted">No items processed yet.</p>{/if}
      {/snippet}
    </Pane>
  {:else if k === "from"}
    <Pane title="Where new observations come from" lede="How each kept observation was admitted." sections={[{ id: "table", w: "Admitted by" }]}>
      {#snippet kind()}<Glyph name={SET_ST.ok[0]} colour={SET_ST.ok[1]} word={SET_ST.ok[2]} />{" health · library"}{/snippet}
      {#snippet section()}
        {#if d.exploration.length}
          <div class="tw"><table><thead><tr><th>Admitted by</th><th class="n">Observations</th><th class="n">Mean signal</th><th class="n">In cross-source clusters</th></tr></thead><tbody>{#each d.exploration as e (e.admitted_by)}<tr><td>{words(e.admitted_by)}</td><td class="n">{String(e.n)}</td><td class="n">{n3(e.mean_signal)}</td><td class="n">{e.in_cross_source == null ? "–" : `${e.in_cross_source} (${pct(e.in_cross_source / e.n)})`}</td></tr>{/each}</tbody></table></div>
          <p class="muted small mt">{"topic: similar enough to a topic to pass the prefilter. exploration: below the prefilter but judged anyway, a random sample kept so the library does not narrow onto your topics' wording. no topics: from broad sources and approved wildcards, which skip the prefilter. Cross-source clusters are from the latest map" + (d.exploration[0]?.in_cross_source == null ? "; there is no map yet." : ".")}</p>
        {:else}<p class="empty">No observations yet.</p>{/if}
      {/snippet}
    </Pane>
  {:else if k === "memory"}
    {@const m = d.memory}
    {@const st = memSt(m.level)}
    <Pane title="Memory" lede="What Kranto uses, and the caps it runs under." sections={[{ id: "use", w: "Use and caps" }]}>
      {#snippet kind()}<Glyph name={st[0]} colour={st[1]} word={st[2]} />{" health · memory"}{/snippet}
      {#snippet section()}
        <p class="big">{memoryWords(m)}</p>
        {#if m.level === "high"}<div class="note c-amber" role="status"><Icon name="warn" /><div>{m.words}</div></div>{/if}
        <Kv rows={[["Kranto", mb(m.used_mb), "mono"], ["The server alone", mb(m.rss_mb), "mono"], ["High mark (slows down above)", mb(m.high_mb), "mono"],
          ["At most (the biggest process is ended)", mb(m.max_mb), "mono"], ["Where", m.group || "no group", "mono"]]} />
        <p class="muted small mt">{m.level === "uncapped" ? "No cap is set: Kranto runs here without systemd's memory limits. " : "The caps are kranto.service's (or the scope Kranto made for itself). "}To change them: <span class="mono">systemctl --user edit Kranto</span>, then <span class="mono">[Service]</span> with <span class="mono">MemoryHigh=</span> and <span class="mono">MemoryMax=</span> (docs/memory.md).</p>
      {/snippet}
    </Pane>
  {:else if k === "retention"}
    {@const ret = d.retention}
    <Pane title="Retention" lede={ret.line} sections={[{ id: "how", w: "How long" }]}>
      {#snippet kind()}<Glyph name={SET_ST.ok[0]} colour={SET_ST.ok[1]} word={SET_ST.ok[2]} />{" health · retention"}{/snippet}
      {#snippet section()}
        {#snippet last()}{#if ret.last}{@const m = runSt(ret.last.status)}<Mark name={m[0]} colour={m[1]} word={m[2]} />{" " + stamp(ret.last.finished_at)}{ret.last.summary && ret.last.summary.expired != null ? `: ${ret.last.summary.expired} expired, ${ret.last.summary.rollups} rollups written` : ""}{ret.last.error ? " " + ret.last.error : ""}{:else}never{/if}{/snippet}
        <p class="small">Observations are compacted into weekly <a href="#/library/rollups">rollups</a> once they reach their retention age, and removed with the model calls that hold their source text. Every removal is recorded.</p>
        <Kv rows={[["Kept for", ret.line], ["Last compaction", last], ["Rollups", `${ret.rollups} (in place of ${ret.replaced} observations)`, "mono"],
          ["Rows removed", (ret.removed.map((t) => `${t.table_name} ${t.n}`).join(" · ") || "none") + (ret.last_purge ? ` (last ${ret.last_purge.slice(0, 10)})` : ""), "mono"]]} />
      {/snippet}
    </Pane>
  {:else if k === "run"}
    {@const x = d.runs.find((y) => y.run_uuid === v)}
    {#if !x}{@render gone("This run is no longer among the last ones.")}
    {:else}
      {@const m = runSt(x.status)}
      {@const sm = x.summary || {}}
      {@const t = x.tokens || sm.tokens}
      <Pane title={`${x.kind} ${stamp(x.finished_at || x.started_at)}`} lede={x.error || (sm.contributed != null ? plural(sm.contributed, "new observation") : null)}
        sections={[{ id: "facts", w: "Run" }, ...(hasDetail(x) ? [{ id: "detail", w: "Detail" }] : [])]}>
        {#snippet kind()}<Glyph name={m[0]} colour={m[1]} word={m[2]} />{` run · ${x.kind} · ${m[2].toLowerCase()}`}{/snippet}
        {#snippet section(s)}
          {#if s.id === "facts"}
            {#snippet result()}<Mark name={m[0]} colour={m[1]} word={m[2]} />{/snippet}
            {#snippet used()}{@render tok(t)}{/snippet}
            <Kv rows={[["Job", x.kind], ["Result", result], ["Started", stamp(x.started_at)], ["Finished", stamp(x.finished_at) || "–"], ["New", sm.contributed != null ? String(sm.contributed) : "–"], ["Tokens", t ? used : "–"]]} />
            <p class="small"><a id="run-trace" href={"#/afk/" + encodeURIComponent(x.run_uuid) + "/trace"}>Its trace ›</a>{" "}<span class="muted">each model call's request and answer, redacted</span></p>
          {:else}
            {@const o = sm.overrides}
            {#if x.error}<p class="small">{x.error}</p>{/if}
            {#if x.kind === "compact" && sm.expired}<p class="small">{`${sm.expired} expired, ${sm.rollups} rollups`}</p>{/if}
            {#if o && o.rated}<p class="small mono">{`override ${o.set}/${o.rated} (${o.lifted} lifted, ${o.refused} refused)`}</p>{/if}
            {#if sm.sponsored || sm.sponsor_links}<p class="small mono">{`sponsors/ads: ${sm.sponsored || 0} items, ${sm.sponsor_links || 0} links`}</p>{/if}
            {#if (sm.sources || []).length}
              <details class="fold" id={"run-" + x.run_uuid} open={OPENED.has("run-" + x.run_uuid)} ontoggle={keepOpen("run-" + x.run_uuid)}><summary class="small">{plural((sm.sources || []).length, "source")}</summary><ul class="ctx">{#each sm.sources || [] as src, i (i)}<li><span>{src.label}</span><span class="n" title={src.fetch_error || null}>{src.not_reached ? "not reached"
                : src.waiting_until ? (src.failing_runs ? "backing off until " : "paced until ") + nextRead(src.waiting_until)
                  : src.fetch_state === "paced" ? pacedWord(src.retry_at) : src.fetch_error ? cut(src.fetch_error, 70) : `${src.judged} judged, ${src.contributed} kept, ${src.prefiltered} prefiltered`}</span></li>{/each}</ul></details>
            {/if}
          {/if}
        {/snippet}
      </Pane>
    {/if}
  {:else if k === "msg"}
    {@const m = d.messages.find((y) => String(y.id) === v)}
    {@const dl = m ? d.deliveries[String(m.id)] : null}
    {#if !m}{@render gone("No such message among the recent ones.")}
    {:else}
      {#snippet delivery()}<section class="sec" id="s-delivery"><h3>Delivery</h3>{#if dl}<p class="small mono">{dl.sent.length ? "sent to " + dl.sent.join(", ") : "not sent"}{dl.failed ? `; ${dl.failed} failed attempt${dl.failed === 1 ? "" : "s"}, last: ${cut(dl.last_error || "", 120)}` : ""}</p>{:else}<p class="muted small">{d.delivery_status}</p>{/if}</section>{/snippet}
      <MessagePane {m} health more={delivery} />
    {/if}
  {:else if k === "err"}
    {@const e = d.errors[Number(v)]}
    {#if !e}{@render gone("No such error among the last 7 days'.")}
    {:else}
      <Pane title={cut(e.example || "error", 160)} lede={`${plural(e.n, "time")} in the last 7 days, the last on ${(e.last_at || "").slice(0, 10)}.`} sections={[{ id: "facts", w: "Error" }]}>
        {#snippet kind()}<Glyph name="x" colour="red" word="Model error" />{" health · model error · " + e.purpose}{/snippet}
        {#snippet section()}<Kv rows={[["Purpose", e.purpose], ["HTTP", e.http_status ? String(e.http_status) : "–"], ["Count", String(e.n)], ["Last", stamp(e.last_at)], ["Example", e.example || "–"]]} />{/snippet}
      </Pane>
    {/if}
  {:else if k === "dec"}
    {@const x = d.decisions.find((y) => String(y.decision_id) === v)}
    {@const s = d.strike}
    {#if !x}{@render gone("No such decision among the recent ones.")}
    {:else}
      <Pane title={x.title} lede={x.detail || null} right={stamp(x.decided_at)} sections={[{ id: "decision", w: "Decision" }, { id: "gate", w: "The gate" }]}>
        {#snippet kind()}{#if x.promoted}<Glyph name="check" colour="blue" word="Promoted" />{:else}<Glyph name="skipped" colour="grey" word="Not promoted" />{/if}{` strike gate · ${x.origin} · ${x.promoted ? "promoted" : words(x.reason)}`}{/snippet}
        {#snippet acts()}{#if x.message_id}<a class="btn sm" href={href("settings/health", { sel: "emsg:" + x.message_id })}>Open its message</a>{/if}{/snippet}
        {#snippet section(sec)}
          {#if sec.id === "decision"}<Kv rows={[["Score", n3(x.score) + (x.threshold != null ? " against " + n3(x.threshold) : ""), "mono"], ["Result", x.promoted ? "promoted to a message" : words(x.reason)], ["Subject", x.subject_key, "mono"], ["Candidate", "#" + x.candidate_id + ", " + stamp(x.created_at)]]} />
          {:else}<p class="muted small">{`Every candidate is decided once, with a reason. Thresholds: card ${n3(s.min_card_score)}, burst ${n3(s.min_burst_score)}, watch ${n3(s.min_watch_score)}; quiet for ${s.refractory_days} days per subject after a strike; at most ${s.max_per_week} per 7 days; none before ${s.warmup_snapshots} map snapshots.`}</p>{/if}
        {/snippet}
      </Pane>
    {/if}
  {:else}
    {@render gone("Nothing to show here.")}
  {/if}
</Detail>
