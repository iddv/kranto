<script lang="ts">
  // Add source's pane with nothing chosen: Describe what to add (a box for a
  // pasted list or description, the topic, Resolve), and once resolved (?batch=<n>) the batch as one
  // group in five sections: Ready to approve (ticked), Could not be fetched (Try as corrects one),
  // Not found or not offered, Needs an account, Already watching or proposed; with Open in Claude
  // Code on, Find these with Claude Code under the lines Kranto could not add, and a sixth section,
  // Found by Claude Code, for the lists its session sent back. Approve the ticked approves them in
  // one request. Or pick a kind on the left, as before.
  import FLabel from "../../ui/FLabel.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Loading from "../../ui/Loading.svelte";
  import Pane, { type Sec } from "../../ui/Pane.svelte";
  import Row from "../../ui/Row.svelte";
  import Tip from "../../ui/Tip.svelte";
  import Icon from "../../shell/Icon.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { about, perDay } from "../topics/proposals";
  import type { Session } from "../../term/api";
  import { openTerm, termUi } from "../../term/state.svelte";
  import { approveTicked, batchApi, canTry, DESCRIBE, FINDABLE, FOUND, lineMark, lineMeta, lineTitle, preticked, resolveText, SECTIONS, sectionLines, tryAs, tryHref, type FromTextBatch, type FromTextLine } from "./describe.svelte";
  import { CATALOG_API, type Catalog } from "./sources.svelte";

  let { view }: { view: View } = $props();
  const q = $derived(view.w.r.q);
  const cc = $derived.by(() => {
    void view.tick; // each draw may find the reads stale
    return read<Catalog>(CATALOG_API, 60000);
  });
  const cat = $derived(cc.data);
  // the batch: the one just resolved, or the one the address names (read again by its id)
  const bc = $derived.by(() => {
    void view.tick;
    return q.batch && (!DESCRIBE.batch || String(DESCRIBE.batch.call_id) !== q.batch) ? read<{ job: { state: string; result: FromTextBatch | null; error: string | null } }>(batchApi(q.batch), 600000) : null;
  });
  const batch = $derived<FromTextBatch | null>(q.batch ? (DESCRIBE.batch && String(DESCRIBE.batch.call_id) === q.batch ? DESCRIBE.batch : bc?.data?.job.result || null) : null);
  // a batch opened by its address: its ready lines ticked, once
  let seeded = $state<string | null>(null);
  $effect(() => {
    if (batch && seeded !== batch.id && (!DESCRIBE.batch || DESCRIBE.batch.id !== batch.id)) {
      DESCRIBE.batch = batch;
      DESCRIBE.ticked = preticked(batch);
    }
    if (batch) seeded = batch.id;
  });
  // the topic the box resolves for: the one Add source was opened from, else none
  $effect.pre(() => {
    if (!DESCRIBE.text && !DESCRIBE.waiting) DESCRIBE.topic = q.topic || "";
  });
  const topicName = $derived(batch && batch.topic != null ? cat?.topics.find((t) => t.id === batch.topic)?.name || null : null);
  // Find these with Claude Code (4.6, behind term.enabled): the batch's sessions and the
  // lists they sent back, read from the page's own api/term and the server's batches
  const tc = $derived.by(() => {
    void view.tick;
    return batch && termUi.enabled ? read<{ sessions: Session[]; sources_on?: string | null }>("api/term", 5000) : null;
  });
  const mine = $derived(batch && tc?.data ? tc.data.sessions.filter((s) => s.subject?.kind === "sources" && s.subject.id === String(batch.call_id)) : []);
  const foundIds = $derived(mine.flatMap((s) => s.batches || []));
  // what the session runs on (the credential, and the model pinned on an API key), and the Claude
  // API's refusal of its last request
  const findOn = $derived(mine.find((s) => s.state === "running")?.on || tc?.data?.sources_on || null);
  const refused = $derived(mine.find((s) => s.refused)?.refused || null);
  const found = $derived.by((): FromTextLine[] => {
    void view.tick;
    return foundIds.flatMap((n) => read<{ job: { result: FromTextBatch | null } }>(batchApi(n), 600000).data?.job.result?.lines || []);
  });
  // a list sent back: its fetched lines ticked when it first shows
  let seen = $state<number[]>([]);
  $effect(() => {
    const fresh = foundIds.filter((n) => !seen.includes(n));
    if (!fresh.length || !found.length) return;
    seen = [...seen, ...fresh];
    DESCRIBE.ticked = [...new Set([...DESCRIBE.ticked, ...preticked({ lines: found })])];
  });
  const linesOf = (b: FromTextBatch, id: string): FromTextLine[] => (id === FOUND[0] ? found : sectionLines(b, id));
  const secs = $derived.by((): Sec[] => !batch ? [{ id: "describe", w: "Describe what to add" }]
    : [...SECTIONS.map(([id, w]): Sec => ({ id, w, n: sectionLines(batch, id).length })), { id: FOUND[0], w: FOUND[1], n: found.length }].filter((s) => s.n));
  // the button goes under the first section whose lines a session may look into
  const findIn = $derived(secs.find((s) => FINDABLE.includes(s.id))?.id || null);
  const ticked = $derived(new Set(DESCRIBE.ticked));
  const rowsTicked = $derived(batch ? [...batch.lines, ...found].filter((l) => l.row && l.source_id != null && ticked.has(l.source_id)).map((l) => l.row!) : []);
  function find(b: FromTextBatch): void {
    const n = b.lines.filter((l) => ["invalid", "not_found", "unverified"].includes(l.status)).length;
    openTerm("sources", String(b.call_id), `Find feeds for ${n} ${n === 1 ? "line" : "lines"}`);
  }
  const count = $derived(`${ticked.size} ticked · about ${about(perDay(rowsTicked))} items a day before filtering`);
  function tick(l: FromTextLine, yes: boolean): void {
    if (l.source_id == null) return;
    const id = l.source_id;
    DESCRIBE.ticked = yes ? [...new Set([...DESCRIBE.ticked, id])] : DESCRIBE.ticked.filter((x) => x !== id);
  }
  const tickable = (l: FromTextLine): boolean => l.source_id != null && ["valid", "unverified", "already_proposed", "already_watching"].includes(l.status)
    && !(l.status === "already_watching" && (batch?.topic == null));
  const connectHref = (l: FromTextLine): string => "#/settings/connections/" + (l.preset || "").split(".")[0];
