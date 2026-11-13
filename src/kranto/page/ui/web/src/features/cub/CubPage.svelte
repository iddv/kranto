<script lang="ts">
  // A cub's page, drawn by the core from the manifest for
  // any cub: like Kranto's own pages. Its head is the shell's (shell/PageHead,
  // declared here): Home › Cubs › Newsletter, its glyph and title with its trust tag, its mode and
  // facts in one line, its says as the lede, its Activity line, one flash (off, or a mode that
  // is not live, with where to change it), at most one primary (ui.primary, else its first form,
  // else its first head action), Stop for a feature that runs, ⋯ with every other verb, ⚙ to
  // Settings › <Cub>; its lists and Log as the subnav's words. Then the list's groups, one row
  // anatomy (each object a row worded by its card, its group's tone the row's glyph; the ask's own
  // button on one that waits for you, a primary on the first row only); above them what it asks
  // you now, one line each (AskLine, SEND), and under Log its history in words; a list with nothing in it says the manifest's
  // words (ui.lists[].empty). A row opens the shell's one sheet (sel=o<id>: CubPane), or its own
  // page when its card says open: page (cub/<id>/o/<oid>: CubObjectPage).
  import Glyph from "../../ui/Glyph.svelte";
  import Row from "../../ui/Row.svelte";
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import Empty from "../../ui/Empty.svelte";
  import Loading from "../../ui/Loading.svelte";
  import type { View } from "../../lib/pages.svelte";
  import type { HeadDecl, HeadVerb } from "../../lib/app/heads";
  import type { MenuItem } from "../../lib/app";
  import { read } from "../../lib/reads.svelte";
  import { go, href } from "../../lib/router";
  import { plural } from "../../lib/format";
  import { ui } from "../../lib/shell.svelte";
  import { features, featurePath, glyphOf, modeTone, modeWord, trustWord } from "../index";
  import { askVerb, at, cubHref, cubPath, groupsOf, headActions, ticketOf, type CubDetail } from "../cub";
  import { ASKS_API } from "../ask";
  import AskLine from "./AskLine.svelte";
  import { cubAct, openAsk } from "../cubverbs";
  import { KIND_WASH } from "../../pages/settings/feature";

  let { view }: { view: View } = $props();
  const H = $derived(!!ui.facts?.header.host);
  const id = $derived(view.w.r.path[1] || "");
  const fs = $derived.by(() => {
    void view.tick;
    return features(H);
  });
  const f = $derived(fs?.features.find((x) => x.id === id) || null);
  // an update staged for an installed cub (from the page or kranto cub update): under ⋯ without a
  // press; Kranto's own features are not installed and have none
  const detail = $derived.by(() => {
    void view.tick;
    return f && f.trust !== "first-party" ? read<CubDetail>(cubPath(f.id), 20000) : null;
  });
  const staged = $derived(detail?.data?.update?.job && detail.data.update.version ? detail.data.update : null);
  // its last update: "Updated to 1.2.1 by itself" when the daily look applied it (cubs.auto_update)
  const updated = $derived(detail?.data?.updated?.version ? detail.data.updated : null);
  const lists = $derived(f?.manifest.ui.lists || []);
  const forms = $derived(f?.manifest.ui.forms || []);
  const listId = $derived(view.w.r.q.list || lists[0]?.id || "log");
  const list = $derived(lists.find((l) => l.id === listId) || null);
  const data = $derived.by(() => {
    void view.tick;
    return f && f.enabled && list ? read<Record<string, unknown>>(featurePath(f.id, list.read), 20000) : null;
  });
  const groups = $derived(list ? groupsOf(list, data?.data) : []);
  const log = $derived.by(() => {
    void view.tick;
    return f && listId === "log" ? read<{ history?: { id: number; title: string; said: string; at: string }[] }>(`${ASKS_API}?cub=${encodeURIComponent(f.id)}`, 20000) : null;
  });
  // an installed cub's own log (Kranto's lines and its own, scrubbed): a built-in feature has none
  const lines = $derived.by(() => {
    void view.tick;
    return f && listId === "log" && f.trust !== "first-party" ? read<{ lines: { ts: string; src: string; level: string; msg: string }[] }>(cubPath(f.id, "log") + "?limit=100", 20000) : null;
  });
  const card = $derived(list && f ? f.manifest.ui.cards[list.card] || null : null);
  const count = (l: typeof lists[number]): number | null => {
    if (!l.count || !f) return null;
    const d = read<Record<string, unknown>>(featurePath(f.id, l.read), 20000).data;
    const xs = d ? d[l.count] : null;
    return Array.isArray(xs) ? xs.length : null;
  };
  const when = (s: string | null | undefined): string => (s || "").slice(0, 16).replace("T", " ");
  const title = (o: Record<string, unknown>): string => String((card && at(o, card.title)) ?? o.title ?? o.id ?? "");
  const meta = (o: Record<string, unknown>): string => {
    const first = card?.lines.map((k) => at(o, k)).find((v) => typeof v === "string" && v);
    return [o.state, first].filter((x) => typeof x === "string" && x).join(" · ");
  };
  /** a group's tone as its rows' glyph and word */
  const TONE: Record<string, [string, string, string]> = {
    wait: ["waiting", "amber", "waits on you"], good: ["check", "green", "done"], bad: ["x", "red", "failed"], new: ["dot", "blue", "new"], quiet: ["open", "grey", "quiet"],
  };
  const sel = (code: string): string => cubHref(id, { list: view.w.r.q.list, sel: code });

  /** the head: its one primary, Stop, ⋯ and its words, declared to the shell */
  const head = $derived.by((): Partial<HeadDecl> | null => {
    if (!f) return null;
    const heads = headActions(f);
    const stopAc = heads.find((a) => a.kind.endsWith(".stop") || a.kind.endsWith(".resume")) || null;
    const verb = (a: (typeof heads)[number]): HeadVerb => a.fields.length
      ? { label: a.title, id: "head-" + a.kind, title: a.says || a.title, href: sel("act:" + a.kind) }
      : { label: a.title + (a.click !== "click" ? "…" : ""), id: "head-" + a.kind, title: a.says || a.title, run: (b) => cubAct(f, a, {}, b) };
    const formVerb = (fm: (typeof forms)[number]): HeadVerb => ({ label: fm.word, id: "form-" + fm.id, title: fm.says || fm.word, href: sel("form:" + fm.id) });
    const want = f.manifest.ui.primary || null;
    const pform = f.enabled ? forms.find((x) => x.id === want) || (want ? null : forms[0] || null) : null;
    const pact = !pform && f.enabled ? heads.find((a) => a !== stopAc && (want ? a.kind === want : true)) || null : null;
    const primary = pform ? formVerb(pform) : pact ? verb(pact) : null;
    const more: MenuItem[] = [];
    for (const a of heads) if (a !== stopAc && a !== pact) more.push({ label: a.title + (a.fields.length || a.click !== "click" ? "…" : ""), id: "head-" + a.kind, title: a.says || a.title, run: (b) => (a.fields.length ? go("cub/" + f.id, { ...view.w.r.q, sel: "act:" + a.kind }) : cubAct(f, a, {}, b)) });
    for (const fm of f.enabled ? forms : []) if (fm !== pform) more.push({ label: fm.word, id: "form-" + fm.id, title: fm.says || fm.word, run: () => go("cub/" + f.id, { ...view.w.r.q, sel: "form:" + fm.id }) });
    if (staged) more.push({ label: `Update to ${staged.version}`, id: "cub-update-ready", title: `${f.title} ${staged.version} ${staged.why || "is staged"}: see its changes and what it may now do, then Update`, run: () => go("settings/" + f.id) });
    const flash = !f.enabled ? { kind: "blue" as const, text: `${f.title} is off: it runs nothing and adds no row.`, link: { href: href("settings/" + f.id), w: `Settings › ${f.title} ›` } }
      : f.mode !== "live" && !f.mode.startsWith("reads") ? { kind: "amber" as const, text: "Practice: approving what it asks sends nothing. Send for real is in its dialog.", link: { href: href("settings/" + f.id), w: `Settings › ${f.title} ›` } }
      : null;
    return {
      crumb: [{ to: "cubs", w: "Cubs" }, { to: "cub/" + f.id, w: f.title }],
      glyph: glyphOf(f.manifest.ui.glyph), wash: KIND_WASH[f.manifest.ui.kind || ""] || "grey",
      trust: { w: trustWord(f.trust), cls: f.trust }, tags: [{ w: modeWord(f.mode), cls: modeTone(f.mode) }],
      facts: [f.version, updated ? `updated to ${updated.version} ${updated.by === "itself" ? "by itself" : "by you"}, ${when(updated.at).slice(0, 10)}` : null,
        f.last_run ? `ran ${when(f.last_run.finished_at)} ${f.last_run.status}` : null, f.spend ? `${plural(f.spend.calls, "model call")} this month` : null,
        (f.asks ?? f.tickets_open) ? `${f.asks ?? f.tickets_open} waiting for you` : null].filter(Boolean).join(" · "),
      lede: f.says,
      // what of it runs now, stopped for you, or failed
      line: "feature:" + f.id, lineId: "cub-run-line",
      flash, primary, stop: stopAc ? { ...verb(stopAc), label: stopAc.title } : null, more, gear: "settings/" + f.id,
      sub: [...lists.map((l) => ({ to: cubHref(f.id, { list: l.id }).slice(2), w: l.word, n: count(l), tone: "wait", on: listId === l.id })),
        { to: cubHref(f.id, { list: "log" }).slice(2), w: "Log", n: null, on: listId === "log" }],
    };
  });
