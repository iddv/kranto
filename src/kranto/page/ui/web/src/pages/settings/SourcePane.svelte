<script lang="ts">
  // A source (WORKSPACE.md 2.5; the old page's paneSource): the topics it feeds first (each
  // with Remove, this topic only, and Add to another topic), its facts, fetches, how it is read
  // and what it kept lately; the verbs by its state: Approve and watch (proposed, when its topic is
  // known: the topic page it is open on, else its own), Review, Dismiss; Fetch now, Mute or
  // Unmute, Retire (watched); Watch again (retired); Reconnect (needs login). More than three
  // fold into ⋯ as the old head did. Drawn wherever a source opens (its own route, or sel=s<id>
  // on a topic's page, Today or Health). The mute menu, Approve and
  // Retire are the old module's, shared with Today (and Approve with Add topic) until they move.
  import { addTo, gradeWords, muteMenu, reachWords, removalWords, removeFrom, removeNote, setSource } from "./sourceverbs";
  import { approveSource, dismissSource } from "../topics/proposals";
  import ObsLine from "../library/ObsLine.svelte";
  import Detail from "../../ui/Detail.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Loading from "../../ui/Loading.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import Pane, { type Sec } from "../../ui/Pane.svelte";
  import Row from "../../ui/Row.svelte";
  import Icon from "../../shell/Icon.svelte";
  import Mark from "../../shell/Mark.svelte";
  import { ago, dt, longTime, rel, tokText, tokTitle } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { app, ui } from "../../lib/shell.svelte";
  import type { ObsRow } from "../library/library";
  import { srcSt, type SourcePage } from "./sources.svelte";

  let { view, id }: { view: View; id: string } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const c = $derived.by(() => {
    void view.tick; // each draw may find the reads stale
    return host ? read<SourcePage>("/api/sources/" + id) : null;
  });
  const s = $derived(c?.data || null);
  const watched = $derived(s?.review === "approved");
  const graded = $derived(!!s && (watched || s.review === "retired"));
  const recent = $derived.by(() => {
    void view.tick;
    return s && graded ? read<{ results: ObsRow[]; total: number }>(`/api/observations?source=${s.id}&limit=5&sort=new`, 60000) : null;
  });
  // the topic a proposal is approved for: the topic page it is open on, else its own
  const tid = $derived.by((): string | number | null => {
    const node = view.w.node || "";
    // with the doors, a topic's sources are Watch › Sources with ?topic=
    return /^topics\/[^/]+/.test(node) ? (node.split("/")[1] as string) : view.w.r.q.topic || s?.topics[0]?.id || null;
  });
  const topicName = (t: string | number): string | undefined =>
    ((app()?.host()?.topics as { id: number; name: string }[] | undefined) || []).find((x) => String(x.id) === String(t))?.name;

  /** a verb of the head: a link, or a press with its button (null from ⋯'s menu) and its anchor */
  interface Act {
    label: string;
    cls: string;
    id?: string;
    title?: string | null;
    href?: string;
    run?: (btn: HTMLElement | null, anchor: HTMLElement) => void;
  }
  const acts = $derived.by((): Act[] => {
    if (!s) return [];
    const L = app(), out: Act[] = [];
    if (!L) return out;
    if (s.review === "proposed") {
      const t = tid;
      if (t != null) out.push({ label: "Approve and watch", cls: "btn sm primary", id: "approve-source", run: (b) => void approveSource(b, s, t, topicName(t)) });
      out.push({ label: "Review", cls: "btn sm" + (t == null ? " primary" : ""), href: href("settings/sources/new", { review: s.id }) },
        { label: "Dismiss", cls: "btn sm", id: "dismiss-source", run: (b) => void dismissSource(b, s) });
    }
    if (s.status === "needs_login") out.push({ label: "Reconnect", cls: "btn sm primary", href: "#/settings/watching" });
    if (graded) out.push({ label: "Fetch now", cls: "btn sm", id: "fetch-now", run: (b) => void L.act(b, async () => afk(L, () => L.api(`/api/sources/${s.id}/fetch`, {})), (r) => {
      const x = r as { state: string; fetched: number; new: number; error: string };
      L.say(x.state === "ok" ? `Fetched ${x.fetched} items, ${x.new} new. Nothing is judged until the next run.` : `The fetch failed: ${x.error}`, x.state === "ok" ? "blue" : "red");
    }) });
    // Mute, Read less and Retire act on every topic it feeds: their title says so (SRC D3)
    const ref = { id: s.id, label: s.label, topics: s.topics.length }, reach = reachWords(s.topics.length);
    if (watched && s.mute) out.push({ label: "Unmute", cls: "btn sm", run: (b) => void L.act(b, () => L.api(`/api/sources/${s.id}/mute`, { days: null }), () => {
      L.afkStale("/api/sources", "/api/topics/");
      L.render();
      L.toast(`${s.label} is back to normal from the next run.`);
    }) });
    else if (watched) out.push({ label: "Mute", cls: "btn sm quiet", title: reach, run: (b, a) => muteMenu((b || a)!, ref) });
    if (watched) out.push({ label: "Retire", cls: "btn sm quiet", id: "retire-source", title: reach ? `Retire: not read for any topic (${reach}); its evidence stays; Watch again undoes it` : null, run: (b) => void setSource(b, ref, "retired") });
    if (s.review === "retired") out.push({ label: "Watch again", cls: "btn sm primary", run: (b) => void setSource(b, ref, "approved") });
    return out;
  });
  // at most three verbs in the head: with more, the first two and ⋯ (the rest)
  const shown = $derived(acts.length <= 3 ? acts : acts.slice(0, 2));
  const rest = $derived(acts.length <= 3 ? [] : acts.slice(2));
  // the topics it feeds: each with its sources and its kept items this month, Remove
  // (this topic only), and Add to another topic
  const facts = $derived(s ? (s.topic_facts || s.topics.map((t) => ({ ...t, status: "active", sources: 0, kept_month: 0 }))) : []);
  const otherTopics = $derived.by(() => {
    void view.tick;
    const mine = new Set((s?.topics || []).map((t) => t.id));
    return ((app()?.host()?.topics as { id: number; name: string }[] | undefined) || []).filter((t) => !mine.has(t.id));
  });
  /** where it came from, in words: "Found by the scout for Robotics on 7 Oct", "Added by you for Robotics" */
  const found = $derived.by((): string | null => {
    if (!s) return null;
    const on = s.added_at ? new Date(s.added_at).toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : "";
    const f = s.found_for ? ` for ${s.found_for.name}` : "";
    return s.origin === "scout" ? `Found by the scout${f}${on ? " on " + on : ""}` : s.origin === "manual" ? `Added by you${f}${on ? " on " + on : ""}` : s.origin === "import" ? "Imported from Parallax" : null;
  });
  function addElsewhere(btn: HTMLElement, x: SourcePage): void {
    app()?.menu(btn, otherTopics.map((t) => ({ label: t.name, id: "src-add-" + t.id, run: () => void addTo(null, { id: x.id, label: x.label, topics: x.topics.length }, t) })));
  }
  const secs = $derived.by((): Sec[] => !s ? [] : [{ id: "topics", w: "Topics", n: s.topics.length, about: { text: "An item from this source is judged for each topic it feeds. Remove takes it out of one topic only; Mute, Read less and Retire act on all of them." } },
    { id: "facts", w: "Facts" }, { id: "fetches", w: "Fetches", n: s.fetches.length || null },
    { id: "how", w: "How it is read" }, ...(graded && recent ? [{ id: "recent", w: "Recent from this source", n: recent.data ? recent.data.total : null }] : [])]);

  /** a write to the server: its cached reads are read again after it */
  async function afk(L: NonNullable<ReturnType<typeof app>>, f: () => Promise<unknown>): Promise<unknown> {
    const r = await f();
    L.afkDrop();
    return r;
  }
  function more(btn: HTMLElement): void {
    const L = app();
    L?.menu(btn, rest.map((a) => ({ label: a.label, id: a.id || null, run: (anchor: HTMLElement) => {
      if (a.href) location.hash = a.href;
      else a.run?.(null, anchor);
    } })));
  }
  let ret = $state<HTMLInputElement>();
  function saveRetention(btn: HTMLElement, x: SourcePage): void {
    const L = app();
    const v = (ret?.value || "").trim();
    if (!L) return;
    if (v && !(Number(v) >= 0)) {
      ret?.focus();
      return;
    }
    void L.act(btn, async () => afk(L, () => L.api(`/api/sources/${x.id}/retention`, { days: v ? Number(v) : null })), (r) => {
      const d = (r as { effective_days: number }).effective_days;
      L.say(`Kept ${d > 0 ? d + " days" : "forever"}.`);
    });
  }
  function defaultRetention(btn: HTMLElement, x: SourcePage): void {
    const L = app();
    if (L) void L.act(btn, async () => afk(L, () => L.api(`/api/sources/${x.id}/retention`, { days: null })), (r) => L.say(`Back to the default: ${(r as { effective_days: number }).effective_days} days.`));
  }