</script>

{#snippet kindLine()}<Glyph name="open" colour="blue" word="Add source" />{batch ? " settings · add source · described" : " settings · add source"}{/snippet}
{#snippet ledeBox()}Paste a list or describe the sources; or pick a kind on the left.<Tip id="sources.access" about="how a source is read" />{/snippet}
{#snippet approveBtn()}<button class="btn sm primary" id="approve-ticked" disabled={!ticked.size} onclick={(e) => void approveTicked(e.currentTarget, batch!, topicName, found)}>Approve the ticked</button><a class="btn sm" href="#/settings/sources/new" onclick={() => (DESCRIBE.batch = null)}>Describe more</a>{/snippet}

{#if q.batch && !batch}
  <div class="pane-in"><Loading error={bc?.error || (bc?.data && !bc.data.job.result ? bc.data.job.error || "this batch is not done" : null)} /></div>
{:else if batch}
  {@const b = batch}
  <Pane title={topicName ? `Described sources for ${topicName}` : "Described sources"} kind={kindLine} lede={b.message} acts={approveBtn} right={count} sections={secs}>
    {#snippet top()}{#if b.topic == null}<div class="note c-grey" role="status"><Icon name="note" /><div>No topic: approved sources are watched with every item judged. Choose a topic in the box to have their items prefiltered against it.</div></div>{/if}{/snippet}
    {#snippet section(s)}
      <ul class="lst pl desc">
        {#each linesOf(b, s.id) as l, i (s.id + i)}
          {@const w = lineMark(l)}
          {#snippet tickBox()}{#if tickable(l)}<input type="checkbox" class="ptick" aria-label={"Watch " + lineTitle(l)} checked={ticked.has(l.source_id!)} onchange={(e) => tick(l, e.currentTarget.checked)} />{/if}{/snippet}
          {#snippet st()}<Glyph name={w[0]} colour={w[1]} word={w[2]} />{/snippet}
          {#snippet end()}{#if canTry(l)}<a class="btn sm" href={tryHref(l, b.topic)} title="Correct a field and preview it" onclick={() => tryAs(l, b.topic)}>Try as</a>{:else if l.status === "connect_first"}<a class="btn sm" href={connectHref(l)}>Connect</a>{/if}{/snippet}
          <Row tick={tickBox} {st} title={lineTitle(l)} href={l.source_id != null ? `#/settings/sources/new?sel=ereview:${l.source_id}` : null} meta={lineMeta(l)} end={canTry(l) || l.status === "connect_first" ? end : undefined} />
        {/each}
      </ul>
      {#if s.id === findIn}
        {#if termUi.enabled}<div class="inline mt"><button class="btn sm" id="find-with-claude" onclick={() => find(b)}>Find these with Claude Code</button><span class="muted small">{findOn ? findOn.charAt(0).toUpperCase() + findOn.slice(1) + ". " : ""}It looks the feeds up in the terminal, in its sandbox, and sends a list back here; you approve it like this one.</span></div>
          {#if refused}<div class="note c-red mt" role="status" id="find-refused"><Icon name="x" /><div>{"The Claude API refused the session's last request: " + refused}</div></div>{/if}
        {:else}<p class="muted small mt">Open in Claude Code is not available here: correct the fields by hand with Try as.</p>{/if}
      {/if}
      {#if s.id === FOUND[0]}<p class="muted small mt">Sent back by Claude Code and checked again, like the lines above.</p>{/if}
    {/snippet}
  </Pane>
{:else}
  <Pane title="Add source" kind={kindLine} lede={ledeBox} sections={secs}>
    {#snippet section()}
      <div class="field"><FLabel forId="d-text" text="Sources" hint="Names, URLs, repositories, accounts. One per line is easiest." /><textarea id="d-text" rows="8" style="width:min(100%,560px)" placeholder={"Simon Willison's blog\nreleases of astral-sh/uv\nthat Rust weekly thing"} value={DESCRIBE.text} oninput={(e) => (DESCRIBE.text = e.currentTarget.value)} disabled={!!DESCRIBE.waiting}></textarea></div>
      <div class="field"><FLabel forId="d-topic" text="Topic" tipId="sources.topic" /><select id="d-topic" disabled={!!DESCRIBE.waiting} onchange={(e) => (DESCRIBE.topic = e.currentTarget.value)}><option value="" selected={DESCRIBE.topic === ""}>No topic: every item is judged</option>{#each cat?.topics || [] as t (t.id)}<option value={String(t.id)} selected={DESCRIBE.topic === String(t.id)}>{t.name}</option>{/each}</select></div>
      <div class="inline"><button class="btn primary" id="resolve" disabled={!DESCRIBE.text.trim() || !!DESCRIBE.waiting} onclick={(e) => void resolveText(e.currentTarget)}>Resolve</button>{#if DESCRIBE.waiting}<span class="muted small">{DESCRIBE.waiting}</span>{/if}</div>
      <p class="muted small">One model call names each source, then each is fetched; nothing is watched until you approve it.</p>
      {#if DESCRIBE.error}<div class="note c-red" role="status"><Icon name="x" /><div>{"Resolving failed: " + DESCRIBE.error + " Your text is kept; click Resolve again."}</div></div>{/if}
    {/snippet}
  </Pane>
{/if}
