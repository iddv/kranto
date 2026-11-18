<script lang="ts">
  // One topic's pages, the list: the topic itself, and its
  // Sources, Evidence and Map (Watch is topic-first: #/watch/topic/<id>[/sources|/evidence|
  // /map], "Robotics › Sources"); Themes and Ideas by their old addresses (a page it does
  // not know is the topic, as before). One read of /api/topics/<id> for all of them, shared with
  // the pane and the navigator's counts. Evidence is the library's Observations with the topic
  // fixed (library/ObsList); Map is the topic's themes, the map itself over them (its pane, which
  // dims the other topics' clusters). Without the server, it says topics need it.
  import List from "../../ui/List.svelte";
  import Loading from "../../ui/Loading.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { ui } from "../../lib/shell.svelte";
  import ObsList from "../library/ObsList.svelte";
  import TopicIdeas from "./TopicIdeas.svelte";
  import TopicOverview from "./TopicOverview.svelte";
  import TopicSources from "./TopicSources.svelte";
  import TopicThemes from "./TopicThemes.svelte";
  import { noTopic, pageName, subOf, topicApi, type TopicPage } from "./topics";

  let { view }: { view: View } = $props();
  const host = $derived(!!ui.facts?.header.host);
  // by the node (topics/<id>[/<page>]): the doors' address for a topic is watch/topic/<id>
  const id = $derived((view.w.node || "").split("/")[1] || "");
  const sub = $derived(subOf((view.w.node || "").split("/")[2]));
  const c = $derived.by(() => {
    void view.tick; // each draw may find the reads stale
    return host ? read<TopicPage>(topicApi(id), 20000) : null;
  });
  const t = $derived(c?.data || null);
</script>

{#if !host}
  <div data-title="Topics"><NeedHost what="Topics" /></div>
{:else if !t}
  <List title={pageName(sub)} label="Topic" crumb="Topics">{#if noTopic(c?.error)}<p class="empty">{`No topic ${id}.`}</p>{:else}<Loading error={c?.error} />{/if}</List>
{:else if sub === "evidence"}
  <ObsList {view} topic={t} />
{:else if sub === "themes"}
  <TopicThemes {t} at={view.tick} />
{:else if sub === "map"}
  <TopicThemes {t} at={view.tick} title={`${t.name} › Map`} />
{:else if sub === "ideas"}
  <TopicIdeas {t} at={view.tick} />
{:else if sub === "sources"}
  <TopicSources {view} {t} />
{:else}
  <TopicOverview {view} {t} />
{/if}
