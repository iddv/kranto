<script lang="ts">
  // Settings › <Feature> (#/settings/<id>, the gear in its head): one page for
  // every feature and cub, generated from its manifest in the eight pages' shape. On and off (its
  // switch; a cub's live kinds and Stop); its settings in the groups its manifest names (a
  // true-or-false key a switch in its row, one press with Undo; any other key a row whose form is
  // in the sheet, sel=e<key>); Advanced, folded (the keys marked advanced, and the ones written by
  // hand, shown not edited); a cub's keys Kranto holds (Needs you and New, its caps); the accounts
  // it uses; its spend and its caps; About (a cub's version, what it may do, Look for an update,
  // Remove). NEWS adds News's per-topic group here; a cub installed later has its
  // page with no work by its author.
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import Row from "../../ui/Row.svelte";
  import SetRow from "../../ui/SetRow.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Empty from "../../ui/Empty.svelte";
  import Loading from "../../ui/Loading.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { app, ui } from "../../lib/shell.svelte";
  import { confirmThen } from "../../ui/dialog.svelte";
  import { saveUndo } from "../../ui/save";
  import { SET_ST } from "../../ui/settings";
  import { features, FEATURES_API, glyphOf, trustWord, type FeatureRow, type SettingRow } from "../../features/index";
  import { arrangement, placeOf, SHELL_API } from "../../features/shell";
  import { cubPath, type CubDetail } from "../../features/cub";
  import { cubLive, cubStop, cubPost, cubSwitch } from "../../features/cubverbs";
  import CubControls from "../../features/cub/CubControls.svelte";
  import { put } from "../../lib/reads.svelte";
  import { CORE_CAPS, featureHref, featureLine, groupsOf, KIND_WASH, keyWord, perTopicWhere, settingsPath, stateOf, valueWords } from "./feature";

  let { view }: { view: View } = $props();
  const H = $derived(!!ui.facts?.header.host);
  const fs = $derived.by(() => {
    void view.tick;
    return features(H);
  });
  // the feature's id is the address's (a sheet open on the page makes w.id the selection's)
  const id = $derived(view.w.r.path[1] || "");
  const f = $derived(fs?.features.find((x) => x.id === id) || null);
  const g = $derived(f ? groupsOf(f) : null);
  const isCub = $derived(!!f && f.trust !== "first-party");
  const detail = $derived.by(() => {
    void view.tick;
    return f && isCub ? read<CubDetail>(cubPath(f.id), 20000) : null;
  });
  const cub = $derived(detail?.data || null);
  const place = $derived.by(() => {
    void view.tick;
    return f ? placeOf(arrangement(H), f.id, f.trust) : null;
  });
  const topics = $derived((app()?.host()?.topics as { id: number; name: string }[] | undefined) || []);
  const sel = (code: string): string => href(settingsPath(id), { ...view.w.r.q, sel: code });
  const ACCOUNT: Record<string, string> = { newsletter: "Your newsletter platform", mastodon: "Mastodon (posting)", sanity: "Sanity (your site)" };

  /** one key written (POST /api/f/<id>/settings), with Undo for 9 s; a sensitive key asks the house confirm */
  function write(x: FeatureRow, r: SettingRow, value: unknown, btn: HTMLElement | null): void {
    const L = app();
    if (!L) return;
    const old = r.value === undefined ? r.default : r.value;
    const body = (v: unknown) => ({ key: r.key, value: v, confirm: r.sensitive || undefined });
    const go = () => saveUndo(btn, {
      write: () => L.api(`/api/f/${x.id}/settings`, body(value)),
      what: () => `${keyWord(x, r)}: ${valueWords({ ...r, value }, topics)}`,
      effect: "run",
      undo: () => L.api(`/api/f/${x.id}/settings`, body(old)),
      after: () => L.afkStale(FEATURES_API),
    });
    if (r.sensitive) confirmThen(`Change ${keyWord(x, r)}?`, [`${x.title} asks the house confirm for this one.`, `It becomes ${valueWords({ ...r, value }, topics)}.`], "Change it", () => void go());
    else void go();
  }
  /** a core key for this cub (the shell's: may add rows to Needs you, to New) */
  function shell(key: string, value: boolean, btn: HTMLElement): void {
    const L = app();
    if (!L) return;
    void L.act(btn, async () => put(SHELL_API, await L.api(SHELL_API, { key, value })), () => L.say("Saved: the home follows it."));
  }
