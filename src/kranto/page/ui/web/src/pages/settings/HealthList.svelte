<script lang="ts">
  // Settings › System › Health, the list: what Kranto did (model calls, items, where observations come
  // from, retention), the sources needing a look, then the server's runs, model errors, messages
  // (each with its grade) and the strike gate's decisions.
  import Glyph from "../../ui/Glyph.svelte";
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import Loading from "../../ui/Loading.svelte";
  import Row from "../../ui/Row.svelte";
  import SetRow from "../../ui/SetRow.svelte";
  import Icon from "../../shell/Icon.svelte";
  import { ago, cut, dt, firstSentence, memoryWords, n3, nextRead, plural, readingWords, tokText } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { ui } from "../../lib/shell.svelte";
  import { SET_ST } from "../../ui/settings";
  import { capUsed, HEALTH_API, memSt, msgWord, needingLook, pacedWord, runKind, runSt, runTitle, SOURCES_API, srcSt, stamp, words, type Health, type Source, type Sources } from "./health";

  let { view }: { view: View } = $props();
  // drawn inside Settings › System, its reports start folded to their names and counts
  // (R4: the hundred runs were most of System's words); on its own page, open
  const inSystem = $derived(view.w.r.path[1] === "system");
  const host = $derived(!!ui.facts?.header.host);
  const a = $derived.by(() => {
    void view.tick;
    return host ? read<Health>(HEALTH_API, 20000) : null;
  });
  const srcs = $derived.by(() => {
    void view.tick;
    return host ? read<Sources>(SOURCES_API) : null;
  });
  const d = $derived(a?.data || null);
  const looks = $derived(srcs?.data ? needingLook(srcs.data.sources) : null);
  const outs = $derived(d ? Object.entries(d.outcomes).sort((x, y) => y[1] - x[1]) : []);
  const srcMeta = (s: Source): string => s.status === "paced" ? pacedWord(s.retry_at) + (s.last_error ? " · " + cut(s.last_error, 90) : "")
    : s.status === "failing" ? [s.failing_runs && s.failing_runs > 1 ? `failing ${s.failing_runs} runs in a row` : "failed once", s.backoff_until ? "left alone until " + nextRead(s.backoff_until) : null, s.needs_fixing ? "fix it or remove it" : null, cut(s.last_error || "", 90)].filter(Boolean).join(" · ")
      : s.detail || "";
</script>

