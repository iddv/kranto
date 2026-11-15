<script lang="ts">
  // Settings › Privacy & access, the pane: the choice (UsageChoice, Welcome's own), today's report as it
  // stands, a sent day's exact bytes, and the notice with the field list. Nothing on this page
  // sends anything.
  import Detail from "../../ui/Detail.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Pane from "../../ui/Pane.svelte";
  import Md from "../../ui/Md.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { ui } from "../../lib/shell.svelte";
  import { groupOf, kindLine, SET_ST } from "../../ui/settings";
  import UsageChoice from "./UsageChoice.svelte";
  import { errorsLine, fieldRows, PRIVACY_API, PRIVACY_PAGE, PRIVACY_REPORT, sendingLine, type Privacy, type Report } from "./privacy";
  import Kv, { type KvRow } from "../../ui/Kv.svelte";

  let { view }: { view: View } = $props();
  const id = $derived(groupOf(view.w) || "");
  const host = $derived(!!ui.facts?.header.host);
  const c = $derived.by(() => {
    void view.tick;
    return host ? read<Privacy>(PRIVACY_API, 30000) : null;
  });
  const d = $derived(c?.data || null);
  const rep = $derived.by(() => {
    void view.tick;
    if (!host || (id !== "today" && id !== "errors" && !id.startsWith("sent:"))) return null;
    return read<Report>(PRIVACY_REPORT + (id.startsWith("sent:") ? "?sent=" + id.slice(5) : id === "errors" ? "?errors=1" : ""), 60000);
  });
  const page = $derived(host && id === "notice" ? read<{ markdown: string }>(PRIVACY_PAGE, 600000) : null);
  const st = SET_ST.dflt;
</script>

<Detail back={view.back}>
  {#if !d}
    <div class="pane-in"><p class="empty">{c?.error ? `Could not read the server: ${c.error}` : "Loading…"}</p></div>
  {:else if !id || id === "mode"}
    <Pane title="Usage reports" lede={sendingLine(d)} sections={[{ id: "form", w: "Choose" }]}>
      {#snippet kind()}<Glyph name={st[0]} colour={st[1]} word={st[2]} />{kindLine("privacy & access", "usage reports")}{/snippet}
      {#snippet section()}<UsageChoice p={d} local={true} />{/snippet}
    </Pane>
  {:else if id === "today" || id.startsWith("sent:")}
    {@const r = rep?.data}
    <Pane title={id === "today" ? "Today's report, as it stands" : `Sent: ${id.slice(5)}`} lede={id === "today" ? "What a report for today would hold if it were sent (it is not: " + (d.sending ? "today's is sent tomorrow" : sendingLine(d)) + ")." : "The exact bytes that were posted."} sections={[{ id: "body", w: "Fields" }]}>
      {#snippet kind()}<Glyph name={st[0]} colour={st[1]} word={st[2]} />{" privacy · report"}{/snippet}
      {#snippet section()}
        {#if !r}<p class="empty">{rep?.error || "Loading…"}</p>
        {:else if r.sent !== undefined}<pre class="file">{r.sent || "Nothing was sent that day."}</pre>
        {:else if !r.report}<p class="empty">Off: nothing is counted, so there is no report.</p>
        {:else}<Kv rows={[...fieldRows(r.resource), ...fieldRows(r.report)].map(([k, v]): KvRow => [k, v, "mono"])} /><p class="muted small">{`${r.bytes} bytes before gzip.`}</p>{/if}
      {/snippet}
    </Pane>
  {:else if id === "errors"}
    {@const r = rep?.data}
    <Pane title="Error reports waiting" lede={errorsLine(d) + " Each report is what Kranto says about one error, exactly as it would be sent; the same error goes at most once an hour, with a count."} sections={[{ id: "body", w: "Reports" }]}>
      {#snippet kind()}<Glyph name={st[0]} colour={st[1]} word={st[2]} />{" privacy · error reports"}{/snippet}
      {#snippet section()}
        {#if !r}<p class="empty">{rep?.error || "Loading…"}</p>
        {:else if !r.errors}<p class="empty">Error reports follow your choice: none is kept or sent.</p>
        {:else if !r.errors.length}<p class="empty">None waiting.</p>
        {:else}{#each r.errors as e, i (i)}<Kv rows={fieldRows(e).map(([k, v]): KvRow => [k, v, "mono"])} />{/each}<p class="muted small">{`${r.bytes} bytes before gzip, with the fields every report has (${fieldRows(r.resource).map(([k]) => k).join(", ")}).`}</p>{/if}
      {/snippet}
    </Pane>
  {:else if id === "notice"}
    <Pane title="What Kranto sends" lede="The notice, then every field a report may hold. A field that is not here cannot be sent." sections={[{ id: "body", w: "Notice and fields" }]}>
      {#snippet kind()}<Glyph name={st[0]} colour={st[1]} word={st[2]} />{" privacy · notice"}{/snippet}
      <!-- the notice as a page reads, never its Markdown (13, Gemini 10) -->
      {#snippet section()}{#if page?.data?.markdown}<Md text={page.data.markdown} links />{:else}<p class="empty">{page?.error || "Loading…"}</p>{/if}{/snippet}
    </Pane>
  {:else}
    <div class="pane-empty"><p class="empty">Nothing to show here.</p></div>
  {/if}
</Detail>
