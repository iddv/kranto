<script lang="ts">
  // File it's confirm (FB): exactly the issue that is filed (the repository, who files it, the
  // title, the labels, the body) and nothing else. File it posts that title and body; the server
  // scrubs them again and files only when its scrub changes nothing. When it would, nothing is
  // filed and this confirm shows its version (note). Back returns to the sheet with the draft.
  import { untrack } from "svelte";
  import { ISSUE_API, clearDraft, type Draft, type FeedbackStatus, type Issue } from "./feedback";
  import { backToSheet, confirmFiling } from "./sendFeedback";

  let { st, draft, issue, hash, note = null, close }: { st: FeedbackStatus; draft: Draft; issue: Issue; hash: string; note?: string | null; close: () => void } = $props();
  const x = untrack(() => issue);
  let busy = $state(false);
  let err = $state<string | null>(null);

  async function file(): Promise<void> {
    busy = true;
    err = null;
    try {
      const r = await fetch(ISSUE_API, { method: "POST", cache: "no-store", headers: { "content-type": "application/json" }, body: JSON.stringify({ kind: draft.kind, title: x.title, body: x.body }) });
      const j = (await r.json().catch(() => ({}))) as { error?: string; title?: string; body?: string; number?: number; url?: string; repo?: string; dropped?: string[] };
      if (r.status === 409 && j.title && j.body) {
        confirmFiling(st, draft, { ...x, title: j.title, body: j.body }, hash, j.error || "Kranto found more to take out: this is what would be filed.");
        return;
      }
      if (!r.ok || !j.number || !j.url) throw new Error(j.error || r.statusText || "GitHub did not answer");
      clearDraft();
      backToSheet(hash, { filed: { number: j.number, url: j.url, repo: j.repo || st.repo, dropped: j.dropped || [] } });
    } catch (e) {
      err = ((e as Error).message || "Nothing was filed.") + (/draft is kept/.test((e as Error).message) ? "" : " Nothing was filed; your draft is kept.");
      busy = false;
    }
  }
</script>

<div class="dlg-h" id="dlg-t">File this issue on {st.repo}?</div>
<div class="dlg-b" id="fb-confirm">
  {#if note}<div class="flash amber" role="status" id="fb-note"><div>{note}</div></div>{/if}
  <p>Filed as <strong>{st.login}</strong>, through your gh, exactly as below. Anyone who can see {st.repo} can read it.</p>
  <div class="field mt"><span class="lbl">Title</span><div id="fb-c-title">{x.title}</div></div>
  <div class="field"><span class="lbl">Labels</span><div id="fb-c-labels">{x.labels.join(", ")} <span class="muted small">(GitHub keeps those the repository has; the body says the kind either way)</span></div></div>
  <div class="field"><span class="lbl">Body</span><pre class="cmd" id="fb-c-body" style="max-height:40vh;overflow:auto">{x.body}</pre></div>
  {#if err}<div class="flash red" role="status" id="fb-c-err"><div>{err}</div></div>{/if}
</div>
<!-- svelte-ignore a11y_autofocus -->
<div class="dlg-f"><button class="btn" autofocus onclick={() => backToSheet(hash)}>Back</button><button class="btn primary" id="fb-c-ok" disabled={busy} aria-busy={busy ? "true" : null} onclick={() => void file()}>File it</button></div>
