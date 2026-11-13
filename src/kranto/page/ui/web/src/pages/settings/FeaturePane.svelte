<script lang="ts">
  // Settings › <Feature>, the sheet: a key's form (sel=e<key>): its words,
  // the field its type calls for (a number with its range, a choice, a list, the core's topic
  // picker), Save with Undo and Back to the default; a key written by hand is shown, never edited.
  // A cub's cap (sel=ecap:<name>), and what it may do in words (sel=eabout). With nothing chosen
  // (Classic's pane), what the page holds.
  import Detail from "../../ui/Detail.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Pane from "../../ui/Pane.svelte";
  import SaveBar from "../../ui/SaveBar.svelte";
  import SettingField from "../../ui/SettingField.svelte";
  import TopicPicker from "../../ui/TopicPicker.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { app, ui } from "../../lib/shell.svelte";
  import { confirmThen } from "../../ui/dialog.svelte";
  import { saveUndo } from "../../ui/save";
  import { groupOf, kindLine, SET_LEGEND, SET_ST } from "../../ui/settings";
  import { features, FEATURES_API, otherLine, type FeatureRow, type SettingRow } from "../../features/index";
  import { CANNOT, cubPath, permissionWords, type CubDetail } from "../../features/cub";
  import { CORE_CAPS, keyWord, perTopicWhere, stateOf, valueWords } from "./feature";

  let { view }: { view: View } = $props();
  const H = $derived(!!ui.facts?.header.host);
  const fs = $derived.by(() => {
    void view.tick;
    return features(H);
  });
  const f = $derived(fs?.features.find((x) => x.id === view.w.r.path[1]) || null);
  const code = $derived(groupOf(view.w));
  const r = $derived(f && code ? (f.settings || []).find((x) => x.key === code) || null : null);
  const cap = $derived(code && code.startsWith("cap:") ? CORE_CAPS.find(([k]) => k === code.slice(4)) || null : null);
  const detail = $derived.by(() => {
    void view.tick;
    return f && cap && f.trust !== "first-party" ? read<CubDetail>(cubPath(f.id), 20000) : null;
  });
  const topics = $derived((app()?.host()?.topics as { id: number; name: string }[] | undefined) || []);
  const now = $derived(r ? (r.value === undefined || r.value === null ? r.default : r.value) : null);
  // what is typed, until Save (a field never saves by itself)
  let typed = $state<string | null>(null);
  let chips = $state<(string | number)[] | null>(null);
  $effect(() => {
    void code;
    typed = null;
    chips = null;
  });
  const text = (v: unknown): string => (v == null ? "" : Array.isArray(v) ? v.join(", ") : String(v));
  const kindOf = (x: SettingRow) => (x.type === "usd" ? "money" : x.type === "int" || x.type === "float" ? "number" : x.type === "enum" ? "enum" : x.type === "bool" ? "bool" : x.type === "list" ? "list" : "text") as "money" | "number" | "enum" | "bool" | "list" | "text";
  /** what is typed as the key's value: a number, a list, a choice, or null for an empty cap */
  function parsed(x: SettingRow, t: string): unknown {
    const s = t.trim();
    if (x.type === "int" || x.type === "float" || x.type === "usd") return s === "" ? null : x.type === "int" ? Math.round(Number(s)) : Number(s);
    if (x.type === "bool") return s === "true";
    if (x.type === "list") return s.split(",").map((v) => v.trim()).filter(Boolean);
    return s === "" ? null : s;
  }
  function write(x: FeatureRow, k: SettingRow, value: unknown, btn: HTMLElement | null): void {
    const L = app();
    if (!L) return;
    const old = now;
    const body = (v: unknown) => ({ key: k.key, value: v, confirm: k.sensitive || undefined });
    const go = () => saveUndo(btn, {
      write: () => L.api(`/api/f/${x.id}/settings`, body(value)), what: () => `${keyWord(x, k)}: ${valueWords({ ...k, value }, topics)}`, effect: "run",
      undo: () => L.api(`/api/f/${x.id}/settings`, body(old)),
      after: () => {
        typed = null;
        chips = null;
        L.afkStale(FEATURES_API);
      },
    });
    if (k.sensitive) confirmThen(`Change ${keyWord(x, k)}?`, [`${x.title} asks the house confirm for this one.`, `It becomes ${valueWords({ ...k, value }, topics)}.`], "Change it", () => void go());
    else void go();
  }
  function writeCap(x: FeatureRow, name: string, t: string, btn: HTMLElement): void {
    const L = app();
    if (!L) return;
    const v = t.trim() === "" ? null : Number(t);
    void L.act(btn, () => L.api("/api/cubs/settings", { key: `cubs.${x.id}.${name}`, value: v, confirm: true }), () => {
      L.afkStale("/api/cubs");
      L.afkStale(FEATURES_API);
      L.say(`Saved: ${x.title}'s ${name.replace(/_/g, " ")} ${v == null ? "no cap" : v}.`);
    });
  }
</script>

