<script lang="ts">
  // Needs you's rows (WORKSPACE.md 8;): a row for each thing that waits on
  // you, one line each: the state in a word, the title, at most one fact, the age, one verb. It
  // opens with the one thing (Next, by rule: needs.ts nextOf), the page's only primary; every
  // other row's verb is a plain button (R3). At most seven rows with a verb before scrolling (five
  // on a phone, R4): a group past them starts folded to its heading and its count, a long group
  // shows its first rows and Show all; Decide starts folded (the owner's D-2). Opening a group is
  // remembered per viewer (fold.svelte.ts). A row's quiet verbs are in its pane, which shows the
  // row's real object (an idea, a source) or a pane of its own (the proposals, a message, the
  // queue: sel=p, m, r). The idea cards waiting are one row (their verbs are on Ideas). The
  // update's Restart is shared with Settings › System › Updates.
  import { SvelteSet } from "svelte/reactivity";
  import Glyph from "../../ui/Glyph.svelte";
  import Group from "../../ui/Group.svelte";
  import Row from "../../ui/Row.svelte";
  import Next from "../../ui/Next.svelte";
  import MarkEmpty from "../../ui/MarkEmpty.svelte";
  import { ago, cut, dt, plural } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { href } from "../../lib/router";
  import { CARD_VERBS } from "../../lib/app/data";
  import { app } from "../../lib/shell.svelte";
  import { selHref } from "../../ui/settings";
  import { sendError } from "../../ui/sendFeedback";
  import type { Activity } from "../../api/types.gen";
  import { ACT_PATH, bandOf } from "../../lib/activity";
  import IncidentBand from "../../shell/IncidentBand.svelte";
  import { dismissIncident } from "../../shell/incidents";
  import { gone, lineOf, PREPARED_API, waitingItems, whoOf, whyOf, type Prepared } from "../../lib/prepared";
  import { actPrepared, openPrepared, refusedPrepared } from "../../ui/prepared.svelte";
  import { openAsk } from "../../features/cubverbs";
  import { put, read } from "../../lib/reads.svelte";
  import { tagOf, UPD_API } from "../settings/updates";
  import { candidateRead, confirmWords, promoteRow, PROMOTE_API, type Candidate } from "./promote";
  import { confirmThen } from "../../ui/dialog.svelte";
  import { setSource } from "../settings/sourceverbs";
  import { activityRows, askedBy, isFix, preparedRows, type HomeRow } from "./home";
  import { dispatchNew, messageListed, msgMark, nextOf, projectProposed, reviewCount, termRead, termWaits, updateOffer, waitingCards,
    type Want, type Host, type TermWait, type Today, type TodayTopic } from "./needs";

  let { view, t, host, n, loading, cubs = [] }: {
    view: View; t: Today | null; host: Host | null; n: number; loading: boolean;
    /** the cubs' asks, among the rows */
    cubs?: HomeRow[];
    /** grouped by the verb: the only way Needs you draws now */
    byVerb?: boolean;
  } = $props();
  const sel = (code: string): string => selHref(view.w, code);
  // what the activity read adds: a failing kind's Fix row; a run that
  // stopped for you whose verb no row here offers
  const act = $derived.by(() => {
    void view.tick;
    return read<Activity>(ACT_PATH, 5000).data; // the page server's read, the top bar's too
  });
  // one problem, one card: Kranto's own incident is the band (as on the home: on a phone it
  // stays above the console's sheet), never a Fix row as well, and never the one thing; a
  // feature's is Fix's first row. A prepared item is its own row, never its waiting run too
  const acts = $derived(activityRows(act, cubs, { band: true, prepared: true }));
  const incs = $derived(bandOf(act));
  const prows = $derived.by(() => {
    void view.tick;
    return host ? preparedRows(waitingItems(read<{ prepared: Prepared[] }>(PREPARED_API, 10000).data?.prepared)) : [];
  });
  // what is broken (a refused key, a failing kind) leads Fix
  const actFix = $derived(acts.filter(isFix));
  const actOf = (v: string): HomeRow[] => acts.filter((r) => !isFix(r) && actVerb(r) === v);
  const actVerb = (r: HomeRow): string => (/^(Confirm|Apply|Approve|Update)/.test(r.verb) ? "approve" : /^Answer/.test(r.verb) ? "answer" : "review");
  const cards = $derived.by(() => {
    void view.tick;
    return waitingCards();
  });
  const proposed = $derived(t ? t.topics.filter((x) => x.proposed) : []);
  // the project topics' proposals: one row for all of them (the owner's O-3)
  const pp = $derived(projectProposed(t));
  // a run's "ingest run failed" message, one a run, is folded into the incident that says it
  // and a refused key's alarm (dedup auth:<provider>:…) is the incident's
  const msgs = $derived(t ? t.messages.filter(messageListed(act)) : []);
  const failing = $derived(t ? t.sources_failing || [] : []);
  // the sources your downvotes recommend removing (the server's source rule,): Remove
  // or Keep, never removed without your click
  const removing = $derived(t ? t.sources_to_remove || [] : []);
  const rev = $derived.by(() => {
    void view.tick;
    return reviewCount(host);
  });
  const tw = $derived.by(() => {
    void view.tick;
    return termWaits(termRead().data);
  });
  /** a session's subject: its page, and its row's sel= code where it has one */
  const TERMSEL: Record<string, [string, string]> = { idea: ["i", "ideas/"] };
  const disp = $derived.by(() => {
    void view.tick;
    return dispatchNew(host, t);
  });
  const upd = $derived(host?.update || null);
  const offer = $derived(updateOffer(upd));
  // Promote to stable (REL): the gate's candidate, on the maintainer's install only
  const cand = $derived.by(() => {
    void view.tick;
    return candidateRead(host);
  });
  const prow = $derived(promoteRow(cand));
  /** Promote: the confirm reads back what it carries; only its Promote writes */
  function promote(btn: HTMLElement, c: Candidate): void {
    const w = confirmWords(c);
    confirmThen(w.title, w.body, "Promote", () => {
      const L = app();
      if (!L) return;
      return L.act(btn, () => L.api(PROMOTE_API, { tag: c.tag }), (r) => {
        put(UPD_API, r);
        L.toast(`Promoting ${String(c.to || "").replace(/^v/, "")}: the gate cuts it, runs rc_check and releases it. This row says each step.`);
        L.render();
      });
    });
  }

  // by the verb you will use: a cub's ask, an assistant's proposals and
  // proposed sources Approve; the queue, cards, messages Review; failing sources Fix; a source
  // your grades recommend removing Decide. Fix first: a refused key or a failing kind
  // outranks every chore
  const VERBS: [string, string][] = [["fix", "Fix"], ["answer", "Answer"], ["decision", "Decide"], ["approve", "Approve"], ["review", "Review"], ["update", "Update"]];

  /** one row of the page: what it draws (kind and its object), what it asks of you and when it came
   * (the one thing's rule), and whether it counts (the promote row counts only while it asks) */
  type Item = { key: string; kind: string; want?: Want; at: number | null; counts?: boolean;
    r?: HomeRow; w?: TermWait; x?: TodayTopic; msg?: Today["messages"][number];
    f?: Today["sources_failing"][number]; rm?: Today["sources_to_remove"][number] };
  const hrow = (kind: string, want?: Want) => (r: HomeRow): Item => ({ key: r.key, kind, r, want, at: r.at ?? null });
  const items = $derived.by((): Record<string, Item[]> => ({
    fix: [...actFix.map(hrow("act", "fix")), ...failing.map((f): Item => ({ key: "s" + f.id, kind: "failing", f, want: "fix", at: null }))],
    answer: [...actOf("answer").map(hrow("act"))],
    decision: [...removing.map((rm): Item => ({ key: "sr" + rm.id, kind: "remove", rm, want: "decision", at: null }))],
    // an item whose verb left Kranto is never the one thing: its only button is Dismiss
    approve: [...prows.map((r) => hrow("prep", gone(r.prepared!) ? undefined : "approve")(r)), ...cubs.map(hrow("cub", "approve")), ...actOf("approve").map(hrow("act")),
      ...tw.map((w): Item => ({ key: "t" + w.s.tid, kind: "term", w, at: null })),
      ...proposed.map((x): Item => ({ key: "p" + x.id, kind: "proposed", x, at: null })), ...(pp.n ? [{ key: "pproj", kind: "pproj", at: null }] : [])],
    review: [...(rev ? [{ key: "r", kind: "review", at: null }] : []), ...actOf("review").map(hrow("act")),
      ...(cards.length ? [{ key: "cards", kind: "cards", at: null }] : []), ...(disp.length ? [{ key: "dispatches", kind: "dispatch", at: null }] : []),
      ...msgs.map((msg): Item => ({ key: "m" + msg.id, kind: "message", msg, at: dt(msg.created_at) }))],
    update: [...(prow && cand ? [{ key: "promote", kind: "promote", at: null, counts: !!prow.counts }] : []), ...(upd && offer ? [{ key: "update", kind: "update", at: null }] : [])],
  }));
  // the one thing: Kranto's own trouble is the band, so never a candidate (acts leaves it out)
  const nx = $derived(nextOf(Object.values(items).flat().filter((x): x is Item & { want: Want } => !!x.want)));
  const others = (xs: Item[]): Item[] => xs.filter((x) => x.key !== nx?.key);
  const counted = (xs: Item[]): number => xs.filter((x) => x.counts !== false).length;
  const total = $derived(Object.values(items).reduce((a, xs) => a + counted(xs), 0));

  // at most seven rows with a verb before scrolling, five on a phone (R4)
  const phone = typeof matchMedia === "function" && matchMedia("(max-width: 759px)").matches;
  const BUDGET = phone ? 5 : 7;
  const opened = new SvelteSet<string>(); // Show all, for this page's life
  /** each group's start (folded or open) and how many rows it shows before Show all */
  const plan = $derived.by((): Record<string, { start: boolean; cap: number }> => {
    let left = BUDGET - (nx ? 1 : 0);
    const out: Record<string, { start: boolean; cap: number }> = {};
    for (const [v] of VERBS) {
      const k = others(items[v] || []).length;
      if (!k) continue;
      const start = v === "decision" || left <= 0;
      const cap = start ? k : Math.max(left, 1);
      out[v] = { start, cap };
      if (!start) left -= Math.min(k, cap);
    }
    return out;
  });
  const shown = (key: string, xs: Item[], cap: number): Item[] => (opened.has(key) || xs.length <= cap ? xs : xs.slice(0, cap));

  /** Watch the n ticked: the scout's close matches for a topic, watched from its row in one
   * request */
  function watchProposed(btn: HTMLElement, x: TodayTopic): void {
    const L = app();
    if (!L) return;
    void L.act(btn, () => L.api("/api/sources/approve", { ids: x.proposed_ticked, topic: x.id }), () => {
      L.afkStale("/api/today", "/api/sources", "/api/topics"); void L.loadHost(); L.render();
      L.toast(`Watching ${plural(x.proposed_ticked.length, "more source")} for ${x.name}. Their first fetch is the next ingest run.`);
    });
  }
  /** Remove a source the rule recommends removing: the house confirm reads it back, then the
   * click retires it (source.retire; Undo watches it again) */
  function removeSource(btn: HTMLElement, r: Today["sources_to_remove"][number]): void {
    confirmThen(`Remove ${r.label}?`, [`Stop watching ${r.label}. Its observations stay; the next ingest run does not read it.`,
      `${r.down} of its ${r.down + r.up} graded posts were not useful in ${r.window_days} days. Watch again (on its page) undoes it.`], "Remove",
    () => void setSource(btn, { id: r.id, label: r.label, topics: r.topics.length }, "retired"));
  }
  /** Keep a source the rule recommends removing (source.keep): the row goes, and only downvotes
   * given from now count toward asking again */
  function keepSource(btn: HTMLElement, r: Today["sources_to_remove"][number]): void {
    const L = app();
    if (!L) return;
    void L.act(btn, () => L.api(`/api/sources/${r.id}/keep`, {}), () => {
      L.afkStale("/api/today", "/api/sources", "/api/grades/summary"); L.render();
      L.toast(`Kept ${r.label}. Kranto asks again only if ${r.down >= 3 ? "three" : "more"} more of its posts are downvoted.`);
    });
  }
  /** the one thing's muted line: what it is and who raised it, and when */
  const kindLine = (x: Item): string => {
    const when = x.at ? (ago(x.at) === "now" ? ", just now" : `, ${ago(x.at)} ago`) : "";
    if (x.kind === "prep") return `prepared by ${whoOf(x.r!.prepared!)}${when}`;
    if (x.kind === "cub") return askedBy(x.r!, when);
    if (x.kind === "failing") return "a source failing run after run";
    if (x.kind === "act") return "a run that keeps failing";
    return "your grades on a source";
  };
