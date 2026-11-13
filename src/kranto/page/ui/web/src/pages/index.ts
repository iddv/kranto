// Every page, by its route's node (lib/pages.svelte.ts). Each is its own chunk, loaded the first
// time its route opens. A route with no page here says Not found (Missing.svelte), a pane with
// none says what it is about (PaneEmpty.svelte).
import { lazy, register } from "../lib/pages.svelte";
import { TPAGES } from "./topics/topics";
// the features' pages (News) register themselves from their slot registry
import "../features/index";

// Settings: the Overview (#/settings, g s) and seven pages in the order you
// set kranto up, then Advanced. A page of several of today's lists draws their groups under one title (ui/Parts) and
// opens today's panes by the selection; every old route redirects here (lib/nodes.json).
register("settings", {
  list: lazy(() => import("./settings/OverviewList.svelte")),
  pane: lazy(() => import("./settings/OverviewPane.svelte")),
});
// Settings › <Feature>: every feature's and cub's own page, #/settings/<id>,
// generated from its manifest (the route after Settings' own pages in nodes.json)
register("settings/feature", {
  list: lazy(() => import("./settings/FeaturePage.svelte")),
  pane: lazy(() => import("./settings/FeaturePane.svelte")),
});
register("settings/watching", {
  list: lazy(() => import("./settings/WatchingList.svelte")),
  pane: lazy(() => import("./settings/WatchingPane.svelte")),
});
// Sources: every source (a source at settings/sources/:id, also away from home), Add source
// (settings/sources/new) and the accounts sources are read with (an account sel=eacct:<id>, a
// site's page at settings/connections/:key)
register("settings/sources", {
  list: lazy(() => import("./settings/SourcesList.svelte")),
  pane: lazy(() => import("./settings/SourcesPagePane.svelte")),
});
register("settings/prompts", {
  list: lazy(() => import("./settings/PromptsList.svelte")),
  pane: lazy(() => import("./settings/PromptsPane.svelte")),
});
register("settings/spend", {
  list: lazy(() => import("./settings/SpendList.svelte")),
  pane: lazy(() => import("./settings/SpendPane.svelte")),
});
register("settings/privacy", {
  list: lazy(() => import("./settings/PrivacyAccessList.svelte")),
  pane: lazy(() => import("./settings/PrivacyAccessPane.svelte")),
});
register("settings/system", {
  list: lazy(() => import("./settings/SystemList.svelte")),
  pane: lazy(() => import("./settings/SystemPane.svelte")),
});
// Settings › Posting: the accounts a draft is sent with, what Kranto writes
register("settings/posting", {
  list: lazy(() => import("./settings/PostingList.svelte")),
  pane: lazy(() => import("./settings/AccountsPane.svelte")),
});
// Settings › Posting › How you write: the prose profile, a page you tune
register("settings/voice", { list: lazy(() => import("./settings/VoicePage.svelte")) });
// Settings › Assistant: the console's settings and the ladder
register("settings/assistant", {
  list: lazy(() => import("./settings/AssistantList.svelte")),
  pane: lazy(() => import("./settings/AssistantPane.svelte")),
});
register("settings/appearance", {
  list: lazy(() => import("./settings/AppearanceList.svelte")),
  pane: lazy(() => import("./settings/AppearancePane.svelte")),
});
// First run, stage routes (drawn without the panes: a stage page is its route's list, at the
// stage's full width): the splash (#/hello) and setup's three steps (#/welcome, welcome/topics,
// welcome/finish, one node)
register("hello", { list: lazy(() => import("./welcome/Hello.svelte")) });
// The home (mock D), a stage like Welcome: #/ draws it while shell.home is on
register("home", { list: lazy(() => import("./front/Home.svelte")) });
// What Kranto is doing: #/activity, g a, the top bar's indicator; a stage in both
// layouts
register("activity", { list: lazy(() => import("./activity/Activity.svelte")) });
// A cub's page, drawn from its manifest: #/cub/<id>, a stage too
// a cub's objects open in the shell's one sheet (CubPane: the pane beside the list in Classic), and
// one you read opens as a page
register("cub", { list: lazy(() => import("../features/cub/CubPage.svelte")), pane: lazy(() => import("../features/cub/CubPane.svelte")) });
register("cub/o", { list: lazy(() => import("../features/cub/CubObjectPage.svelte")) });
register("post/d", { list: lazy(() => import("../features/post/DraftPage.svelte")) });
// Cubs: Installed, Available, Made by Kranto, Tickets; Check a manifest (sel=add)
register("cubs", { list: lazy(() => import("../features/cub/CubsPage.svelte")), pane: lazy(() => import("../features/cub/CubsPane.svelte")) });
register("welcome", { list: lazy(() => import("./welcome/Welcome.svelte")) });
// Post, the fourth door: the drafts that wait, what was sent, the accounts
register("post", { list: lazy(() => import("./post/PostPage.svelte")) });
// Topics › Add topic: the form in the list (onboarding's step 2 draws it too), its side in the pane
register("topics/new", {
  list: lazy(() => import("./welcome/AddTopic.svelte")),
  pane: lazy(() => import("./welcome/AddTopicPane.svelte")),
});
// A topic's pages (every topic is Watch › Topics; #/watch/topic/<id> and its Sources, Evidence
// and Map, WT), by their route's node (topics/:id is the topic; Evidence, Themes, Ideas,
// Sources, Map): one list component for all of them, so a change of page keeps it, and the topic
// in the pane; a topic's Map has the map there (drawn over the column in the new frame)
const topicList = lazy(() => import("./topics/TopicList.svelte"));
const topicPane = lazy(() => import("./topics/TopicPane.svelte"));
for (const [sub] of TPAGES) register("topics/:id" + (sub ? "/" + sub : ""), { list: topicList, pane: sub === "map" ? lazy(() => import("./library/MapPane.svelte")) : topicPane });
// A run's agent trace: a full page, a stage like the cub's (the spans and the
// inspector need the width): a console session's, a research run's, one of the server's runs
// (#/sessions/<tid>/trace, #/research/<id>/trace, #/afk/<id>/trace)[?span=<id>]
register("trace", { list: lazy(() => import("./trace/TracePage.svelte")) });
// Ideas: the list (its groups), a card in the pane (ideas/:id, and sel=i<id> away from
// home: a Needs you row, a topic's Ideas)
register("ideas", {
  list: lazy(() => import("./ideas/IdeasList.svelte")),
  pane: lazy(() => import("./ideas/IdeaPane.svelte")),
});
// Needs you (#/needs): the one inbox grouped by verb; a row that is not an
// object's own route (a topic's proposals, a message, the review queue: sel=p, m, r) opens in its
// pane, as it does beside any list
register("needs", {
  list: lazy(() => import("./front/NeedsPage.svelte")),
  pane: lazy(() => import("./front/NeedsPane.svelte")),
});
// Watch (with the doors on): Topics as the digest (a topic's sheet, sel=t<id>;
// its page is watch/topic/<id>, the topic's node, with its pane drawn in the column), Sources (what
// Settings › Sources was), Evidence (Observations, Rollups and every topic's Evidence), Map (the
// map over the themes: Map and Clusters), all topics at once: a topic's own are its pages (WT)
register("watch", { list: lazy(() => import("./watch/Topics.svelte")), pane: lazy(() => import("./topics/TopicPane.svelte")) });
register("watch/sources", { list: lazy(() => import("./watch/Sources.svelte")), pane: lazy(() => import("./settings/SourcesPagePane.svelte")) });
register("watch/evidence", { list: lazy(() => import("./watch/Evidence.svelte")), pane: lazy(() => import("./watch/EvidencePane.svelte")) });
register("watch/map", { list: lazy(() => import("./watch/Map.svelte")), pane: lazy(() => import("./library/MapPane.svelte")) });
// Review: this week's queue as the list (the progress bar its toolbar), the current item in
// the pane; keys only (QUEUE_KEYS), the pointer works too
register("review", {
  list: lazy(() => import("./review/ReviewList.svelte")),
  pane: lazy(() => import("./review/ReviewPane.svelte")),
});

// The Library: Observations (an observation at library/o/:id; a search's compacted week,
// sel=u<id>), Map (its pane the SVG), Clusters (a theme at library/clusters/:n) and Rollups.
register("library", {
  list: lazy(() => import("./library/ObsList.svelte")),
  pane: lazy(() => import("./library/ObsPane.svelte")),
});
register("library/map", {
  list: lazy(() => import("./library/MapList.svelte")),
  pane: lazy(() => import("./library/MapPane.svelte")),
});
register("library/clusters", {
  list: lazy(() => import("./library/ClustersList.svelte")),
  pane: lazy(() => import("./library/ThemePane.svelte")),
});
register("library/rollups", {
  list: lazy(() => import("./library/RollupsList.svelte")),
  pane: lazy(() => import("./library/RollupPane.svelte")),
});