<Detail back={view.back}>
  {#if !f}
    <div class="pane-empty"><p class="empty">{fs ? "No such feature." : "Loading…"}</p></div>
  {:else if r}
    {@const st = stateOf(r)}
    <Pane title={keyWord(f, r)} lede={r.by_hand ? "Written by hand in your settings file: shown here, changed there." : r.per_topic ? perTopicWhere(f) : null}>
      {#snippet kind()}<Glyph name={st[0]} colour={st[1]} word={st[2]} />{kindLine(f.title, r.group || (r.advanced ? "advanced" : "settings"))}{/snippet}
      {#snippet top()}
        {#if r.by_hand}
          <p class="small" id="fs-hand">{`${valueWords(r, topics)}: written by hand in your settings file, as `}<code>{r.key}</code>.</p>
        {:else if r.per_topic}
          <p class="small">{perTopicWhere(f)}.</p>
        {:else if r.type === "topics"}
          <p class="small muted">Which of your topics: none picked is every topic.</p>
          <TopicPicker id={"fs-k-" + r.key} value={now} pick={(ids, btn) => write(f, r, ids, btn)} />
        {:else if r.type === "list" && r.choices.length}
          {@const cur = chips ?? (Array.isArray(now) ? (now as (string | number)[]) : [])}
          <p class="chips" role="group" aria-label={keyWord(f, r)}>{#each r.choices as c (c)}<button type="button" class="chip" aria-pressed={cur.includes(c) ? "true" : "false"} onclick={() => (chips = cur.includes(c) ? cur.filter((v) => v !== c) : [...cur, c])}>{String(c)}</button>{" "}{/each}</p>
          <SaveBar id="fs-save" effect="run" disabled={chips == null} save={(b) => write(f, r, chips, b)} dflt={(b) => write(f, r, r.default, b)} />
        {:else}
          <SettingField id={"fs-k-" + r.key} label={keyWord(f, r)} kind={kindOf(r)} value={typed ?? text(now)} input={(t) => (typed = t)} choices={r.type === "enum" ? r.choices.map((c) => [String(c), String(c)]) : null}
            now={valueWords(r, topics)} dflt={r.default == null ? (r.type === "usd" ? "no cap" : null) : text(r.default)} min={r.lo} max={r.hi} step={r.type === "float" ? "any" : null} empty={r.type === "usd" ? "no cap" : null} />
          <SaveBar id="fs-save" effect="run" disabled={typed == null} save={(b) => write(f, r, parsed(r, typed ?? ""), b)} dflt={(b) => write(f, r, r.default, b)} note={r.sensitive ? "The house confirm." : null} />
        {/if}
        {#if otherLine(r)}<p class="muted small mt" id="fs-other-line">{otherLine(r)}</p>{/if}
        <p class="muted small mt" title={r.key}>{`Its key: ${r.key}`}</p>
      {/snippet}
    </Pane>
  {:else if cap}
    {@const c = detail?.data}
    <Pane title={cap[1]} lede="What Kranto holds for this cub; empty is the cub's default by its trust (yours: no cap).">
      {#snippet kind()}<Glyph name={SET_ST.set[0]} colour={SET_ST.set[1]} word={SET_ST.set[2]} />{kindLine(f.title, "the core's keys")}{/snippet}
      {#snippet top()}
        <SettingField id="fs-cap" label={cap[1]} kind={cap[0] === "monthly_usd" ? "money" : "number"} value={typed ?? (cap[0] === "monthly_usd" ? text(c?.spend.cap_usd) : cap[0] === "calls_per_day" ? text(c?.spend.calls_per_day) : "")} input={(t) => (typed = t)} />
        <SaveBar id="fs-save" effect="now" disabled={typed == null} save={(b) => writeCap(f, cap[0], typed ?? "", b)} note="The house confirm." />
        <p class="muted small mt">{`Its key: cubs.${f.id}.${cap[0]}`}</p>
      {/snippet}
    </Pane>
  {:else if code === "about"}
    <Pane title={`What ${f.title} may do`} lede={f.trust === "first-party" ? "One of Kranto's own features, in Kranto's own process." : "Runs in Kranto's sandbox as its own process; its manifest is pinned: a changed manifest without a new version refuses to run."}>
      {#snippet kind()}<Glyph name={SET_ST.ok[0]} colour={SET_ST.ok[1]} word={SET_ST.ok[2]} />{kindLine(f.title, "about")}{/snippet}
      {#snippet top()}<dl class="kv small" id="fs-perms">{#each permissionWords(f.manifest as unknown as Record<string, unknown>) as [k, w] (k)}<dt>{k}</dt><dd>{w}</dd>{/each}</dl><p class="muted small">{CANNOT}</p>{/snippet}
    </Pane>
  {:else if code}
    <div class="pane-empty"><p class="empty">No such setting.</p></div>
  {:else}
    <Pane title={`Settings › ${f.title}`} lede={f.says} sections={[{ id: "marks", w: "What the marks mean" }]}>
      {#snippet kind()}{kindLine(f.title).trim()}{/snippet}
      {#snippet section()}<dl class="kv small legend" id="marks-legend">{#each SET_LEGEND as [s, means] (s[2])}<dt><Glyph name={s[0]} colour={s[1]} word={s[2]} /></dt><dd>{means}</dd>{/each}</dl>{/snippet}
    </Pane>
  {/if}
</Detail>
