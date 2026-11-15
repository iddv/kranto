<script lang="ts">
  // A draft's sheet: its title, one facts line ("edited by you" once
  // edited), the draft rendered and folded to its first lines ("Show all"), PROSE's flags under
  // it (what reads like AI, each with its plain fix, and one line), then the verbs. With an account
  // and an ask that waits: Send (the primary; SEND's dialog, unchanged), Copy, Edit, Download,
  // Decline, Details. With none: Copy (the primary), Edit, Download, "Connect an account to send",
  // Decline, Details. Edit turns the sheet into the editor in place (DraftEditor: Cancel and Save,
  // the page's one primary while editing); Save files the owner's words as the series' next draft
  // and the page moves to it. An edited draft offers "Start again from the original" under its
  // verbs. Copy puts the markdown on the clipboard and Download saves <title>.md: neither needs
  // an account, a model or the network. SOCIAL's read fields, when the read carries them, are
  // drawn as plain lines (the siblings above the words, the extras under them). A short post (a
  // site's variant of one write) draws its posts, each with its count the site's way (red past the
  // limit), and its verbs: Open in <site> first (the site's own composer with the draft filled in:
  // a plain link, nothing is sent; off on the preview, with its words), then I posted it (the
  // person's record, with Not yet), Post to <site> when they switched the site to Post directly
  // (the confirm dialog), Copy (the posts' words), Edit, Download, Decline, Details. There is no
  // "copy and open". The Post page (pages/post) mounts it for #/post/d/<id>.
  import Loading from "../../ui/Loading.svelte";
  import Md from "../../ui/Md.svelte";
  import { openDetails } from "../../ui/details.svelte";
  import { confirmThen } from "../../ui/dialog.svelte";
  import { rel, dt } from "../../lib/format";
  import { afkDropPrefix } from "../../lib/app/data";
  import { read } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { app } from "../../lib/shell.svelte";
  import { openAsk } from "../cubverbs";
  import DraftEditor from "./DraftEditor.svelte";
  import ProseFlags from "./ProseFlags.svelte";
  import { siteOf } from "./prose";
  import { copyText, downloadHref, editPath, partsText, sheetPath, type PostEdited, type PostSheet } from "./post";

  // titled: the sheet's own title (off on the draft's page, whose head has it)
  let { id, tick = 0, titled = true }: { id: number | string; tick?: number; titled?: boolean } = $props();
  const c = $derived.by(() => {
    void tick;
    return read<PostSheet>(sheetPath(id), 30000);
  });
  const s = $derived(c?.data || null);
  let all = $state(false);
  let editing = $state(false);
  // the draft as drawn: its "# Title" line left out (the head says it); Copy and Download keep it
  const parts = $derived(s ? s.markdown.split(/\n{2,}/).filter((p, i) => !(i === 0 && p.trim() === `# ${s.title}`)) : []);
  const folded = $derived(!all && parts.length > 4);
  const shown = $derived((folded ? parts.slice(0, 4) : parts).join("\n\n"));
  const waits = $derived(!!s && s.group === "waiting" && (s.ticket != null || s.again != null));
  // a short post: a site's variant, with its posts and its own verbs
  const short = $derived(!!s && !!s.site);
  const posts = $derived(s?.parts || []);
  const canSend = $derived(!!s && waits && s.account && !short);
  // I posted it shows once Open was followed, or while the draft waits for it (Not yet hides it)
  let opened = $state(false);
  let notYet = $state(false);
  const askPosted = $derived(!!s && short && !!s.posted_by_you && !notYet && (opened || s.group === "waiting"));
  // the words PROSE checks: the editor's own (sources by outlet), else the markdown
  const words = $derived(s ? (s.edit?.body ?? s.edit?.parts?.map((p) => p.text).join("\n\n") ?? s.markdown) : "");
  let copied = $state(false);

  async function copy(): Promise<void> {
    if (!s) return;
    const ok = await copyText(short && posts.length ? partsText(posts) : s.markdown);
    copied = ok;
    // a refusal is not a success: amber, with the warning mark (17, Codex 22)
    app()?.say(ok ? (short ? "Copied: the post is on your clipboard." : "Copied: the post's markdown is on your clipboard.") : "The browser did not allow copying: use Download.", ok ? undefined : "amber");
  }
  /** I posted it: the person posted the opened draft themselves; Kranto sends nothing */
  function posted(btn: HTMLElement): void {
    const L = app();
    if (!s || !L) return;
    void L.act(btn, () => L.api(`${sheetPath(s.id)}/posted`, {}), (r) => {
      afkDropPrefix("/api/post");
      L.afkDrop();
      L.say((r as { say?: string } | null)?.say || "Recorded: posted by you.");
    });
  }
  function send(btn: HTMLElement): void {
    if (s) openAsk({ cub: s.cub, ticket: s.ticket, again: s.again }, btn);
  }
  function decline(): void {
    const t = s?.ticket;
    if (t == null) return;
    confirmThen("Decline this draft?", ["It moves to Earlier drafts, where you can still copy or download it. Nothing is sent."], "Decline", () => {
      const L = app();
      void L?.act(null, () => L.api(`/api/tickets/${t}/decline`, {}), () => {
        L.afkDrop();
        L.say("Declined: the draft is under Earlier drafts.");
      });
    }, "danger");
  }
  /** after Save: the page moves to the new draft (the series' next), the editor closes */
  function moved(to: number): void {
    editing = false;
    if (String(to) !== String(id)) location.hash = href(`post/d/${to}`);
  }
  /** Start again from the original: an edit with the original draft's own words */
  function again(): void {
    const from = s?.original_draft;
    if (!s || from == null || from === s.id) return;
    confirmThen("Start again from the original?", ["The original draft's words become the draft that waits. Your version stays under Earlier drafts. Nothing is sent."], "Start again", () => {
      const L = app();
      void L?.act(null, async () => {
        const o = await L.api(sheetPath(from)) as PostSheet;
        const e = o.edit || { title: null };
        return L.api(editPath(s.id), e.body != null ? { ...(e.title != null ? { title: e.title } : {}), body: e.body } : { parts: (e.parts || []).map((p) => ({ text: p.text })) });
      }, (r) => {
        afkDropPrefix("/api/post");
        L.say((r as PostEdited).say);
        moved((r as PostEdited).id);
      });
    });
  }
  const facts = $derived(s ? [s.word, s.fact, s.edited ? "edited by you" : "", rel(dt(s.at)), s.said || s.line].filter(Boolean).join(" · ") : "");