{#snippet tag(w: string)}<span class="kindtag">{w}</span>{/snippet}

<List title="Health" crumb="Settings">
  {#if !host}
    <div class="flash" role="status"><Icon name="note" /><div><strong>{"Watching's health needs the server. "}</strong>Its runs, failures, spend and intake are the server's, which is not answering. Start it with kranto up, then reload this page.</div></div>
  {:else if !d}
    <Loading error={a?.error} />
  {:else}
    {@const b = d.budget}
    {@const ret = d.retention}
    {@const s = d.strike}
    {@const mem = d.memory}
    {#if mem && mem.level === "high"}<div class="flash" role="status" id="mem-high"><Icon name="warn" /><div><strong>{"Memory is high. "}</strong>{mem.words}</div></div>{/if}
    <!-- tokens, and how much of the monthly cap is used as a share; the dollars are on Spend -->
    <Group id="h-sum" fold="system:h-sum" start={inSystem} title="Watching" count={String(5 + (mem ? 1 : 0) + (d.ingest_progress ? 1 : 0))} kind="sets">
      {#if d.ingest_progress}<SetRow key="reading" word="Reading now" summary={readingWords(d.ingest_progress)} state={["running", "blue", "Running"]} />{/if}
      <SetRow key="calls" word={`Model calls in ${d.month}`} summary={[d.tokens_month ? tokText(d.tokens_month) : "none yet", b.monthly_usd == null ? "no cap" : `${Math.round(capUsed(d))}% of the monthly cap`].join(" · ")} state={d.alarm ? ["warn", "red", "Past the alarm line"] : SET_ST.ok} />
      <SetRow key="items" word="Items in the last 7 days" summary={outs.length ? outs.slice(0, 4).map(([k, v]) => `${words(k)} ${v}`).join(" · ") : "none processed yet"} state={SET_ST.ok} />
      <SetRow key="from" word="Where new observations come from" summary={d.exploration.length ? d.exploration.map((e) => `${words(e.admitted_by)} ${e.n}`).join(" · ") : "none yet"} state={SET_ST.ok} />
      <SetRow key="retention" word="Retention" summary={[ret.line, ret.last ? "last compaction " + stamp(ret.last.finished_at) : "never compacted"].join(" · ")} state={ret.last && ret.last.status !== "ok" ? SET_ST.warn : SET_ST.ok} />
      {#if mem}<SetRow key="memory" word="Memory" summary={memoryWords(mem)} state={memSt(mem.level)} />{/if}
    </Group>
    {#if looks}
      <Group id="h-src" fold="system:h-src" start={inSystem} title="Sources needing a look" count={String(looks.length)} kind="hrows">
        {#snippet right()}<a href={href("settings/sources", { status: "attention" })}>All sources</a>{/snippet}
        {#each looks as x (x.id)}
          {@const m = srcSt(x.status)}
          <Row sel={"s" + x.id} title={x.label} href={"#/settings/sources/" + x.id} meta={srcMeta(x)} age={x.last_fetch ? ago(dt(x.last_fetch)) : "–"} stw={m}>{#snippet st()}<Glyph name={m[0]} colour={m[1]} word={m[2]} />{/snippet}</Row>
        {/each}
        {#snippet foot()}{#if !looks.length}<p class="more">Every watched source read cleanly on its last fetch.</p>{/if}{/snippet}
      </Group>
    {/if}
    <Group id="h-runs" fold="system:h-runs" start={inSystem} title="Runs" count={String(d.runs.length)} kind="hrows">
      {#snippet right()}<span class="muted">{`the last ${d.runs.length}`}</span>{/snippet}
      {#each d.runs as x (x.run_uuid)}
        {@const m = runSt(x.status)}
        {@const sm = x.summary || {}}
        <Row sel={"erun:" + x.run_uuid} title={cut(runTitle(x as never), 120)}
          meta={[tokText(x.tokens || sm.tokens) || null, (sm.sources || []).length ? plural((sm.sources || []).length, "source") : null].filter(Boolean).join(" · ")}
          age={ago(dt(x.finished_at || x.started_at))} stw={m}>{#snippet st()}<Glyph name={m[0]} colour={m[1]} word={m[2]} />{/snippet}{#snippet num()}{@render tag(runKind(x.kind))}{/snippet}</Row>
      {/each}
      {#snippet foot()}{#if !d.runs.length}<p class="more">No runs yet.</p>{/if}{/snippet}
    </Group>
    <Group id="h-err" fold="system:h-err" start={inSystem} title="Model errors in the last 7 days" count={String(d.errors.length)} kind="hrows">
      {#each d.errors as e, i (i)}
        <Row sel={"eerr:" + i} title={cut(e.example || "", 140) || "error"} meta={[e.http_status ? "HTTP " + e.http_status : null, plural(e.n, "time")].filter(Boolean).join(" · ")} age={ago(dt(e.last_at))} stw={["x", "red", "Model error"]}>{#snippet st()}<Glyph name="x" colour="red" word="Model error" />{/snippet}{#snippet num()}{@render tag(e.purpose)}{/snippet}</Row>
      {/each}
      {#snippet foot()}{#if !d.errors.length}<p class="more">No model error in the last seven days.</p>{/if}{/snippet}
    </Group>
    <Group id="h-msg" fold="system:h-msg" start={inSystem} title="Messages" about={{ text: "Strikes, heartbeats and alarms. Delivery " + d.delivery_status }} count={String(d.messages.length)} kind="hrows hmsgs">
      {#snippet right()}<a href="/feed.xml">Atom feed</a>{/snippet}
      {#each d.messages as m (m.id)}
        {@const w = msgWord(m)}
        <Row sel={"emsg:" + m.id} title={m.title} meta={firstSentence(m.body)} age={ago(dt(m.created_at))} stw={w}>{#snippet st()}<Glyph name={w[0]} colour={w[1]} word={w[2]} />{/snippet}{#snippet num()}{@render tag(m.kind)}{/snippet}</Row>
      {/each}
      {#snippet foot()}{#if !d.messages.length}<p class="more">{(d.delivery_status || "").startsWith("off") ? "No messages. Delivery is off." : "No messages."}</p>{/if}{/snippet}
    </Group>
    <Group id="h-dec" fold="system:h-dec" start={inSystem} title="Strike gate" about={{ text: `At most ${s.max_per_week} a week. Thresholds: card ${n3(s.min_card_score)}, burst ${n3(s.min_burst_score)}, watch ${n3(s.min_watch_score)}.` }} count={String(d.decisions.length)} kind="hrows">
      {#each d.decisions as x (x.decision_id)}
        <Row sel={"edec:" + x.decision_id} title={x.title} meta={[n3(x.score) + (x.threshold != null ? " / " + n3(x.threshold) : ""), x.promoted ? "promoted" : words(x.reason)].join(" · ")} age={ago(dt(x.decided_at))}>{#snippet st()}{#if x.promoted}<Glyph name="check" colour="blue" word="Promoted" />{:else}<Glyph name="skipped" colour="grey" word={words(x.reason || "not promoted")} />{/if}{/snippet}{#snippet num()}{@render tag(x.origin)}{/snippet}</Row>
      {/each}
      {#snippet foot()}{#if !d.decisions.length}<p class="more">No candidates decided yet.</p>{/if}{/snippet}
    </Group>
  {/if}
</List>