</script>

{#if !H}
  <List title="Cubs" head={{ crumb: [{ to: "cubs", w: "Cubs" }] }}><Empty text="Cubs come from the server, which is not hosting this page." /></List>
{:else if !fs}
  <List title="Cubs" head={{ crumb: [{ to: "cubs", w: "Cubs" }] }}><Loading /></List>
{:else if !f}
  <List title={id} head={{ crumb: [{ to: "cubs", w: "Cubs" }] }}><Empty text={`There is no cub called ${id} on this Kranto.`} link={{ href: "#/cubs", w: "Cubs ›" }} /></List>
{:else}
  <List title={f.title} label={f.title} head={head}>
    {#if f.enabled && (f.manifest.requests || []).length && f.trust !== "first-party"}<AskLine cub={f.id} tick={view.tick} />{/if}
    {#if listId === "log"}
      <Group id="cub-log" title="History" count={log?.data ? String((log.data.history || []).length) : null}>
        <!-- what happened first, on the row's own line: the phone draws no second line -->
        {#each log?.data?.history || [] as t (t.id)}<Row title={`${t.said}: ${t.title}`} meta={`asked ${when(t.at)}`} />{/each}
        {#if log?.data && !(log.data.history || []).length}<Empty li text="Nothing yet: what it asks you, and what you answered, shows here." />{/if}
      </Group>
      {#if lines}
        <Group id="cub-lines" title="Its log" count={lines.data ? String(lines.data.lines.length) : null}>
          {#each [...(lines.data?.lines || [])].reverse() as x, i (i)}<Row title={x.msg} meta={`${when(x.ts)} · ${x.src}${x.level !== "info" ? " · " + x.level : ""}`} />{/each}
          {#if lines.data && !lines.data.lines.length}<Empty li text="Nothing logged yet: its runs write here." />{/if}
        </Group>
      {/if}
    {:else if !f.enabled}
      <Empty text={`Nothing to list while ${f.title} is off.`} link={{ href: href("settings/" + f.id), w: `Settings › ${f.title} ›` }} />
    {:else if !data?.data}
      <Loading error={data?.error} what={list ? `its ${list.word.toLowerCase()}` : "it"} path={list ? featurePath(f.id, list.read) : null} />
    {:else if list && groups.every((g) => !g.items.length)}
      <Empty text={list.empty || "Nothing here yet."} />
    {:else}
      {#each groups as g (g.key)}
        {@const tone = TONE[g.tone || "quiet"] || TONE.quiet!}
        <Group id={"cub-g-" + g.key} title={g.word} count={String(g.items.length)} kind={"cubrows t-" + (g.tone || "quiet")}>
          {#each g.items as o, i (i)}
            {@const tid = ticketOf(o)}
            {@const page = card?.open === "page"}
            <Row sel={"o" + String(o.id)} title={title(o)} href={page ? href(`cub/${f.id}/o/${encodeURIComponent(String(o.id))}`, { list: view.w.r.q.list }) : sel("o" + String(o.id))} meta={meta(o)} stw={tone}>
              {#snippet st()}<Glyph name={tone[0]} colour={tone[1]} word={tone[2]} />{/snippet}
              {#snippet end()}{#if tid}<button class="btn sm primary" data-act="ask-open" onclick={(e) => { e.stopPropagation(); openAsk({ cub: f.id, ticket: tid, again: null }, e.currentTarget); }}>{askVerb(f, fs?.request_schemas)}</button>{/if}{/snippet}
            </Row>
          {/each}
          {#if !g.items.length}<Empty li text="None." />{/if}
        </Group>
      {/each}
    {/if}
  </List>
{/if}