</script>

{#snippet fact(k: string, small: string | null | undefined, v: import("svelte").Snippet)}<div class="fact"><dt>{k}</dt><dd>{@render v()}</dd>{#if small}<small>{small}</small>{/if}</div>{/snippet}
{#snippet when(at: string)}<time title={longTime(at)}>{rel(dt(at))}</time>{/snippet}

<Detail back={view.back}>
  {#if !host}
    <NeedHost what="Sources" />
  {:else if !s && c?.error && /no such source|not found|404/i.test(String(c.error))}
    <!-- a source that is not there (removed, or a wrong address): never "Could not read … Tell us" -->
    <div class="pane-in" data-title="Source" id="source-gone"><p class="empty">This source is not here any more.</p><p><a href={href("watch/sources")}>All sources ›</a></p></div>
  {:else if !s}
    <div class="pane-in" data-title="Source"><Loading error={c?.error} /></div>
  {:else}
    {@const st = srcSt(s.status)}
    <!-- the scout's reason keeps the lede, and where it came from follows (the topics are their own section) -->
    {@const lede = [s.why, found].filter(Boolean).join(" · ") || (s.topics.length ? "" : "No topic: every item is judged")}
    <Pane title={s.label} {lede} right={(s.retention_days || 0) > 0 ? `kept ${s.retention_days} days` : "kept forever"} sections={secs}>
      {#snippet kind()}<Glyph name={st[0]} colour={st[1]} word={st[2]} />{` source · ${s.site_name} · ${st[2].toLowerCase()}` + (s.topics.length ? ` · ${s.topics.length === 1 ? "1 topic" : s.topics.length + " topics"}` : "")}{/snippet}
      {#snippet acts()}{#each shown as a (a.label)}{#if a.href}<a class={a.cls} id={a.id || null} href={a.href}>{a.label}</a>{:else}<button class={a.cls} id={a.id || null} title={a.title || null} onclick={(e) => a.run?.(e.currentTarget, e.currentTarget)}>{a.label}</button>{/if}{/each}{#if rest.length}<button type="button" class="btn sm more" aria-haspopup="menu" aria-label="More actions" title="More actions (.)" onclick={(e) => more(e.currentTarget)}>⋯</button>{/if}{/snippet}
      {#snippet top()}
        {#if s.status === "needs_login"}<div class="note c-amber" role="status"><Icon name="warn" /><div><strong>{"Needs login. "}</strong>{s.detail || "The connected account was refused."}</div></div>{/if}
        {#if s.status === "failing"}<div class="note c-red" role="status"><Icon name="x" /><div><strong>{"Failing. "}</strong>{s.detail || ""}</div></div>{/if}
        {#if s.note}<div class="note c-amber" role="status"><Icon name="warn" /><div>{s.note + " Scout more sources on its topic for replacements."}</div></div>{/if}
      {/snippet}
      {#snippet section(sec)}
        {#if sec.id === "topics"}
          {#if facts.length}
            <ul class="lst pl" id="source-topics">{#each facts as t (t.id)}
              {#snippet rm()}{#if watched}<button type="button" class="btn sm quiet hover-only" data-act="remove-from" title={removeNote(s.topics.filter((x) => x.id !== t.id))} onclick={(e) => void removeFrom(e.currentTarget, { id: s.id, label: s.label, topics: s.topics.length }, t)}>{`Remove from ${t.name}`}</button>{/if}{/snippet}
              <Row title={t.name} href={href("topics/" + t.id)} meta={[t.kind === "project" ? "project topic" : null, t.status !== "active" ? t.status : null, `${t.sources} watched`, `${s.kept_month ?? 0} of its ${t.kept_month} kept items this month`].filter(Boolean).join(" · ")} end={rm} />
            {/each}</ul>
          {:else}<p class="muted small">{s.review === "proposed" && s.found_for ? `Proposed for ${s.found_for.name}: no topic until you approve it.` : "No topic: every item from it is judged (the broad lane)."}</p>{/if}
          {#if watched && otherTopics.length}<p class="small mt"><button type="button" class="linkish" id="source-add-topic" onclick={(e) => addElsewhere(e.currentTarget, s)}>Add to another topic</button></p>{/if}
        {:else if sec.id === "facts"}
          {@const m = srcSt(s.status)}
          {#snippet status()}<Mark name={m[0]} colour={m[1]} word={m[2]} />{/snippet}
          {#snippet last()}{#if s.last_fetch}{@render when(s.last_fetch)}{:else}never{/if}{/snippet}
          {#snippet perDay()}{watched && s.items_per_day != null ? s.items_per_day.toFixed(1) : "–"}{/snippet}
          {#snippet kept()}{`${s.kept_30d} of ${s.judged_30d}`}{/snippet}
          {#snippet paid()}{"$" + (s.spend?.usd || 0).toFixed(2)}{/snippet}
          {#snippet toks()}{#if s.spend_month?.tokens}<span class="tok" id="source-tokens" title={tokTitle(s.spend_month.tokens)}>{tokText(s.spend_month.tokens)}</span>{:else}none yet{/if}{/snippet}
          {#snippet graded90()}<span id="source-grades">{gradeWords(s.grades)}</span>{/snippet}
          <dl class="facts">{@render fact("Status", s.detail, status)}{@render fact("Last fetch", `ingest runs every ${s.every_hours} hours`, last)}{@render fact("Items a day", s.items_per_day != null ? "last 7 days, before filtering" : "counted from the first ingest run", perDay)}{@render fact("Kept", "observations from items judged, 30 days", kept)}{#if gradeWords(s.grades)}{@render fact("Your grades", removalWords(s.removal) || "on its observations, 90 days", graded90)}{/if}{#if s.spend_month}{@render fact("Tokens this month", s.spend_month.tokens ? `judging its items; about $${s.spend_month.usd.toFixed(2)}` : "judging its items", toks)}{/if}{#if s.spend}{@render fact("Reads this month", `${s.spend.reads} read at X's list price, about $${s.spend.run_usd.toFixed(2)} a fetch at most; the Developer Console is the bill`, paid)}{/if}</dl>
        {:else if sec.id === "fetches"}
          {#if s.fetches.length}
            <ul class="lst pl">{#each s.fetches as f, i (i)}{@const m = srcSt(f.state)}<Row title={f.state === "ok" ? `${f.fetched} fetched, ${f.new} new` : f.error || m[2]} meta={m[2].toLowerCase()} age={ago(dt(f.created_at))}>{#snippet st()}<Glyph name={m[0]} colour={m[1]} word={m[2]} />{/snippet}{#snippet num()}{f.trigger === "manual" ? "now" : "run"}{/snippet}</Row>{/each}</ul>
          {:else}<p class="empty">No fetches yet.</p>{/if}
        {:else if sec.id === "how"}
          {@const how = s.how || {}}
          <dl class="kv small"><dt>Kind</dt><dd class="mono">{s.kind + (s.preset ? ` (${s.preset})` : "")}</dd><dt>Request</dt><dd class="mono" style="overflow-wrap:anywhere">{how.request || ""}</dd><dt>Pacing</dt><dd>{how.pacing || ""}</dd><dt>Account</dt><dd>{#if s.connection}{"your "}<a href="#/settings/watching">{s.connection}</a>{" account, read-only"}{:else}none: read as any browser would{/if}</dd><dt>Retention</dt><dd class="inline"><span>{((s.retention_days || 0) > 0 ? `${s.retention_days} days` : "forever") + (s.retention_override ? " (set for this source)" : " (the default for its kind)")}</span><label for="ret-days" class="muted small">days</label><input id="ret-days" inputmode="decimal" style="width:80px" value={s.retention_override ? String(s.retention_days) : ""} placeholder={String(s.retention_kind_days)} bind:this={ret} /><button class="btn sm" onclick={(e) => saveRetention(e.currentTarget, s)}>Save</button>{#if s.retention_override}<button class="btn sm" onclick={(e) => defaultRetention(e.currentTarget, s)}>Default</button>{/if}</dd><dt>Terms</dt><dd>{how.terms || ""}</dd></dl>
        {:else if recent}
          {#if !recent.data}<Loading error={recent.error} />
          {:else if recent.data.results.length}<ul class="lst pl">{#each recent.data.results as o (o.id)}<ObsLine {o} />{/each}</ul>
          {:else}<p class="muted small">Nothing kept from it yet.</p>{/if}
          <p class="small mt"><a href={href("library", { source: s.id })}>All observations from this source</a></p>
        {/if}
      {/snippet}
    </Pane>
  {/if}
</Detail>

<style>
  /* a topic's Remove shows on hover or focus where there is a pointer; on a phone it is always there */
  @media (hover: hover) { :global(li.row:not(:hover):not(:focus-within)) .hover-only { opacity: 0; } }
</style>
