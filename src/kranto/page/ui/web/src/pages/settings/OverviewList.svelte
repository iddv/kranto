<script lang="ts">
  // Settings › Overview (#/settings, g s;): one row per page, in the order you set
  // kranto up, each with its state in one line from the reads the app already keeps.
  import Group from "../../ui/Group.svelte";
  import { doorsNow } from "../../features/shell";
  import List from "../../ui/List.svelte";
  import Row from "../../ui/Row.svelte";
  import { capUsd, usd } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { href } from "../../lib/router";
  import { app, ui } from "../../lib/shell.svelte";
  import { shopOff } from "../../lib/app/data";
  import { keyWords, SETUP_API, type Setup } from "./keys.svelte";
  import { SETTINGS_PAGES, type SetPage } from "./pagedefs";
  import { ADVANCED_PAGES, doorsPage, DOORS_PAGES } from "./doorpages";
  import { PRIVACY_API, type Privacy } from "./privacy";
  import VersionCheck from "./VersionCheck.svelte";
  import Empty from "../../ui/Empty.svelte";
  import { features, trustWord } from "../../features/index";
  import { arrangement } from "../../features/shell";
  import { featureLine } from "./feature";

  let { view }: { view: View } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const reads = $derived.by(() => {
    void view.tick;
    return {
      s: host ? read<Setup>(SETUP_API, 10000) : null,
      p: host ? read<Privacy>(PRIVACY_API, 30000) : null,
      H: (app()?.host() || null) as { version?: string; topics?: unknown[]; spend_this_month_usd?: number; budget_usd?: number | null } | null,
    };
  });
  // the Features group: the home's order (its pins first), as the navigator lists the cubs
  const fx = $derived.by(() => {
    void view.tick;
    const f = features(host);
    if (!f) return null;
    const pins = arrangement(host)?.pins || [];
    const at = (id: string) => (id === "news" ? -1 : pins.includes(id) ? pins.indexOf(id) : pins.length + f.features.findIndex((x) => x.id === id));
    return f.features.slice().sort((a, b) => at(a.id) - at(b.id));
  });
  const MODE: Record<string, string> ={ off: "Nothing", local: "Local only", basic: "Basic", detailed: "Detailed" };
  /** a page's state in one line, or null while its reads arrive */
  function line(key: string): string | null {
    const { s, p, H } = reads;
    switch (key) {
      case "watching": return s?.data ? keyWords(s.data.key, Date.now(), s.data.logins?.claude ?? null).line : host ? null : "the server is not answering";
      case "sources": return H?.topics ? `${H.topics.length} active topics; their sources, Add source, and the accounts some are read with` : null;
      case "prompts": return "every prompt Kranto sends a model that you can steer";
      case "spend": return H?.spend_this_month_usd != null ? `watching ${usd(H.spend_this_month_usd)} this month, ${capUsd(H.budget_usd)}` : host ? null : "the server is not answering";
      case "privacy": return p?.data ? `usage reports: ${MODE[p.data.mode] || p.data.mode}` : host ? null : "the server is not answering";
      case "system": return H?.version ? `Kranto ${H.version} on ${location.host}` : `on ${location.host}`;
      case "appearance": return "light or dark, and the theme, in this browser";
      case "posting": return "the accounts a draft is sent with, and what Kranto writes";
      case "assistant": return "the console, what an assistant may do by itself, Kranto in your own client";
    }
    return null;
  }
  /** Advanced › switched on by hand: a page that is there only because a settings file
   * turns its feature on (cubs.developer) */
  function switched(): { to: string; title: string; why: string }[] {
    void view.tick;
    const out: { to: string; title: string; why: string }[] = [];
    if (!shopOff()) out.push({ to: "cubs/available", title: "Adding features", why: "cubs.developer" });
    return out;
  }
</script>

{#snippet version()}<p class="more vline"><VersionCheck id="set-version" /></p>{/snippet}

{#if doorsNow()}
  <!-- Settings: seven pages, then Advanced, folded: Prompts, and what a
       settings file switches on by hand; what you do is on its door -->
  {@const pages = DOORS_PAGES.map(doorsPage).filter((p): p is SetPage => !!p)}
  {@const adv = ADVANCED_PAGES.map(doorsPage).filter((p): p is SetPage => !!p)}
  {@const hand = switched()}
  <List title="Settings" sub="What you set up, in the order you set it up. Sources are on Watch.">
    <Group id="set-pages" title="Pages" count={String(pages.length)} kind="sets">
      {#each pages as pg (pg.key)}<Row title={pg.title} href={href("settings/" + pg.key)} meta={line(pg.key) ?? "reading…"}></Row>{/each}
      {#snippet foot()}{@render version()}{/snippet}
    </Group>
    <Group id="set-advanced" title="Advanced" count={String(adv.length + hand.length)} kind="sets" fold="settings:advanced" start>
      {#each adv as pg (pg.key)}<Row title={pg.title} href={href("settings/" + pg.key)} meta={line(pg.key) ?? pg.lede}></Row>{/each}
      {#each hand as h (h.to)}<Row title={h.title} href={"#/" + h.to} meta="switched on in your settings file"></Row>{/each}
    </Group>
    <!-- every feature and cub has its own page: a cub installed later is here by itself -->
    {#if host}
      <Group id="set-features" title="Features" count={fx ? String(fx.length) : null} kind="sets" says="what Kranto writes and posts" fold="settings:features" start>
        {#each fx || [] as x (x.id)}<Row title={x.title} href={href("settings/" + x.id)}>{#snippet meta()}<span class={"htag t-" + x.trust}>{trustWord(x.trust)}</span>{" " + featureLine(x)}{/snippet}</Row>{/each}
        {#if fx && !fx.length}<Empty li text="No feature yet." />{/if}
      </Group>
    {/if}
    {@render feedback()}
  </List>
{:else}
<List title="Settings" crumb="Overview">
  <Group id="set-pages" title="Pages" count={String(SETTINGS_PAGES.length)} kind="sets">
    {#each SETTINGS_PAGES as pg (pg.key)}<Row title={pg.title} href={href("settings/" + pg.key)} meta={line(pg.key) ?? "reading…"}></Row>{/each}
    {#snippet foot()}{@render version()}{/snippet}
  </Group>
  {@render feedback()}
</List>
{/if}

<!-- Feedback: the sheet, opened by ?feedback=1 on this page's address -->
{#snippet feedback()}
  <Group id="set-feedback-g" title="Feedback" count="" kind="sets">
    <Row title="Send feedback" href={href("settings", { feedback: "1" })} meta="a bug, an idea or a question: an issue on Kranto's GitHub, from you"></Row>
  </Group>
{/snippet}

<style>
  /* a phone (Settings on a phone is the seven pages and one line;): the
     Advanced, Features and Feedback groups stay wide only */
  @media (max-width: 759px) {
    :global(section[aria-labelledby="set-advanced"]), :global(section[aria-labelledby="set-features"]),
    :global(section[aria-labelledby="set-feedback-g"]) { display: none; }
  }
</style>
