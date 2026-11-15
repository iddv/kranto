<script lang="ts">
  // Cubs (mock D's #mods, #mods-find, #mods-make; 
  //): Home › Cubs under the shell's one head (▦ Cubs, its facts, the line a cub keeps as its
  // lede, Add a cub the one primary, Arrange the home under ⋯), four underlined words: Installed (a row per cub with its trust and mode, its switch, › to its
  // page; Staged below), Available (the cubs index, which opens at 0.7), Made by Kranto (Kranto,
  // build me a cub, 0.6) and Approvals (what every cub asks you, one line each, the same dialog as
  // anywhere: AskLine; #/cubs/tickets, its old address, lands there). Add a cub (sel=add) is the install sheet and the head's one primary (  // one sheet, one path): a folder or a git URL, read by the server, its manifest in words,
  // Install (in practice); Check a manifest (sel=check) is a fold inside it that reads a pasted
  // cub.yaml only; both in the shell's one sheet (CubsPane). Without the cub runtime there is
  // nothing to add, and Check is the primary. The head's flash says when every cub is stopped
  // (cubs.STOP) or off (cubs.enabled).
  import Row from "../../ui/Row.svelte";
  import Group from "../../ui/Group.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { plural } from "../../lib/format";
  import { app, ui } from "../../lib/shell.svelte";
  import { shopOff } from "../../lib/app/data";
  import { confirmThen } from "../../ui/dialog.svelte";
  import { cubsOf, features, FEATURES_API, glyphOf, modeTone, modeWord, trustWord, type FeatureRow } from "../index";
  import { CUBS_API, cubHref, type CubsList } from "../cub";
  import List from "../../ui/List.svelte";
  import Empty from "../../ui/Empty.svelte";
  import type { HeadDecl } from "../../lib/app/heads";
  import AskLine from "./AskLine.svelte";
  import { ASKS_API, type AskRow } from "../ask";

  let { view }: { view: View } = $props();
  const H = $derived(!!ui.facts?.header.host);
  // the cub shop (Available, Made by Kranto, adding a cub, an update by hand) is a developer's: off
  // unless cubs.developer; your installed cubs and their approvals stay
  const shop = $derived.by(() => {
    void view.tick;
    return !shopOff();
  });
  const asked0 = $derived(view.w.r.path[1] === "tickets" ? "approvals" : view.w.r.path[1] || "installed");
  const tab = $derived(!shop && (asked0 === "available" || asked0 === "made") ? "installed" : asked0);
  const fs = $derived.by(() => {
    void view.tick;
    return features(H);
  });
  const cubs = $derived(cubsOf(fs));
  // the features not read yet: no "0 cubs installed" and no "None yet" before they arrive (QA B14)
  const pending = $derived.by(() => {
    void view.tick;
    if (!H || fs) return false;
    const c = read(FEATURES_API, 60000);
    return !c.data && !c.error;
  });
  const asked = $derived.by(() => {
    void view.tick;
    return H ? read<{ asks: AskRow[] }>(ASKS_API, 15000) : null;
  });
  const open = $derived((asked?.data?.asks || []).filter((t) => cubs.some((c) => c.id === t.cub)));
  // the installed cubs' own lines (a server without the cub runtime answers 404: no banner, no tags)
  const lines = $derived.by(() => {
    void view.tick;
    return H ? read<CubsList>(CUBS_API, 20000).data || null : null;
  });
  const lineOf = (id: string) => lines?.cubs.find((c) => c.id === id) || null;
  const banner = $derived(!lines ? null : lines.stop_file ? "Every cub is stopped: cubs.STOP exists (~/.config/kranto/cubs.STOP). Nothing runs and every approval is practice until you remove the file."
    : !lines.enabled ? "Cubs are off (cubs.enabled: false in your settings): none runs or starts. Their pages and what they ask you stay." : null);
  const sel = $derived(view.w.r.sel || "");
  const ALLTABS: [string, string][] = [["installed", "Installed"], ["available", "Available"], ["made", "Made by Kranto"], ["approvals", "Approvals"]];
  const SUBNAV = $derived(shop ? ALLTABS : ALLTABS.filter(([k]) => k === "installed" || k === "approvals"));
  const tabHref = (k: string): string => href(k === "installed" ? "cubs" : "cubs/" + k);
  /** the head, declared to the shell */
  const head = $derived.by((): Partial<HeadDecl> => ({
    crumb: [{ to: "cubs", w: "Cubs" }], glyph: "▦", wash: "grey",
    facts: pending ? "reading your cubs…" : `${plural(cubs.length, "cub")} installed` + (open.length ? ` · ${open.length} waiting for you` : ""),
    lede: "A cub can ask you to post, send or trade; it never does it itself, and you see who asked and on what before you confirm.",
    primary: !shop ? undefined : lines ? { label: "Add a cub", id: "cubs-add", href: href(view.w.r.path.join("/"), { sel: "add" }) } : { label: "Check a manifest", id: "cubs-check", href: href(view.w.r.path.join("/"), { sel: "check" }) },
    more: [{ label: "Arrange the home", id: "cubs-arrange", title: "Pin, order and hide the cubs' tiles on the home", run: () => (location.hash = "#/home?arrange=1") }],
    flash: banner ? { kind: "red", text: banner, link: null } : null, gear: "settings/system",
    sub: SUBNAV.map(([k, w]) => ({ to: tabHref(k).slice(2), w, n: k === "installed" ? cubs.length || null : k === "approvals" ? open.length || null : null, tone: k === "approvals" ? "wait" : "", on: tab === k })),
  }));
  const when = (s: string | null | undefined): string => (s || "").slice(0, 16).replace("T", " ");

  function toggle(x: FeatureRow, btn: HTMLElement): void {
    const L = app();
    if (!L) return;
    const key = `${x.id}.enabled`;
    const row = (x.settings || []).find((r) => r.key === key);
    if (!row) return;
    const go = () => L.act(btn, () => L.api(`/api/f/${x.id}/settings`, { key, value: !x.enabled, confirm: row.sensitive || undefined }), () => {
      L.afkStale(FEATURES_API);
      L.say(x.enabled ? `${x.title} is off: it stops; its page stays.` : `${x.title} is on.`);
    });
    if (row.sensitive) confirmThen(x.enabled ? `Turn ${x.title} off?` : `Turn ${x.title} on?`, x.enabled ? "It stops; its page and its record stay." : `${x.title} starts in ${modeWord(x.mode)}.`, x.enabled ? "Turn off" : "Turn on", go);
    else void go();
  }
  let wish = $state("");
  const MAY = ["read my cards", "read my briefs", "read my library", "call a model, under a cap of its own","ask me to post", "ask me to send", "ask me to propose a booking"];
  const EXAMPLES = ["news → a Discord digest each evening", "useful cards → a Notion page each", "a brief mentions a price → watch it"];
  let may = $state<string[]>(["read my cards", "read my briefs"]);