</script>

{#if !s}
  <Loading error={c?.error} what="the draft" />
{:else}
  <section class="draft-sheet" id="draft-sheet" data-draft={String(s.id)}>
    {#if titled}<h2 id="draft-title">{s.title}</h2>{/if}
    <p class="muted small" id="draft-facts">{facts}</p>
    {#if s.siblings?.length}<p class="muted small" id="draft-siblings">{#each s.siblings as x, i (x.id)}{#if i}{" · "}{/if}{#if String(x.id) === String(s.id)}<b>{x.word || x.site}{x.state === "sent" ? " ✓" : ""}</b>{:else}<a href={href(`post/d/${x.id}`)}>{(x.word || x.site) + (x.state === "sent" ? " ✓" : "")}</a>{/if}{/each}</p>{/if}
    {#if editing}
      <DraftEditor {s} close={() => (editing = false)} saved={moved} />
    {:else}
      {#if short && posts.length}
        <div class="draft-text" id="draft-text">
          {#each posts as p, i (i)}
            <div class="draft-part" id={"draft-part-" + i}>
              {#if posts.length > 1}<p class="muted small">{`${i + 1} of ${posts.length}`}</p>{/if}
              <p class="draft-part-text">{p.text}</p>
              {#if s.limit && p.used != null}<p class={"muted small draft-count" + (p.used > s.limit.max ? " over red" : "")} id={"draft-count-" + i}>{`${p.used} of ${s.limit.max} ${s.limit.unit}`}</p>{/if}
            </div>
          {/each}
        </div>
      {:else}
        <div class="draft-text" id="draft-text"><Md text={shown} links /></div>
      {/if}
      {#if folded && !short}<p><button type="button" class="linkish small" id="draft-show-all" onclick={() => (all = true)}>{`Show all ${s.words} words`}</button></p>{/if}
      {#each s.extras || [] as x (x.key)}<p class="muted small draft-extra">{x.words}</p>{/each}
      {#if s.group === "waiting"}<ProseFlags text={words} site={s.site || siteOf(s.kind)} id="draft-flags" />{/if}
      <p class="acts" id="draft-verbs">
        {#if short && waits}
          {#if s.open}<a class="btn sm primary" id="draft-open" href={s.open} target="_blank" rel="noopener noreferrer" onclick={() => (opened = true)}>{`Open in ${s.site_word || s.site}`}</a>
          {:else if s.open_off}<button type="button" class="btn sm primary" id="draft-open" disabled>{`Open in ${s.site_word || s.site}`}</button><span class="muted small" id="draft-open-off">{s.open_off}</span>{/if}
          {#if s.direct}<button type="button" class={"btn sm" + (s.open || s.open_off ? "" : " primary")} id="draft-direct" disabled={!s.direct.ready} title={s.direct.why || ""} onclick={(e) => send(e.currentTarget)}>{s.direct.word}</button>{#if !s.direct.ready && s.direct.why}<span class="muted small" id="draft-direct-why">{s.direct.why}</span>{/if}{/if}
        {/if}
        {#if canSend}<button type="button" class="btn sm primary" id="draft-send" onclick={(e) => send(e.currentTarget)}>{s.ticket != null ? s.verb || "Send" : "Send again"}</button>{/if}
        <button type="button" class={"btn sm" + (canSend || (short && waits) ? "" : " primary")} id="draft-copy" onclick={() => void copy()}>{copied ? "Copied" : "Copy"}</button>
        {#if s.can_edit}<button type="button" class="btn sm" id="draft-edit" title={s.ticket != null ? "Your words become the draft that waits; a send waiting for your yes is withdrawn first" : "Your words become the draft that waits"} onclick={() => (editing = true)}>Edit</button>{/if}
        <a class="btn sm" id="draft-download" href={downloadHref(s.id)} download={s.filename}>Download</a>
        {#if waits && !s.account && !short}<a class="btn sm quiet" id="draft-connect" href={href("settings/posting")}>Connect an account to send</a>{/if}
        {#if s.ticket != null}<button type="button" class="btn sm quiet" id="draft-decline" onclick={decline}>Decline</button>{/if}
        {#if (s.ticket ?? s.again) != null}<button type="button" class="linkish small" id="draft-details" onclick={() => openDetails(`ask:${s.ticket ?? s.again}`)}>Details ›</button>{/if}
      </p>
      {#if askPosted}<p class="acts small" id="draft-posted"><button type="button" class="btn sm" id="draft-posted-yes" onclick={(e) => posted(e.currentTarget)}>I posted it</button><button type="button" class="linkish small" id="draft-posted-no" onclick={() => (notYet = true)}>Not yet</button></p>{/if}
      {#if s.edited && s.can_edit && s.original_draft != null && s.original_draft !== s.id}<p class="small" id="draft-again"><a href={href(`post/d/${s.original_draft}`)}>The original draft ›</a>{" · "}<button type="button" class="linkish small" onclick={again}>Start again from the original</button></p>{/if}
      {#if s.link}<p class="small" id="draft-link"><a href={s.link} target="_blank" rel="noopener noreferrer">Where it went ↗</a></p>{/if}
    {/if}
  </section>
{/if}