</script>

<!-- a row's verb: a plain button in a row, the primary in the one thing (R3) -->
{#snippet verb(x: Item, main: boolean)}
  {@const pc = main ? " primary" : ""}
  <!-- a prepared item: its yes, and Dismiss beside it as on its page's line, naming
       what it would act on -->
  {#if x.kind === "prep"}{@const p = x.r!.prepared!}<span class="acts2"><button type="button" class={"btn sm" + pc} data-prepared-act={p.uuid} title={x.r!.verb} onclick={() => openPrepared(p)}>{x.r!.verb}</button>{#if !gone(p)}<button type="button" class="btn sm quiet" data-prepared-dismiss={p.uuid} aria-label={`Dismiss ${lineOf(p)}`} title="Dismiss: put it away, nothing happens" onclick={() => void actPrepared(p, "dismiss")}>Dismiss</button>{/if}</span>
  {:else if x.kind === "cub"}{#if x.r!.ask}{@const a = x.r!.ask}<button type="button" class={"btn sm" + pc} data-act="ask-open" title={x.r!.verb} onclick={(e) => openAsk(a, e.currentTarget)}>{x.r!.verb}</button>{:else}<a class={"btn sm" + pc} href={x.r!.href} title={x.r!.verb}>{x.r!.verb}</a>{/if}
  {:else if x.kind === "act"}<a class={"btn sm" + pc} href={x.r!.href} title={x.r!.verb}>{x.r!.verb}</a>{#if x.r!.dismiss}{@const id = x.r!.dismiss}<button type="button" class="btn sm quiet" data-dismiss={id} title="Put it away until it happens again" onclick={(e) => dismissIncident(id, e.currentTarget)}>Dismiss</button>{/if}
  {:else if x.kind === "failing"}<a class={"btn sm" + pc} href={"#/settings/sources/" + x.f!.id} title="Fix">Fix</a>
  {:else if x.kind === "remove"}{@const r = x.rm!}<span class="acts2"><button type="button" class={"btn sm" + pc} data-verb="source.retire" data-act="remove-source" title={`Remove ${r.label}: stop watching it (its observations stay)`} onclick={(e) => removeSource(e.currentTarget, r)}>Remove</button><button type="button" class="btn sm quiet" data-verb="source.keep" data-act="keep-source" title="Keep it: only downvotes from now count toward asking again" onclick={(e) => keepSource(e.currentTarget, r)}>Keep</button></span>{/if}
{/snippet}

{#snippet promoteRowS()}
  {#if prow && cand}
    {#snippet press()}{#if prow.press}<button class="btn sm" id="promote-stable" title="Promote to stable" onclick={(e) => promote(e.currentTarget, cand)}>Promote to stable</button>{:else if prow.kind === "failed"}<a class="btn sm" id="promote-log" href="#/settings/updates" title="See the log">See the log</a>{/if}{/snippet}
    <Row title={prow.title} href="#/settings/updates" meta={prow.detail[0] || null} end={press}>
      {#snippet st()}{#if prow.kind === "blocked" || prow.kind === "failed"}<Glyph say name="warn" colour="red" word={prow.kind === "failed" ? "Stopped" : "Blocked"} />{:else if prow.kind === "promoted"}<Glyph say name="check" colour="green" word="Stable" />{:else}<Glyph say name="dot" colour="blue" word={prow.kind === "promoting" ? "Promoting" : "Stable?"} />{/if}{/snippet}
    </Row>
  {/if}
{/snippet}

<!-- the Updates row says the version: it is about versions (the lint's allowlist says so) -->
{#snippet updateRowS()}
  {#if upd && offer === "bad" && upd.broke && upd.state === "rolled_back"}
    <!-- the post-update self-check (RCA D1): a page of the new version failed on this data -->
    {#snippet send()}{#if upd.broke!.error_id}<button class="btn sm" id="upd-send-error" title={`Feedback with the error's report (error ${upd.broke!.error_id}), shown before anything is sent`} onclick={() => sendError(upd.broke!.error_id!, `${upd.to} broke on my data and was rolled back`)}>Send this error</button>{/if}{/snippet}
    <Row title={`${upd.to} broke on your data and was rolled back`} href="#/settings/updates" meta="nothing in your data was undone" end={send}>
      {#snippet st()}<Glyph say name="warn" colour="red" word="Rolled back" />{/snippet}
    </Row>
  {:else if upd && offer === "bad"}
    {#snippet again()}<button class="btn sm" title="Try again" onclick={(e) => void app()?.updApply(e.currentTarget, { to: tagOf(String(upd.to)) })}>Try again</button>{/snippet}
    <Row title={`Update to ${upd.to} was ${upd.state === "failed" ? "not finished" : "rolled back"}`} href="#/settings/updates" meta={upd.reason ? cut(upd.reason, 90) : upd.state === "failed" ? "Settings › System › Updates says what to do" : "nothing in your data was undone"} end={upd.can_apply && upd.state !== "failed" ? again : undefined}>
      {#snippet st()}<Glyph say name="warn" colour="red" word="Rolled back" />{/snippet}
    </Row>
  {:else if upd && offer === "offer"}
    {#snippet restart()}{#if upd.can_apply}<button class="btn sm" id="upd-apply" title="Restart to update" onclick={(e) => void app()?.updApply(e.currentTarget)}>Restart to update</button>{:else}<a class="btn sm" href="#/settings/updates" title="This Kranto updates from the command line: kranto update">How to update</a>{/if}{/snippet}
    <Row title={`Kranto ${upd.available} is ready`} href="#/settings/updates" meta={upd.can_apply ? "installs when you restart" : "installs from the command line"} end={restart}>
      {#snippet st()}<Glyph say name="dot" colour="blue" word="Update" />{/snippet}
    </Row>
  {/if}
{/snippet}

{#snippet item(x: Item)}
  {#snippet end()}{@render verb(x, false)}{/snippet}
  {#if x.kind === "prep"}
    {@const r = x.r!}
    <Row title={r.title} href={r.href} meta={r.meta} age={r.age} {end}>
      {#snippet st()}<Glyph say name="waiting" colour="violet" word="Prepared" />{/snippet}
    </Row>
    {#if refusedPrepared[r.prepared!.uuid]}<li class="gempty" role="alert" data-refused={r.prepared!.uuid}><span class="c-amber">{refusedPrepared[r.prepared!.uuid]}</span></li>{/if}
  {:else if x.kind === "cub"}
    {@const r = x.r!}
    <Row title={r.title} href={r.href} meta={r.meta || null} age={r.age} {end}>
      {#snippet st()}<Glyph say name="waiting" colour="amber" word="Waits" />{/snippet}
    </Row>
  {:else if x.kind === "act"}
    {@const r = x.r!}
    <Row title={r.title} href={r.href} meta={r.meta} {end}>
      {#snippet st()}{#if r.tone === "red"}<Glyph say name="x" colour="red" word="Failing" />{:else}<Glyph say name="waiting" colour="amber" word="Stopped" />{/if}{/snippet}
    </Row>
  {:else if x.kind === "failing"}
    {@const f = x.f!}
    <Row sel={"s" + f.id} title={`${f.label} failed ${f.failing_runs} runs in a row`} href={"#/settings/sources/" + f.id} meta={f.error ? cut(f.error, 80) : null} {end}>
      {#snippet st()}<Glyph say name="x" colour="red" word="Failing" />{/snippet}
    </Row>
  {:else if x.kind === "remove"}
    {@const r = x.rm!}
    <Row sel={"sr" + r.id} title={`Remove ${r.label}?`} href={"#/settings/sources/" + r.id} meta={`${r.down} of its ${r.down + r.up} graded posts were not useful`} {end}>
      {#snippet st()}<Glyph say name="waiting" colour="amber" word="Your grades" />{/snippet}
    </Row>
  {:else if x.kind === "term"}
    {@const w = x.w!}
    {@const sub = w.s.subject}
    {@const to = TERMSEL[sub.kind]}
    {#snippet open()}<button class="btn sm" data-act="term" title="Open in Claude Code: Confirm or Dismiss above the terminal" onclick={() => app()?.openClaude(sub.kind, sub.id, w.s.title)}>Open</button>{/snippet}
    <Row sel={to ? to[0] + sub.id : null} title={w.n === 1 ? "Claude Code proposes: " + w.first : `Claude Code proposes ${w.n} changes`} href={to ? href(to[1] + sub.id) : null} meta={w.s.title} end={open}>
      {#snippet st()}<Glyph say name="waiting" colour="amber" word="Proposed" />{/snippet}
    </Row>
  {:else if x.kind === "proposed"}
    {@const p = x.x!}
    {@const m = p.proposed_ticked.length}
    {#snippet watch()}{#if m}<button class="btn sm" title={`Watch the ${m} ticked`} onclick={(e) => watchProposed(e.currentTarget, p)}>{`Watch the ${m} ticked`}</button>{:else}<a class="btn sm" href={sel("p" + p.id)} title={`Review all ${p.proposed}`}>{`Review all ${p.proposed}`}</a>{/if}{/snippet}
    <Row sel={"p" + p.id} title={`${plural(p.proposed, "proposed source")} for ${p.name}`} href={sel("p" + p.id)} meta={m ? `${m} close matches` : "none is a close match"} end={watch}>
      {#snippet st()}<Glyph say name="open" colour="amber" word="Proposed" />{/snippet}
    </Row>
  {:else if x.kind === "pproj"}
    {#snippet rv()}<a class="btn sm" href={href("watch/sources", { status: "proposed" })} title="Review them under Proposed">Review</a>{/snippet}
    <Row sel="pproj" title={`${plural(pp.n, "proposed source")} for ${plural(pp.topics, "project topic")}`} href={href("watch/sources", { status: "proposed" })} meta="for topics you watch for a project" end={rv}>
      {#snippet st()}<Glyph say name="open" colour="amber" word="Proposed" />{/snippet}
    </Row>
  {:else if x.kind === "review"}
    {#snippet start()}<a class="btn sm" href="#/review" title="Start">Start</a>{/snippet}
    <Row sel="r" title={`${rev} waiting for a grade, a few seconds each`} href={sel("r")} age="weekly" end={start}>
      {#snippet st()}<Glyph say name="dot" colour="blue" word="Review" />{/snippet}
    </Row>
  {:else if x.kind === "cards"}
    {@const to = href("ideas", { status: "waiting" })}
    {#snippet openIt()}<a class="btn sm" href={to} title={`${CARD_VERBS} each on Ideas`}>Open</a>{/snippet}
    <Row sel="cards" title={`${plural(cards.length, "idea card")} wait${cards.length === 1 ? "s" : ""} for ${CARD_VERBS}`} href={to} age={cards[0] ? ago(cards[0].created) : null} end={openIt}>
      {#snippet st()}<Glyph say name="open" colour="blue" word="Ideas" />{/snippet}
    </Row>
  {:else if x.kind === "dispatch"}
    {@const to = href("ideas", { source: "dispatch", status: "waiting" })}
    {#snippet them()}<a class="btn sm" href={to} title="Review them">Review them</a>{/snippet}
    <Row sel="dispatches" title={`${plural(disp.length, "idea")} from your Parallax dispatches`} href={to} meta="your pitches, kept as written" end={them}>
      {#snippet st()}<Glyph say name="open" colour="blue" word="Ideas" />{/snippet}
    </Row>
  {:else if x.kind === "message"}
    {@const m = x.msg!}
    {@const mk = msgMark(m)}
    {#snippet readIt()}<a class="btn sm" href={sel("m" + m.id)} title="Read it in the pane">Read</a>{/snippet}
    <Row sel={"m" + m.id} title={m.title} href={sel("m" + m.id)} age={ago(dt(m.created_at))} end={readIt}>
      {#snippet st()}<Glyph say name={mk[0]} colour={mk[1]} word={mk[2]} />{/snippet}
    </Row>
  {:else if x.kind === "promote"}{@render promoteRowS()}
  {:else if x.kind === "update"}{@render updateRowS()}{/if}
{/snippet}

{#snippet nextBox(x: Item & { want: Want })}
  {@const r = x.r}
  {@const tone = x.want === "approve" ? "violet" : x.want === "fix" ? "amber" : "blue"}
  {#snippet main()}{@render verb(x, true)}{/snippet}
  {#if x.kind === "prep" && r}<Next kind={kindLine(x)} title={r.title} href={r.href} why={whyOf(r.prepared!, r.verb || "")} details={"prep:" + r.prepared!.uuid} sel={x.key} {tone} act={main} />
  {:else if r}<Next kind={kindLine(x)} title={r.title} href={r.href} why={r.meta || null} sel={x.key} {tone} act={main} />
  {:else if x.kind === "failing"}<Next kind={kindLine(x)} title={`${x.f!.label} failed ${x.f!.failing_runs} runs in a row`} href={"#/settings/sources/" + x.f!.id} why={x.f!.error ? cut(x.f!.error, 90) : null} details={"s" + x.f!.id} sel={x.key} {tone} act={main} />
  {:else if x.kind === "remove"}<Next kind={kindLine(x)} title={`Remove ${x.rm!.label}?`} href={"#/settings/sources/" + x.rm!.id} why={`${x.rm!.down} of its ${x.rm!.down + x.rm!.up} graded posts were not useful.`} details={"s" + x.rm!.id} sel={x.key} {tone} act={main} />{/if}
{/snippet}

<!-- the band is Kranto's own only (a refused model key), and then no Fix row says it again (the
     owner, 2026-10-29: the OpenRouter incident showed twice, as the band and as its row); a
     feature's or a cub's incident is one row, the first of Fix -->
{#if incs.length}<IncidentBand incidents={incs} />{/if}
{#if nx}{@render nextBox(nx)}{/if}
<!-- Needs you: one inbox grouped by the verb you will use -->
{#each VERBS as [v, word] (v)}
  {@const xs = others(items[v] || [])}
  {@const pl = plan[v]}
  {#if xs.length && pl}
    {@const key = "needs:" + v}
    {@const rows = shown(key, xs, pl.cap)}
    {#snippet more()}{#if rows.length < xs.length}<div class="more"><button type="button" class="linkish" data-show-all={v} onclick={() => opened.add(key)}>{`Show all ${xs.length}`}</button></div>{/if}{/snippet}
    <Group id={"ny-" + v} title={word} count={String(counted(xs))} kind="needs words" fold={key} start={pl.start} foot={more}>
      {#each rows as x (x.key)}{@render item(x)}{/each}
    </Group>
  {/if}
{/each}
{#if !total}<MarkEmpty text={"Nothing needs you. Kranto keeps watching." + (loading && !n ? " Reading what Kranto kept…" : "")} />{/if}