</script>

{#snippet tag(word: string, tone: string)}<span class={"htag t-" + tone.replace(/[^a-z-]/g, "")}>{word}</span>{/snippet}

<List title="Cubs" label="Cubs" {head}>
  {#if !H}
    <Empty text="Cubs come from the server, which is not hosting this page." />
  {:else if tab === "installed"}
    <Group id="cubs-installed" title="Installed" count={String(cubs.length)}>
      {#each cubs as x (x.id)}
        {@const ln = lineOf(x.id)}
        {#snippet meta()}{@render tag(trustWord(x.trust), x.trust)}{" "}{@render tag(modeWord(x.mode), modeTone(x.mode))}{#if ln && ln.state === "paused"}{" "}{@render tag((ln.paused?.note || "").startsWith("stopped") ? "stopped" : "paused", "amber")}{/if}{` ${x.says.split(". ")[0]} · ${x.version}${x.last_run ? " · ran " + when(x.last_run.finished_at) : ""}${(x.asks ?? x.tickets_open) ? ` · ${x.asks ?? x.tickets_open} waiting for you` : ""}`}{/snippet}
        {#snippet end()}{#if (x.settings || []).some((r) => r.key === x.id + ".enabled")}<button class="btn sm sw" role="switch" data-cub-switch={x.id} aria-checked={x.enabled ? "true" : "false"} onclick={(e) => toggle(x, e.currentTarget)}>{x.enabled ? "On" : "Off"}</button>{/if}<a class="btn sm quiet" href={cubHref(x.id)} aria-label={`Open ${x.title}`}>›</a>{/snippet}
        <Row title={x.title} href={cubHref(x.id)} {meta} {end}>{#snippet st()}<span class="hglyph" aria-hidden="true">{glyphOf(x.manifest.ui.glyph)}</span>{/snippet}</Row>
      {/each}
      {#if pending}<li class="gempty"><span class="muted">Loading…</span></li>{:else if !cubs.length}<Empty li text={shop ? "No cub yet: Kranto works without any. Add a cub installs one from a folder or a git address." : "No cub yet: Kranto works without any."} />{/if}
    </Group>
    <!-- an update staged for an installed cub (Look for an update, or kranto cub update) waits here
         and on the cub's head until it is applied; the shop's, with cubs.developer -->
    {@const ups = (lines?.cubs || []).filter((c) => c.update?.job && c.state !== "removed")}
    {#if shop}<Group id="cubs-staged" title="Staged" count={String(ups.length)}>
      {#each ups as c (c.id)}
        {@const u = c.update!}
        {#snippet end()}<a class="btn sm primary" data-cub-update={c.id} href={href("settings/" + c.id)}>{`Update to ${u.version}`}</a>{/snippet}
        <Row title={`${c.title} ${u.version}`} href={href("settings/" + c.id)}
          meta={`an update, staged · installed ${c.version}${u.adds && u.adds.length ? ` · it may now: ${u.adds.join("; ")}` : u.needs === "house" ? " · it adds a permission" : ""}`} {end} />
      {/each}
      {#if !ups.length}<li class="gempty"><span class="muted">An update you looked for, and a cub Kranto builds for you (Made by Kranto), wait here until you have read them.</span></li>{/if}
    </Group>{/if}
    <p class="muted small">Each cub's switch here stops it; its page and its record stay. Hide a cub from the home under Arrange.</p>
  {:else if tab === "available"}
    <p class="flash blue" id="cubs-index">The cubs index opens at 0.7: other people's cubs, each marked reviewed, listed or unreviewed, with what it may do. Until then you can check a cub's manifest by pasting it.</p>
    <dl class="perm"><dt>Reviewed</dt><dd>a maintainer read the code; signed</dd><dt>Listed</dt><dd>the index's automated checks passed on this version; nobody has read the code</dd><dt>Unreviewed</dt><dd>any address or folder; nobody has read the code, and the install dialog says so</dd></dl>
    <p><a class="btn" href={href("cubs/available", { sel: "check" })}>Check a manifest</a></p>
  {:else if tab === "made"}
    <section class="box made" aria-labelledby="made-h"><h2 id="made-h">Kranto, build me a cub</h2>
      <label for="made-wish">What should it do?</label>
      <textarea id="made-wish" bind:value={wish} placeholder="When a brief mentions a conference in Europe, draft a trip with flights and a hotel under €800 and ask me before holding anything."></textarea>
      <p class="chips"><span class="muted small">Examples:</span>{#each EXAMPLES as x (x)}{" "}<button type="button" class="chip" onclick={() => (wish = x)}>{x}</button>{/each}</p>
      <p class="label">It may</p>
      <p class="chips">{#each MAY as m (m)}<button type="button" class="chip" aria-pressed={may.includes(m) ? "true" : "false"} onclick={() => (may = may.includes(m) ? may.filter((y) => y !== m) : [...may, m])}>{m}</button>{" "}{/each}</p>
      <p class="muted small">The exam checks the built cub asks for no more than this, and for no high-trust grant you did not name. It is staged as made by Kranto: nothing runs until you have read its manifest, its tests and one practice run.</p>
      <p class="flash amber small" id="made-later">Kranto builds a cub from a sentence in 0.6: until then there is no button for it here. Copy the template (kranto cub new says where) and Add a cub from its folder.</p>
    </section>
    <Group id="cubs-made" title="Staged, made by Kranto" count="0"><li class="gempty"><span class="muted">Nothing staged yet.</span></li></Group>
  {:else}
    <Group id="cubs-approvals" title="Approvals" count={String(open.length)}>
      <li class="asks"><AskLine tick={view.tick} titles={Object.fromEntries(cubs.map((c) => [c.id, c.title]))} /></li>
      {#if !open.length}<Empty li text="Nothing waits for your approval: what a cub asks you comes here and to Needs you." />{/if}
    </Group>
  {/if}
</List>

<style>
  .htag { display: inline-block; font: 500 10.5px/16px var(--sans); padding: 0 7px; border-radius: 8px; color: var(--text); background: var(--subtle); border: 1px solid var(--border-2); white-space: nowrap; }
  .t-first-party { background: var(--blue-wash); } .t-owner, .t-generated { background: var(--violet-wash); }
  .t-reviewed, .t-listed, .t-green { background: var(--green-wash); } .t-listed, .t-generated { border-style: dashed; }
  .t-unreviewed, .t-amber { background: var(--amber-wash); } .t-grey { color: var(--muted); }
  .perm { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 6px 14px; margin: 10px 0; }
  .perm dt { font-size: 11px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; color: var(--muted); }
  .made { padding: 14px 16px; border: 1px solid var(--border); border-radius: 10px; background: var(--box); margin-bottom: 14px; }
  .made h2 { font-size: 15px; margin-bottom: 8px; }
  .made .label, .made label { font-weight: 600; display: block; margin-top: 10px; }
  textarea { width: 100%; min-height: 76px; resize: vertical; }
  .chips { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin-top: 6px; }
  @media (max-width: 700px) {
    .perm { grid-template-columns: 1fr; gap: 2px; }
  }
</style>