</script>

{#snippet sw(on: boolean, label: string, press: (btn: HTMLElement) => void, idv: string | null = null)}<button type="button" class="btn sm sw" role="switch" id={idv} aria-checked={on ? "true" : "false"} aria-label={label} onclick={(e) => { e.stopPropagation(); press(e.currentTarget); }}>{on ? "On" : "Off"}</button>{/snippet}

{#snippet keyRow(x: FeatureRow, r: SettingRow)}
  {#if r.per_topic}
    <Row title={keyWord(x, r)} meta={perTopicWhere(x)} href={x.id === "news" ? href("news/topics") : null} stw={SET_ST.set}>{#snippet st()}<Glyph name="dot" colour="blue" word="Set" />{/snippet}</Row>
  {:else if r.type === "bool" && !r.by_hand}
    {@const on = !!(r.value === undefined || r.value === null ? r.default : r.value)}
    {#snippet end()}{@render sw(on, keyWord(x, r), (b) => write(x, r, !on, b), "k-" + r.key)}{/snippet}
    {@const s = stateOf(r)}
    <Row title={keyWord(x, r)} meta={r.sensitive ? "the house confirm" : null} stw={s} {end}>{#snippet st()}<Glyph name={s[0]} colour={s[1]} word={s[2]} />{/snippet}</Row>
  {:else}
    <SetRow key={r.key} word={keyWord(x, r)} summary={r.by_hand ? `${valueWords(r, topics)} · written by hand in your settings file` : valueWords(r, topics)} state={stateOf(r)} />
  {/if}
{/snippet}

{#if !H}
  <List title="Settings"><Empty text="A feature's settings come from the server, which is not hosting this page." /></List>
{:else if !fs}
  <List title="Settings"><Loading /></List>
{:else if !f || !g}
  <List title={id} head={{ crumb: [{ to: settingsPath(id), w: id }] }}><Empty text={`There is no feature called ${id} on this Kranto.`} link={{ href: "#/settings", w: "Settings ›" }} /></List>
{:else}
  <List title={f.title} label={`Settings › ${f.title}`} head={{ crumb: [{ to: settingsPath(f.id), w: f.title }], trust: { w: trustWord(f.trust), cls: f.trust }, facts: featureLine(f), lede: f.says,
    glyph: glyphOf(f.manifest.ui.glyph), wash: KIND_WASH[f.manifest.ui.kind || ""] || "grey",
    primary: { label: `Open ${f.title} ›`, href: featureHref(f), id: "feature-open" }, gear: null }}>
    <Group id="fs-on" title="On and off" count="" kind="sets">
      {#if isCub}
        {@const on = cub ? cub.enabled : f.enabled}
        {#snippet end()}{@render sw(on, `${f.title} on`, (b) => cubSwitch(f.id, f.title, !on, b), "fs-enabled")}{/snippet}
        <Row title={f.title} meta={on ? "on: it runs when it is due" : "off: it runs nothing and adds no row"} {end} />
        {#each cub?.grants?.requests || [] as k (k)}
          {@const live = !!cub?.live.includes(k)}
          {@const schema = fs.request_schemas?.[k]}
          {#snippet lend()}<button type="button" class="btn sm sw" role="switch" id={"live-" + k} aria-checked={live ? "true" : "false"} onclick={(e) => cubLive(f.id, f.title, k, !live, fs.request_schemas || {}, e.currentTarget)}>{live ? "For real" : "Practice"}</button>{/snippet}
          <Row title={schema?.title || k} meta={live ? "for real: your approval does it" : "practice: your approval sends nothing"} end={lend} />
        {/each}
        {#if cub}
          {#snippet send()}{#if cub.state === "paused"}<button type="button" class="btn sm" id="fs-resume" onclick={(e) => cubPost(f.id, e.currentTarget, "resume", {}, `${f.title} runs again.`)}>Resume</button>{:else}<button type="button" class="btn sm" id="fs-stop" onclick={(e) => cubStop(f.id, f.title, e.currentTarget)}>Stop</button>{/if}{/snippet}
          <Row title={cub.state === "paused" ? "Stopped" : "Running when it is due"} meta={cub.state === "paused" ? cub.paused?.note || "by you" : "Stop ends its process and closes what it asks you"} end={send} />
        {/if}
      {:else if g.on}
        {@render keyRow(f, g.on)}
      {:else}
        <Empty li text={`${f.title} is always on.`} />
      {/if}
    </Group>
    {#each g.groups as gr (gr.word)}
      <Group id={"fs-g-" + gr.word.toLowerCase().replace(/[^a-z0-9]+/g, "-")} title={gr.word} count={String(gr.rows.length)} kind="sets">
        {#each gr.rows as r (r.key)}{@render keyRow(f, r)}{/each}
      </Group>
    {/each}
    {#if f.id === "news"}
      <Group id="fs-news-topics" title="Per topic" count="" kind="sets">
        <Row title="Each topic's News" meta="on or off, how often and at what hour: under News › Topics" href={href("news/topics")} />
      </Group>
    {/if}
    {#if g.advanced.length}
      <Group id="fs-advanced" title="Advanced" count={String(g.advanced.length)} kind="sets" fold={"fs-adv-" + f.id}>
        {#each g.advanced as r (r.key)}{@render keyRow(f, r)}{/each}
      </Group>
    {/if}
    {#if isCub && place}
      <Group id="fs-core" title="The core's keys" count="" kind="sets" says="what Kranto holds for this feature">
        <Row title="May add rows to Needs you" meta="also under Arrange on the home">{#snippet end()}{@render sw(place.needs_you, "May add rows to Needs you", (b) => shell(`shell.needs_you.${f.id}`, !place.needs_you, b), "k-needs")}{/snippet}</Row>
        <Row title="May add rows to New" meta="also under Arrange on the home">{#snippet end()}{@render sw(place.new, "May add rows to New", (b) => shell(`shell.new.${f.id}`, !place.new, b), "k-new")}{/snippet}</Row>
        {#each CORE_CAPS as [k, w] (k)}<SetRow key={"cap:" + k} word={w} summary={k === "monthly_usd" ? (cub?.spend.cap_usd == null ? "no cap" : `$${cub.spend.cap_usd.toFixed(2)}`) : k === "calls_per_day" ? String(cub?.spend.calls_per_day ?? "the default") : "the kind's own"} state={SET_ST.set} />{/each}
        <Row title="Updates" meta="an update that adds no permission applies by itself: Settings › System" href={href("settings/system")} />
      </Group>
    {/if}
    {#if Object.keys(f.manifest.broker || {}).length}
      <Group id="fs-accounts" title="Accounts it uses" count={String(Object.keys(f.manifest.broker || {}).length)} kind="sets">
        {#each Object.keys(f.manifest.broker || {}) as svc (svc)}<Row title={ACCOUNT[svc] || svc} meta="connect it, test it or sign out under Settings › Accounts" href={href("settings/accounts")} />{/each}
      </Group>
    {/if}
    <Group id="fs-spend" title="Spend" count="" kind="sets" says="every cap is on Spend">
      {#snippet right()}<a href={href("settings/spend")}>Spend ›</a>{/snippet}
      <Row title="This month" meta={f.spend ? `$${f.spend.month_usd.toFixed(2)} · ${f.spend.calls} model call${f.spend.calls === 1 ? "" : "s"}` : "nothing spent"} href={href("settings/spend")} />
      {#each g.caps as r (r.key)}{@render keyRow(f, r)}{/each}
    </Group>
    <Group id="fs-about" title="About" count="" kind="sets" fold={isCub ? null : "fs-about-" + f.id}>
      <Row title={isCub ? `${trustWord(f.trust)} · ${f.version}` : `Built in · ${f.version}`} meta={isCub ? "runs in Kranto's sandbox as its own process" : "in Kranto's own process"} />
      <SetRow key="about" word="What it may do" summary="its permissions, in words" state={SET_ST.ok} />
      {#snippet foot()}{#if isCub}<div class="fs-controls"><CubControls id={f.id} title={f.title} schemas={fs.request_schemas || {}} part="about" /></div>{/if}{/snippet}
    </Group>
  </List>
{/if}

<style>
  .fs-controls { padding: 4px 8px 8px; }
</style>
