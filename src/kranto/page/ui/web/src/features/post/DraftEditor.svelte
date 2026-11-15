<script lang="ts">
  // Editing a draft in place (the verb post.edit): the title as a field, the
  // draft's own words as text (a long post is one box of markdown; a short post or a thread is one
  // box a part, each with its count against the limit, red past it), the extras as plain lines
  // with Remove where the site allows it, PROSE's flags under the words (checked again as you
  // type; Fix them puts revise's words in the box), and a foot with Cancel and Save (the page's
  // one primary while editing). Save files your words as the series' next draft
  // (POST /api/post/d/<id>/edit); the original stays under Earlier drafts. Nothing is sent.
  import { untrack } from "svelte";
  import { afkDropPrefix } from "../../lib/app/data";
  import { app } from "../../lib/shell.svelte";
  import ProseFlags from "./ProseFlags.svelte";
  import { learnFrom, siteOf } from "./prose";
  import { editPath, type PostEdited, type PostSheet } from "./post";

  let { s, close, saved }: { s: PostSheet; close: () => void; saved: (to: number) => void } = $props();
  const long = $derived(s.edit?.body != null);
  // the words the editor opens with, read once (the box is the owner's from then on); SOCIAL's
  // parts when the read carries them, else the editor's own (one part)
  const first = untrack(() => ({ title: s.edit?.title ?? "", body: s.edit?.body ?? "",
    parts: s.parts?.map((p) => ({ text: p.text })) || s.edit?.parts?.map((p) => ({ text: p.text })) || [{ text: "" }],
    before: s.edit?.body ?? s.edit?.parts?.map((p) => p.text).join("\n\n") ?? "" }));
  let title = $state(first.title);
  let body = $state(first.body);
  let parts = $state(first.parts);
  let said = $state("");
  const max = $derived(s.limit?.max ?? null);
  const site = $derived(s.site || siteOf(s.kind));
  const text = $derived(long ? body : parts.map((p) => p.text).join("\n\n"));
  const over = $derived(max != null && parts.some((p) => p.text.length > max));
  const empty = $derived(!text.trim() || (s.edit?.title != null && !title.trim()));
  const before = first.before;

  async function save(btn: HTMLElement, extra: Record<string, unknown> | null = null): Promise<void> {
    const L = app();
    if (!L) return;
    const what = extra ?? (long ? { title, body } : { ...(s.edit?.title != null ? { title } : {}), parts: parts.map((p) => ({ text: p.text })) });
    await L.act(btn, () => L.api(editPath(s.id), what), (r) => {
      const got = r as PostEdited;
      if (!extra) learnFrom(before, text);
      afkDropPrefix("/api/post");
      L.say(got.say);
      saved(got.id);
    });
  }
</script>

<form class="draft-editor" id="draft-editor" onsubmit={(e) => { e.preventDefault(); void save(e.currentTarget.querySelector("#draft-save") as HTMLElement); }}>
  {#if s.edit?.title != null}<label class="de-l small" for="draft-edit-title">Title</label><input id="draft-edit-title" class="wide" type="text" maxlength="200" bind:value={title} />{/if}
  {#if long}
    <label class="de-l small" for="draft-edit-body">The words (markdown)</label>
    <textarea id="draft-edit-body" class="wide de-body" rows="16" bind:value={body}></textarea>
  {:else}
    {#each parts as p, i (i)}
      <label class="de-l small" for={"draft-edit-part-" + i}>{parts.length > 1 ? `${i + 1} of ${parts.length}` : "The post"}</label>
      <textarea id={"draft-edit-part-" + i} class="wide de-part" rows="5" bind:value={p.text}></textarea>
      {#if max != null}<p class={"de-count small" + (p.text.length > max ? " over" : "")} id={"draft-edit-count-" + i}>{`${p.text.length} of ${max} ${s.limit?.unit || "characters"}`}</p>{/if}
    {/each}
  {/if}
  {#each s.extras || [] as x (x.key)}<p class="muted small de-extra">{x.words}{#if x.drop}{" "}<button type="button" class="linkish small" onclick={(e) => void save(e.currentTarget, { drop: x.key })}>Remove</button>{/if}</p>{/each}
  <ProseFlags {text} {site} parts={long ? null : parts.map((p) => p.text)} id="draft-edit-flags" fix={(t, say) => { if (long) body = t; else if (parts[0]) parts[0].text = t; said = say; }} />
  {#if said}<p class="muted small" id="draft-edit-said">{said} Save keeps it; Cancel leaves the draft as it was.</p>{/if}
  <p class="acts de-foot"><button type="button" class="btn sm" id="draft-cancel" onclick={close}>Cancel</button><button type="submit" class="btn sm primary" id="draft-save" disabled={over || empty}>Save</button></p>
  <p class="muted small">Saved, your version waits on Post in its place; the original stays under Earlier drafts.</p>
</form>

<style>
  .draft-editor { display: flex; flex-direction: column; gap: 4px; }
  .de-l { color: var(--ink2); margin-top: 6px; }
  .de-body, .de-part { font: inherit; line-height: 1.5; resize: vertical; }
  .de-count { margin: 0; color: var(--muted); text-align: right; }
  .de-count.over { color: var(--red); }
  .de-foot { display: flex; gap: 8px; }
</style>
