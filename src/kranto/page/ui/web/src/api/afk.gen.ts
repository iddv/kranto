// Generated from the server's web/types.py; do not edit: change the Python side and
// run the server's scripts/gen_ts.py with this file's path. A test fails when it is
// stale.
export const HOST_API_VERSION = 2;
export type FromTextStatus = "valid" | "unverified" | "invalid" | "not_found" | "refused" | "connect_first" | "already_proposed" | "already_watching";
export type QueueSlot = "build" | "card";

export interface Tokens {
  in: number;
  out: number;
}

/** The latest grade on a target (``grades.latest``): from the ``grades`` table or the app's ``feedback``. */
export interface Grade {
  id: number;
  target: string;
  target_id: string;
  grade: string;
  note: string | null;
  context: string;
  created_at: string;
  table: "grades" | "feedback";
  reasons?: unknown;
  origin?: string | null;
  [key: string]: unknown;
}

export interface GradeBrief {
  grade: string;
  created_at: string;
}

/** A message (strike, heartbeat or alarm), as on the Health page and in the feed. */
export interface Message {
  id: number;
  kind: "strike" | "heartbeat" | "alarm";
  dedup_key: string;
  origin: string;
  title: string;
  body: string;
  links: string[];
  evidence_ids: number[];
  created_at: string;
  grade?: GradeBrief | null;
}

/** An observation's own fields as the JSON API shows them (``app._public``). */
export interface ObservationPublic {
  id: number;
  kind: string;
  title: string | null;
  summary: string;
  why_it_matters: string;
  content_quality: number;
  durability: number;
  opportunity: number;
  signal: number;
  override: boolean;
  override_reason: string | null;
  tags: string[];
  source_url: string | null;
  source_excerpt: string | null;
  item_published_at: string | null;
  source_id: number | null;
  source_label: string | null;
  admitted_by: string | null;
  created_at: string;
  llm_call_id: number | null;
  prompt_version: string | null;
}

/** An observation as the JSON API shows it (``app._public``); ``new`` and ``grade`` on the library's rows, ``score`` and ``weak`` on a search's. */
export interface Observation {
  id: number;
  kind: string;
  title: string | null;
  summary: string;
  why_it_matters: string;
  content_quality: number;
  durability: number;
  opportunity: number;
  signal: number;
  override: boolean;
  override_reason: string | null;
  tags: string[];
  source_url: string | null;
  source_excerpt: string | null;
  item_published_at: string | null;
  source_id: number | null;
  source_label: string | null;
  admitted_by: string | null;
  created_at: string;
  llm_call_id: number | null;
  prompt_version: string | null;
  grade: GradeBrief | null;
  new?: boolean;
  score?: number;
  weak?: boolean;
}

/** An observation as a list row (``kranto_api._brief``). */
export interface ObservationBrief {
  id: number;
  title: string | null;
  summary: string;
  signal: number;
  kind: string;
  source_label: string | null;
  created_at: string;
}

export interface Synthesis {
  text: string;
  input_ids: number[];
}

/** What compaction kept of expired observations (``app._rollup``); ``score`` on a search's. */
export interface Rollup {
  id: number;
  period_start: string;
  period_end: string;
  first_at: string;
  last_at: string;
  size: number;
  source_mix: Record<string, number>;
  platform_mix: Record<string, number>;
  topic_mix: Record<string, number>;
  mean_signal: number;
  kind_counts: Record<string, number>;
  keywords: string[];
  name: string | null;
  summary: string | null;
  summary_call_id: number | null;
  urls: string[];
  embedding_model: string;
  replaced_count: number;
  replaced_fingerprint: string;
  run_uuid: string | null;
  created_at: string;
  label: string;
  score?: number;
}

export interface StatusTopic {
  id: number;
  name: string;
  description: string;
  kind: string;
  ref: string | null;
}

export interface StatusSource {
  id: number;
  kind: string;
  label: string;
  status: string | null;
  params: Record<string, unknown>;
}

export interface StatusRun {
  run_uuid: string;
  kind: string;
  status: string;
  started_at: string;
  finished_at: string;
  error: string | null;
}

/** How many pages the new version could not answer on this install's data, and the first one's error id (Send this error). */
export interface UpdateBroke {
  pages: number;
  error_id: string | null;
}

/** The header's update pill (``update.check.summary``). */
export interface UpdateSummary {
  available: string | null;
  installed: string | null;
  channel: string | null;
  chosen?: string;
  state: string;
  detail: string | null;
  reason: string | null;
  to: string | null;
  notes: string[];
  notes_url: string | null;
  can_apply: boolean;
  checked_at: string | null;
  check_failing: string | null;
  failing_since: string | null;
  broke?: UpdateBroke | null;
}

export interface Hold {
  reason: string;
  since: string;
  stopped: unknown[];
}

/** How far a running ingest is (``tick.Progress``): source ``source_index`` of ``sources``, its ``item`` of ``items`` (None until fetched), the run's ``done_items`` and ``kept`` so far. */
export interface IngestProgress {
  run_uuid: string;
  started_at: string;
  sources: number;
  source_index: number;
  source: string | null;
  items: number | null;
  item: number;
  done_items: number;
  kept: number;
}

/** ``/api/status``'s ``preview`` (``kranto.preview.status``): the status bar's sentence, when the copy was taken, and the branch commits it was built from (None when unknown). */
export interface PreviewStatus {
  line: string;
  copied_at: string | null;
  commits: Record<string, string> | null;
}

/** ``/api/status``: what the header and the shell read; ``host_api`` is this module's ``HOST_API_VERSION``. */
export interface Status {
  version: string;
  host_api: number;
  observations: number;
  rollups: number;
  spend_this_month_usd: number;
  budget_usd: number | null;
  tokens_today: Tokens | null;
  paused: string | null;
  preview: PreviewStatus | null;
  topics: StatusTopic[];
  sources: StatusSource[];
  runs: StatusRun[];
  scheduler: boolean;
  running: string | null;
  ingest_progress: IngestProgress | null;
  next_run: Record<string, string | null>;
  lanes: Record<string, Record<string, unknown>>;
  update: UpdateSummary;
  hold: Hold | null;
  builds: boolean;
  browser: boolean;
  cubs_developer: boolean;
}

/** One topic with its facts (``topics_api._facts``). */
export interface Topic {
  id: number;
  name: string;
  description: string;
  kind: string;
  ref: string | null;
  status: "active" | "paused" | "archived";
  created_at: string;
  sources: number;
  proposed: number;
  items_per_day: number;
  kept_per_day: number;
  observations: number;
  themes: number;
  rising: number;
  spend_month_usd: number;
  tokens_month: Tokens | null;
}

/** A watched source with no topic: the broad lane. */
export interface BroadSource {
  id: number;
  label: string;
  kind: string;
  items_per_day: number;
  kept_per_day: number;
  wildcard: boolean;
}

export interface TopicsAll {
  observations: number;
  sources: number;
  themes: number;
  items_per_day: number;
  map: string | null;
}

/** ``/api/topics?kind=``: ``topics`` active and paused, ``archived`` the owner's archived ones. */
export interface Topics {
  topics: Topic[];
  archived: Topic[];
  broad: BroadSource[];
  all: TopicsAll;
  progress: string;
  every_hours: number;
  theme_min_share: number;
}

export interface TopicRef {
  id: number;
  name: string;
}

/** A topic a source feeds (``topic_links``), with its kind: user (yours) or project. */
export interface SourceLink {
  id: number;
  name: string;
  kind: string;
}

export interface SourceValidation {
  status?: string;
  items?: number;
  recent?: number;
  median_similarity?: number;
  error?: string;
  discovered_from?: string;
  checked?: string;
  from?: string;
  batch?: string;
  latest?: string;
  topic_id?: number;
  role?: string;
  preset?: string;
  why?: string;
  replaces?: string;
}

export interface Mute {
  muted_until: string | null;
  read_less: boolean;
  since: string;
}

/** The owner's latest grade of each of a source's observations, trailing 90 days (``source_health.source_grades``), and the why chips given. */
export interface SourceGrades {
  useful: number;
  not_useful: number;
  wrong: number;
  missed: number;
  reasons: Record<string, number>;
}

/** A paid API's reads for one source (X, ``spend.by_source``): this month's estimate at list price and how many resources, and what one fetch reads at most. */
export interface SourceSpend {
  usd: number;
  reads: number;
  run_usd: number;
}

/** The owner's latest Keep of a source Kranto recommended removing (``source_rule.keeps``). */
export interface SourceKept {
  at: string;
  row: number;
  down: number;
  up: number;
  window_days: number;
}

/** The source rule's state (``source_rule.state``,): ``recommend`` when its downvoted posts since the window's start (or the latest Keep) call for removal. */
export interface SourceRemoval {
  recommend: boolean;
  down: number;
  up: number;
  window_days: number;
  kept: SourceKept | null;
}

/** A source as Settings › Sources lists it (``source_health.list_sources``). */
export interface Source {
  id: number;
  kind: string;
  label: string;
  origin: "manual" | "scout" | "import";
  review: string | null;
  group: string;
  status: string;
  detail: string;
  site: string;
  site_name: string;
  preset: string | null;
  fields: Record<string, unknown> | null;
  topics: SourceLink[];
  proposed_for: string | null;
  found_for: SourceLink | null;
  why: string | null;
  replaces: unknown;
  validation: SourceValidation;
  items_7d: number;
  items_per_day: number | null;
  kept_30d: number;
  judged_30d: number;
  kept_rate: number | null;
  yield_per_day: number;
  mute: Mute | null;
  grades: SourceGrades | null;
  removal: SourceRemoval | null;
  last_fetch: string | null;
  last_error: string | null;
  retry_at: string | null;
  failing_runs: number;
  backoff_until: string | null;
  needs_fixing: boolean;
  connection: string | null;
  retention_days: number | null;
  note: string | null;
  spend: SourceSpend | null;
}

/** An active topic a source can be added to, with its watched sources. */
export interface SourceTopic {
  id: number;
  name: string;
  description: string;
  kind: string;
  ref: string | null;
  sources: number;
}

export interface RedditNote {
  watched: number;
  note: string;
}

/** ``/api/sources``. */
export interface Sources {
  sources: Source[];
  topics: SourceTopic[];
  reddit: RedditNote;
  connections_need_you: number;
  every_hours: number;
  default_retention_days: number;
}

/** One fetch of a source, in a run or by Fetch now (a ``source_fetches`` row). */
export interface SourceFetch {
  id: number;
  source_id: number;
  run_uuid: string | null;
  trigger: "run" | "manual";
  state: "ok" | "paced" | "failing" | "needs_login";
  fetched: number;
  new: number;
  error: string | null;
  created_at: string;
  retry_at: string | null;
}

/** How a source is read (``source_health.describe``). */
export interface SourceHow {
  request: string | null;
  pacing: string;
  terms: string;
}

/** A topic a source feeds, on the source's page: the topic's watched sources and the items they kept this month. */
export interface SourceTopicFacts {
  id: number;
  name: string;
  kind: string;
  status: string;
  sources: number;
  kept_month: number;
}

/** This month's model calls on a source's items (``source_health.model_spend``). */
export interface SourceModelSpend {
  usd: number;
  tokens: Tokens | null;
}

/** ``/api/sources/<id>``: the source's row, its last seven fetches and how it is read (``source_health.source_detail``); each topic it feeds with that topic's counts, what it kept this month and what judging its items cost. Not found: 404 with ``error``. */
export interface SourcePage {
  id: number;
  kind: string;
  label: string;
  origin: "manual" | "scout" | "import";
  review: string | null;
  group: string;
  status: string;
  detail: string;
  site: string;
  site_name: string;
  preset: string | null;
  fields: Record<string, unknown> | null;
  topics: SourceLink[];
  proposed_for: string | null;
  found_for: SourceLink | null;
  why: string | null;
  replaces: unknown;
  validation: SourceValidation;
  items_7d: number;
  items_per_day: number | null;
  kept_30d: number;
  judged_30d: number;
  kept_rate: number | null;
  yield_per_day: number;
  mute: Mute | null;
  grades: SourceGrades | null;
  removal: SourceRemoval | null;
  last_fetch: string | null;
  last_error: string | null;
  retry_at: string | null;
  failing_runs: number;
  backoff_until: string | null;
  needs_fixing: boolean;
  connection: string | null;
  retention_days: number | null;
  note: string | null;
  spend: SourceSpend | null;
  params: Record<string, unknown>;
  fetches: SourceFetch[];
  how: SourceHow;
  added_at: string;
  retention_override: boolean;
  retention_kind_days: number;
  topic_facts: SourceTopicFacts[];
  kept_month: number;
  spend_month: SourceModelSpend;
  every_hours: number;
}

export interface PresetField {
  key: string;
  label: string;
  placeholder: string;
  hint: string;
}

/** A kind of source in the catalog (``catalog.Preset.to_json``). */
export interface Preset {
  key: string;
  provider: string;
  provider_name: string;
  name: string;
  blurb: string;
  access: "public" | "login" | "not_offered";
  needs: string | null;
  available: boolean;
  reason: string | null;
  retention_days: number | null;
  fields: PresetField[];
}

export interface CatalogProvider {
  key: string;
  name: string;
  presets: Preset[];
}

/** An account connected for a provider, as the catalog lists it. */
export interface ConnectedAccount {
  instance: string;
  account: string;
  state: "connected" | "needs_login";
}

/** ``/api/catalog``: the presets by provider, the topics a source can be added to, the accounts connected per provider, the prefilter line. */
export interface Catalog {
  providers: CatalogProvider[];
  topics: SourceTopic[];
  connected: Record<string, ConnectedAccount[]>;
  prefilter: number;
}

export interface PreviewItem {
  title: string;
  url: string | null;
  link: string | null;
  published_at: string | null;
}

/** ``POST /api/sources/preview`` ({preset, fields, topic}): one fetch, nothing saved. A fetch that fails: 422 with ``error`` and ``state``. */
export interface SourcePreview {
  preset: string;
  kind: string;
  params: Record<string, unknown>;
  label: string;
  existing_id: number | null;
  prefilter: number;
  retention_days: number | null;
  items: number;
  recent: number;
  median_similarity: number | null;
  newest: PreviewItem[];
}

export interface AccountSource {
  id: number;
  label: string;
}

export interface ConnectionTest {
  note: string | null;
  created_at: string;
}

/** A live connected account (``Connections.accounts``): never a secret. */
export interface ConnectionAccount {
  id: number;
  provider: string;
  provider_name: string;
  instance: string;
  account: string;
  scopes: string[];
  state: "connected" | "needs_login";
  note: string | null;
  connected_at: string;
  state_at: string;
  last_used_at: string | null;
  last_test: ConnectionTest | null;
  sources: AccountSource[];
  writes?: boolean;
}

/** What is pasted for a provider; a ``secret`` one is never echoed back. */
export interface ProviderField {
  key: string;
  label: string;
  placeholder?: string;
  secret?: boolean;
}

/** A provider as the Connections page lists it (``PROVIDER_INFO``, with ``client_set`` on a client provider, YouTube and X, and ``device`` on GitHub); one not offered has only its ``reason``. A client provider names its first part (``client_section``), what that part says until the client is saved (``client_ready``) and after Remove (``client_removed``); ``cost`` is what reading with it costs, for a paid API. */
export interface ConnectionProvider {
  key: string;
  name: string;
  state: "available" | "not_offered";
  flow?: "browser" | "paste" | "both" | "client";
  blurb?: string;
  redirect_host?: string;
  scopes?: string[];
  reads?: string;
  never?: string;
  revoke_at?: string;
  expiry?: string;
  steps?: string[];
  alt_steps?: string[];
  device_steps?: string[];
  fields?: ProviderField[];
  sources?: string[];
  reason?: string;
  client_set?: boolean;
  client_section?: string;
  client_ready?: string;
  client_removed?: string;
  cost?: string;
  device?: boolean;
  writes?: boolean;
  group?: "newsletter";
}

/** ``/api/connections``: the accounts, the providers, why connections are off (None: they are on), how tokens are kept, and each browser sign-in's callback path. */
export interface Connections {
  accounts: ConnectionAccount[];
  providers: ConnectionProvider[];
  unavailable: string | null;
  storage: Record<string, string>;
  callback: Record<string, string>;
}

/** A newsletter platform as the Connect dialog offers it (``newsletter.Platform.words``). */
export interface NewsletterPlatform {
  id: string;
  name: string;
  about: string;
  docs: string;
  can_schedule: boolean;
}

export interface NewsletterConnection {
  id: number;
  account: string;
  state: string;
}

/** ``/api/newsletter``: the platform in use (``None`` until one is connected; the words then say ``unnamed``), the ones offered, its connection, the from address and audience in words, whether an issue can go out now and what is missing. ``POST /api/newsletter/check`` answers the same with ``ok``, ``said`` and ``message``. */
export interface Newsletter {
  platform: NewsletterPlatform | null;
  name: string | null;
  unnamed: string;
  platforms: NewsletterPlatform[];
  connection: NewsletterConnection | null;
  from_address: string | null;
  audience: string | null;
  audiences: boolean;
  ready: boolean;
  missing: string[];
}

/** The endpoint's last answer to a key tried here (``setup.record_key_test``). */
export interface KeyTest {
  ok: boolean;
  detail: string;
  base_url: string;
  at: string;
}

/** Whether the watcher's provider has its key (never the key), the variable it is kept under, the endpoint (``openai_compat``), which provider, its last test. ``choice``, ``label`` and ``endpoint``: what the metered client uses (``providers.in_use``). */
export interface SetupKey {
  set: boolean;
  env: string;
  base_url: string;
  provider: string;
  choice: string;
  label: string;
  endpoint: string | null;
  test: KeyTest | null;
}

/** A key provider found or not (``providers.detect``); never the key. */
export interface ProviderKey {
  key_set: boolean;
  env: string;
  label: string;
}

export interface ProviderEndpoint {
  key_set: boolean;
  env: string;
  label: string;
  base_url: string | null;
}

/** Claude Code on this machine, from ``claude --version`` and ``claude auth status``; ``offered``: whether it can be chosen as the watcher's model; ``terms``: the sentence shown wherever it is chosen (an explicit choice, never the default). */
export interface ProviderClaudeCode {
  installed: boolean;
  version: string | null;
  logged_in: boolean;
  auth_method: string | null;
  subscription: string | null;
  token_in_service: boolean;
  offered: boolean;
  label: string;
  terms: string;
}

/** What the metered client sends with (``providers.in_use``): ``provider`` as the ledger records it, ``choice`` as offered (an endpoint at openrouter.ai is ``openrouter``), ``endpoint`` the URL its calls go to (None: Claude Code's login). */
export interface ProviderCurrent {
  provider: string;
  choice: string;
  label: string;
  endpoint: string | null;
  key_env: string | null;
  models: Record<string, string>;
  tiers: Record<string, string>;
  key_set: boolean;
}

/** ``/api/setup/provider``: what can serve the watcher's models, offered in ``choices`` order (``providers.detect``). */
export interface ProviderSetup {
  current: ProviderCurrent | null;
  choices: string[];
  anthropic: ProviderKey;
  openrouter: ProviderKey;
  openai_compat: ProviderEndpoint;
  claude_code: ProviderClaudeCode;
}

/** One of the two logins builds need; ``command`` is what to run when it is missing; ``installed`` (Claude Code's only: Welcome's Ready tells not installed from not signed in). */
export interface Login {
  ok: boolean;
  detail: string;
  command: string;
  installed?: boolean;
}

export interface SetupLogins {
  claude: Login;
  gh: Login;
}

export interface BuildChoice {
  mode: "auto" | "manual" | null;
  concurrency: number;
}

/** ``/api/setup``: whether setup is done, the key, the two logins, what builds may do; ``budget_usd`` None: no monthly cap. */
export interface Setup {
  done: boolean;
  done_at: string | null;
  needs_setup: boolean;
  key: SetupKey;
  logins: SetupLogins;
  builds_ok: boolean;
  build: BuildChoice;
  topics: number;
  sources: number;
  scheduler: boolean;
  budget_usd: number | null;
  cost: string;
  first_brief_minutes: number;
  every_hours: number;
  brb: boolean;
  builds: boolean;
}

/** A topic's part of Today: kept since the marker, its best three, proposed sources. */
export interface TodayTopic {
  id: number;
  name: string;
  status: "active" | "paused";
  kind: string;
  ref: string | null;
  new_kept: number;
  top: Observation[];
  proposed: number;
  proposed_ticked: number[];
  proposed_items_per_day: number;
}

/** A cluster's change since the previous map (``map.read.movement``). */
export interface Movement {
  since: string;
  delta: number;
  excess: number | null;
  points: number;
  new_total: number | null;
  new_in_cluster: number | null;
  expected_new: number | null;
  burst: number | null;
  entered_burst: boolean;
  p_value: number | null;
  q_value: number | null;
}

/** One map's measures of a lineage; older maps lack the later keys. */
export interface TrajectoryPoint {
  at: string;
  share: number;
  size: number;
  stories?: number | null;
  expected_share?: number | null;
  new_total?: number | null;
  new_in_cluster?: number | null;
  new_max_origin_share?: number | null;
  expected_new?: number | null;
  burst?: number | null;
  p_value?: number | null;
  q_value?: number | null;
  [key: string]: unknown;
}

/** A rising theme on Today, with the topic most of its stories come from. */
export interface RisingTheme {
  cluster: number;
  lineage_id: string;
  label: string;
  name: string | null;
  size: number;
  stories: number | null;
  keywords: string[];
  cross_source: boolean;
  rising: boolean;
  movement: Movement | null;
  trajectory: TrajectoryPoint[];
  source_mix: Record<string, number>;
  topic: TopicRef;
  topic_share: number;
}

export interface TopicName {
  id: number;
  name: string;
}

/** A source Kranto recommends removing (``source_rule.to_remove``): a Needs you row. */
export interface SourceToRemove {
  id: number;
  label: string;
  kind: string;
  down: number;
  up: number;
  window_days: number;
  topics: TopicName[];
  items_per_day: number;
}

/** A watched source failing run after run (``source_health.needs_fixing``). */
export interface FailingSource {
  id: number;
  label: string;
  kind: string;
  failing_runs: number;
  backoff_until: string | null;
  error: string | null;
}

export interface IngestLast {
  status: string;
  finished_at: string;
  contributed: number | null;
  error: string | null;
}

/** A provider's pause (a spend limit at the provider, a plan's usage window): watching resumes by itself at ``until``. */
export interface WatchPause {
  until: string;
  reason: string;
  provider: string;
}

/** Kranto's health word and why (``health.health``,): the status bar's word in every layout, and the console's answer to "why is Kranto degraded?". ``reason``: one line in plain words, None when Healthy; ``trace``: the run it is about (``#/afk/<run>/trace``). "Not set up yet" (grey): no source is watched and nothing was read, a new home, not a broken one. "Reading for the first time" (grey): sources are watched and no read has ended yet. */
export interface HealthWord {
  word: "Healthy" | "Degraded" | "Paused" | "Not set up yet" | "Reading for the first time";
  tone: "green" | "amber" | "grey";
  reason: string | null;
  at: string | null;
  run: string | null;
  trace: string | null;
}

export interface IngestLine {
  last: IngestLast | null;
  judge_calls_24h: number;
  judge_errors_24h: number;
  observations: number;
  sources: number;
  topics: number;
  paused: string | null;
  watch_paused: WatchPause | null;
  health: HealthWord;
}

/** ``/api/today?since=``: the inbox; ``topics`` are the user's, ``project_topics`` the page's. */
export interface Today {
  since: string;
  seen_at: string | null;
  now: string;
  default_window_hours: number;
  topics: TodayTopic[];
  project_topics: TodayTopic[];
  new_kept: number;
  proposed: number;
  rising: RisingTheme[];
  messages: Message[];
  sources_failing: FailingSource[];
  sources_to_remove: SourceToRemove[];
  ingest: IngestLine;
}

export interface Overrides {
  rated: number;
  set: number;
  lifted: number;
  refused: number;
  rate: number | null;
}

/** One source's part of an ingest run's summary (``tick.SourceReport``); ``label`` None on a summary that did not keep it (``stored.runs.SourceReport``). */
export interface RunSourceReport {
  label: string | null;
  source_id?: number;
  fetched?: number;
  judged?: number;
  contributed?: number;
  prefiltered?: number;
  fetch_error?: string | null;
  fetch_state?: string | null;
  retry_at?: string | null;
  waiting_until?: string | null;
  failing_runs?: number;
  not_reached?: boolean;
  empty_replies?: number;
  refused?: number;
  [key: string]: unknown;
}

/** A run's summary; its keys depend on the run's kind (ingest, compact, snapshot...). */
export interface RunSummary {
  contributed?: number | null;
  tokens?: Tokens | null;
  expired?: number | null;
  rollups?: number;
  overrides?: Overrides | null;
  sponsored?: number;
  sponsor_links?: number;
  sources?: RunSourceReport[];
  [key: string]: unknown;
}

export interface HealthRun {
  run_uuid: string;
  kind: string;
  status: string;
  started_at: string;
  finished_at: string;
  summary: RunSummary;
  error: string | null;
  tokens: Tokens | null;
}

export interface CompactRun {
  run_uuid: string;
  kind: string;
  status: string;
  started_at: string;
  finished_at: string;
  summary: RunSummary;
  error: string | null;
}

export interface Removed {
  table_name: string;
  n: number;
}

export interface Retention {
  line: string;
  last: CompactRun | null;
  rollups: number;
  replaced: number;
  removed: Removed[];
  last_purge: string | null;
}

/** Failed model calls over the last week, by purpose and HTTP status (0: none). */
export interface ModelError {
  purpose: string;
  http_status: number;
  n: number;
  last_at: string;
  example: string | null;
}

export interface Exploration {
  admitted_by: string;
  n: number;
  mean_signal: number | null;
  in_cross_source: number | null;
}

/** A strike gate decision with its candidate (``gate.recent_decisions``). ``promoted`` is SQLite's 0 or 1. */
export interface Decision {
  decision_id: number;
  promoted: number;
  reason: "promoted" | "below_threshold" | "no_threshold" | "warmup" | "refractory" | "weekly_cap" | "stale";
  threshold: number | null;
  detail: string;
  message_id: number | null;
  decided_at: string;
  candidate_id: number;
  origin: string;
  subject_key: string;
  score: number;
  title: string;
  created_at: string;
}

export interface Delivery {
  sent: string[];
  failed: number;
  last_error: string | null;
}

export interface Budget {
  monthly_usd: number | null;
  alarm_fraction: number;
}

/** ``strike:`` in the config, whole. */
export interface StrikeConfig {
  max_per_week: number;
  min_card_score: number;
  min_burst_score: number;
  min_watch_score: number;
  refractory_days: number;
  warmup_snapshots: number;
  warmup_days: number;
  [key: string]: unknown;
}

/** Kranto's memory and its caps (``memory.py``): ``level`` ``high`` past 80% of the lowest cap, ``uncapped`` with none. ``used_mb`` is the server's group (its builds included), or the process alone without one. */
export interface Memory {
  level: "ok" | "high" | "uncapped";
  used_mb: number | null;
  rss_mb: number | null;
  high_mb: number | null;
  max_mb: number | null;
  group: string | null;
  words: string;
}

/** ``/api/health``: what Settings › System › Health shows (the server's /health page). */
export interface Health {
  memory: Memory;
  month: string;
  spent_usd: number;
  tokens_month: Tokens | null;
  budget: Budget;
  alarm: boolean;
  paused: string | null;
  watch_paused: WatchPause | null;
  busy: boolean;
  can_run: boolean;
  running: string | null;
  ingest_progress: IngestProgress | null;
  next_run: Record<string, string | null>;
  lanes: Record<string, Record<string, unknown>>;
  api_key: boolean;
  models: Record<string, string>;
  outcomes: Record<string, number>;
  exploration: Exploration[];
  errors: ModelError[];
  runs: HealthRun[];
  messages: Message[];
  deliveries: Record<string, Delivery>;
  delivery_status: string;
  decisions: Decision[];
  strike: StrikeConfig;
  grade_labels: Record<string, string>;
  retention: Retention;
}

export interface Compacted {
  n: number;
  replaced: number;
}

/** ``/api/observations``: without ``q`` filtered and paged (``compacted``, ``progress``); with ``q`` a search (``query``; with ``cutoff=1`` also what /library says about it). */
export interface Observations {
  total: number;
  offset: number;
  cluster_label: string | null;
  seen_at: string | null;
  marker: string;
  since: string | null;
  new_total: number;
  results: Observation[];
  compacted?: Compacted;
  progress?: string;
  query?: string;
  cutoff?: number;
  off_topic_below?: number;
  closest?: number | null;
  rollups?: Rollup[];
}

/** ``/api/rollups``: newest first and paged (``total``, ``offset``), or with ``q`` the ``k`` best matches. */
export interface Rollups {
  rollups: number;
  replaced: number;
  retention_line: string;
  results: Rollup[];
  total?: number;
  offset?: number;
  query?: string;
}

/** One of the ``k`` nearest observations by meaning (``search.similar_to``). */
export interface Similar {
  id: number;
  score: number;
  weak: boolean;
}

/** A nearest observation that is still in the library, with its score. */
export interface Neighbour {
  id: number;
  kind: string;
  title: string | null;
  summary: string;
  why_it_matters: string;
  content_quality: number;
  durability: number;
  opportunity: number;
  signal: number;
  override: boolean;
  override_reason: string | null;
  tags: string[];
  source_url: string | null;
  source_excerpt: string | null;
  item_published_at: string | null;
  source_id: number | null;
  source_label: string | null;
  admitted_by: string | null;
  created_at: string;
  llm_call_id: number | null;
  prompt_version: string | null;
  score: number;
  weak: boolean;
}

/** The model call that judged an observation. */
export interface LlmCall {
  id: number;
  model: string;
  prompt_version: string | null;
  cost_usd: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  response: string | null;
  created_at: string;
}

/** The item an observation was read one step from (``library.parent_of``). */
export interface DiveParent {
  relation: "discussion" | "link" | "repository";
  id: number;
  title: string | null;
  summary: string;
}

/** An item read one step from this one (``library.children_of``). */
export interface DiveChild {
  relation: "discussion" | "link" | "repository";
  id: number;
  title: string | null;
  summary: string;
  signal: number;
  source_url: string | null;
}

/** What cites an observation: the cards (newest first) and the News briefs. */
export interface CitedBy {
  ideas: number[];
  briefs: number[];
}

/** ``/api/observations/<id>?k=``: everything /obs/<id> shows. Not found: 404 with ``error``. */
export interface ObservationPage {
  id: number;
  kind: string;
  title: string | null;
  summary: string;
  why_it_matters: string;
  content_quality: number;
  durability: number;
  opportunity: number;
  signal: number;
  override: boolean;
  override_reason: string | null;
  tags: string[];
  source_url: string | null;
  source_excerpt: string | null;
  item_published_at: string | null;
  source_id: number | null;
  source_label: string | null;
  admitted_by: string | null;
  created_at: string;
  llm_call_id: number | null;
  prompt_version: string | null;
  source_kind: string | null;
  topic_similarity: number | null;
  similar: Similar[];
  neighbours: Neighbour[];
  call: LlmCall | null;
  synthesis: Synthesis | null;
  dive_parent: DiveParent | null;
  dive_children: DiveChild[];
  grade: Grade | null;
  grade_choices: string[];
  grade_labels: Record<string, string>;
  cited_by: CitedBy;
  topics: SourceLink[];
}

/** A row's latest grade as the feedback read gives it (cleared grades left out). */
export interface FeedbackGrade {
  value: string;
  reasons: string[];
  created_at: string;
}

/** ``/api/feedback?target=&ids=``: the latest grade of each id that has one, by id. */
export interface FeedbackGrades {
  target: string;
  grades: Record<string, FeedbackGrade>;
}

/** One Parallax snapshot's measures of a theme. */
export interface ArchivePoint {
  at: string;
  share: number | null;
  size: number;
}

export interface ArchiveCard {
  id: number;
  kind: string | null;
  title: string | null;
  status: string;
}

/** A Parallax dispatch whose clusters a theme was, with the cards made from it. */
export interface ArchiveDispatch {
  dispatch_id: string | null;
  title: string | null;
  date: string | null;
  url: string | null;
  cards: ArchiveCard[];
}

/** A lineage of the archive's own clustering (``archive_api.theme_records``). */
export interface ArchiveTheme {
  lineage_id: string;
  name: string | null;
  named: boolean;
  names: string[];
  name_count: number;
  keywords: string[];
  alive: boolean;
  size: number;
  first_at: string;
  last_at: string;
  epochs: number;
  members: number;
  trajectory: ArchivePoint[];
  dispatches: ArchiveDispatch[];
  bundle: string;
}

/** ``/api/archive/themes``: every theme, alive first then by size. */
export interface ArchiveThemes {
  archive: string;
  themes: ArchiveTheme[];
  count: number;
}

/** The map's clusters against structure-free data (``compute.structure_null``); older maps lack the single-blob keys. */
export interface StructureNull {
  reps?: number;
  null_mean?: number;
  null_sd?: number;
  real?: number;
  z?: number | null;
  covariance_null_mean?: number;
  covariance_null_sd?: number;
  covariance_z?: number | null;
  clustered?: boolean;
  [key: string]: unknown;
}

/** How many distinct stories the map's observations tell (copies count once). */
export interface MapStories {
  observations: number;
  distinct: number;
  [key: string]: unknown;
}

/** A map's measures (``compute.cluster`` and the snapshot's); older maps lack some. */
export interface MapQuality {
  silhouette_umap?: number;
  silhouette_native?: number;
  structure_null?: StructureNull;
  stories?: MapStories;
  [key: string]: unknown;
}

export interface MapSnapshot {
  id: number;
  created_at: string;
  n: number;
  k: number;
  quality: MapQuality;
}

export interface MapCluster {
  cluster: number;
  label: string;
  name: string | null;
  keywords: string[];
  size: number;
  share: number;
  centroid_2d: number[];
  cross_source: boolean;
  max_source_share: number;
}

/** The map's points as columns: id, x, y, cluster (``c``), signal (``s``), text (``t``) and the index of its source in ``sources`` (``src``). */
export interface MapPoints {
  id: number[];
  x: number[];
  y: number[];
  c: number[];
  s: number[];
  t: string[];
  src: number[];
}

/** ``/api/map``: the latest snapshot. Before the first map: 404 with ``MapNotYet``. */
export interface Map {
  snapshot: MapSnapshot;
  density: number[][];
  clusters: MapCluster[];
  sources: string[];
  points: MapPoints;
}

export interface MapNotYet {
  error: string;
  progress: string;
  can_run: boolean;
}

/** A cluster of the latest map (``map.read.clusters``) with its synthesis and grade, as /clusters and a topic's themes share it. */
export interface ClusterRow {
  snapshot_id: number;
  cluster: number;
  lineage_id: string;
  size: number;
  share: number;
  stories: number | null;
  keywords: string[];
  name: string | null;
  name_call_id: number | null;
  label: string;
  source_mix: Record<string, number>;
  topic_mix: Record<string, number>;
  origin_mix: Record<string, number>;
  max_source_share: number;
  max_origin_share: number | null;
  cross_source: boolean;
  representatives: number[];
  trajectory: TrajectoryPoint[];
  movement: Movement | null;
  rising: boolean;
  synthesis: Synthesis | null;
  grade: Grade | null;
}

/** A cluster of the latest map as /clusters shows it (``map.read.clusters`` with its synthesis, grade and three examples). */
export interface Cluster {
  snapshot_id: number;
  cluster: number;
  lineage_id: string;
  size: number;
  share: number;
  stories: number | null;
  keywords: string[];
  name: string | null;
  name_call_id: number | null;
  label: string;
  source_mix: Record<string, number>;
  topic_mix: Record<string, number>;
  origin_mix: Record<string, number>;
  max_source_share: number;
  max_origin_share: number | null;
  cross_source: boolean;
  representatives: number[];
  trajectory: TrajectoryPoint[];
  movement: Movement | null;
  rising: boolean;
  synthesis: Synthesis | null;
  grade: Grade | null;
  centroid_2d: number[];
  examples: ObservationBrief[];
}

export interface ClusterSnapshot {
  id: number;
  created_at: string;
  n: number;
  k: number;
}

/** ``/api/clusters?sort=``; before the first map only ``snapshot`` (None), ``clusters`` (empty) and ``progress``. */
export interface Clusters {
  snapshot: ClusterSnapshot | null;
  clusters: Cluster[];
  quality?: Record<string, unknown>;
  sort?: string;
  grade_labels?: Record<string, string>;
  grade_choices?: string[];
  progress?: string;
}

/** A theme of a topic: a cluster of the latest map whose stories come from the topic's sources for at least ``theme_min_share`` of it, with that share. */
export interface TopicTheme {
  snapshot_id: number;
  cluster: number;
  lineage_id: string;
  size: number;
  share: number;
  stories: number | null;
  keywords: string[];
  name: string | null;
  name_call_id: number | null;
  label: string;
  source_mix: Record<string, number>;
  topic_mix: Record<string, number>;
  origin_mix: Record<string, number>;
  max_source_share: number;
  max_origin_share: number | null;
  cross_source: boolean;
  representatives: number[];
  trajectory: TrajectoryPoint[];
  movement: Movement | null;
  rising: boolean;
  synthesis: Synthesis | null;
  grade: Grade | null;
  topic_share: number;
}

/** A source as ``TopicsAPI.source_rows`` gives it: its row in Settings › Sources, the topic it was proposed for, its role (core, wildcard) and whether onboarding's proposal list ticks it (``pretick``). */
export interface SourceRow {
  id: number;
  kind: string;
  label: string;
  origin: "manual" | "scout" | "import";
  review: string | null;
  group: string;
  status: string;
  detail: string;
  site: string;
  site_name: string;
  preset: string | null;
  fields: Record<string, unknown> | null;
  topics: SourceLink[];
  proposed_for: string | null;
  found_for: SourceLink | null;
  why: string | null;
  replaces: unknown;
  validation: SourceValidation;
  items_7d: number;
  items_per_day: number | null;
  kept_30d: number;
  judged_30d: number;
  kept_rate: number | null;
  yield_per_day: number;
  mute: Mute | null;
  grades: SourceGrades | null;
  removal: SourceRemoval | null;
  last_fetch: string | null;
  last_error: string | null;
  retry_at: string | null;
  failing_runs: number;
  backoff_until: string | null;
  needs_fixing: boolean;
  connection: string | null;
  retention_days: number | null;
  note: string | null;
  spend: SourceSpend | null;
  proposed_topic: number | null;
  role: string;
  pretick: boolean;
}

/** One of a topic's sources, with the items a day it gave over the last seven days. */
export interface TopicSource {
  id: number;
  kind: string;
  label: string;
  origin: "manual" | "scout" | "import";
  review: string | null;
  group: string;
  status: string;
  detail: string;
  site: string;
  site_name: string;
  preset: string | null;
  fields: Record<string, unknown> | null;
  topics: SourceLink[];
  proposed_for: string | null;
  found_for: SourceLink | null;
  why: string | null;
  replaces: unknown;
  validation: SourceValidation;
  items_7d: number;
  items_per_day: number | null;
  kept_30d: number;
  judged_30d: number;
  kept_rate: number | null;
  yield_per_day: number;
  mute: Mute | null;
  grades: SourceGrades | null;
  removal: SourceRemoval | null;
  last_fetch: string | null;
  last_error: string | null;
  retry_at: string | null;
  failing_runs: number;
  backoff_until: string | null;
  needs_fixing: boolean;
  connection: string | null;
  retention_days: number | null;
  note: string | null;
  spend: SourceSpend | null;
  proposed_topic: number | null;
  role: string;
  pretick: boolean;
  items_per_day_7d: number;
}

export interface TopicSnapshot {
  id: number;
  created_at: string;
}

/** ``/api/topics/<id>``: the topic's facts, its themes, the ones rising now, its sources with the scout's proposals (``topics_api.one_topic``); ``budget_usd`` None: no monthly cap. Not found: 404 with ``error``. */
export interface TopicPage {
  id: number;
  name: string;
  description: string;
  kind: string;
  ref: string | null;
  status: "active" | "paused" | "archived";
  created_at: string;
  sources: number;
  proposed: number;
  items_per_day: number;
  kept_per_day: number;
  observations: number;
  themes: number;
  rising: number;
  spend_month_usd: number;
  tokens_month: Tokens | null;
  themes_list: TopicTheme[];
  rising_now: TopicTheme[];
  snapshot: TopicSnapshot | null;
  source_rows: TopicSource[];
  prefilter: number;
  every_hours: number;
  budget_usd: number | null;
  progress: string;
  grade_labels: Record<string, string>;
  grade_choices: string[];
  history: TopicChange[];
}

/** One of a new topic's four rows (``progress.topic_start``): Sources, First read, First brief, First ideas; ``at`` the time it happened or the scheduler's next run, None when neither is known; ``brief_id`` on the brief's row once written. */
export interface TopicStartRow {
  key: "sources" | "read" | "brief" | "ideas";
  title: string;
  state: "waiting" | "running" | "done" | "quiet" | "off" | "failed";
  words: string;
  at: string | null;
  brief_id?: number;
}

/** ``/api/topics/{id}/start``: a new topic's first hour; ``done`` once it has an idea card (the page then draws none of it); ``quiet`` the line under the rows. */
export interface TopicStart {
  topic_id: number;
  done: boolean;
  rows: TopicStartRow[];
  quiet: string | null;
  observations: number;
  needed: number;
}

/** One line of a topic's history (``library.topic_history``), newest first: ``what`` edit (``changed``: name, description; ``name`` the name it took), link or unlink (a source added or removed: ``source_id``, ``source`` its label), status (``status``); ``by`` the door it came through (ui, chat, mcp, cli), None on a status change. */
export interface TopicChange {
  what: "edit" | "link" | "unlink" | "status";
  at: string;
  by?: string;
  note: string | null;
  changed?: string[];
  name?: string;
  source_id?: number;
  source?: string | null;
  status?: string;
}

export interface TopicWords {
  name: string;
  description: string;
}

export interface TopicRevision {
  id: number;
  topic_id: number;
  changed: string[];
  by: string;
  created_at: string;
  before: TopicWords;
  after: TopicWords;
}

/** ``POST /api/topics/<id>``: the edit made (``revision``; ``before`` is what Undo sends back), or ``changed`` None when the words were the same. */
export interface TopicEdit {
  id: number;
  changed: string[] | null;
  revision: TopicRevision | null;
}

/** ``POST /api/topics/<id>/sources``: the sources linked and unlinked, and among them those approved (added back) or retired (left with no topic); ``remaining``: by removed source id, the topics it still feeds. */
export interface TopicSourcesChange {
  id: number;
  added: number[];
  removed: number[];
  retired: number[];
  approved: number[];
  remaining: Record<string, SourceLink[]>;
}

/** ``POST /api/topics/<id>/status``: ``was`` the status before (what Undo sends back). */
export interface TopicStatusChange {
  id: number;
  status: string;
  was: string | null;
  changed: boolean;
}

/** The scout run's live search (``scout.search_summary``): the chip "from Exa, searched 2026-10-17", or ``live`` false with the "no live search" sentence in ``note``. */
export interface ScoutSearch {
  live: boolean;
  backends: string[];
  searched_at: string | null;
  results: number;
  note: string | null;
}

export interface NoFeed {
  label: string;
  why: string | null;
}

/** What a finished scout found: the sources it proposed (new or already watched), how many failed validation, the sites live search found that have no feed, and the run's live search. */
export interface ScoutResult {
  message: string;
  proposals: SourceRow[];
  invalid: number;
  no_feed?: NoFeed[];
  search?: ScoutSearch | null;
}

/** The scout as a background job (``web/jobs.py``): ``result`` once it is done, ``error`` when it failed. */
export interface ScoutJob {
  key: string;
  state: "running" | "done" | "failed";
  started: number;
  finished: number | null;
  elapsed_s: number;
  result: ScoutResult | null;
  error: string | null;
}

/** ``/api/topics/<id>/scout``: GET the topic's scout job; POST starts it (202) or answers the one running. No job yet: 404 with ``error``. */
export interface Scout {
  job: ScoutJob;
}

/** An X line's cost at X's list price: what checking it read, one run, and a month at the configured cadence. */
export interface XCost {
  check: number;
  run: number;
  month: number;
}

export interface FromTextLine {
  status: "valid" | "unverified" | "invalid" | "not_found" | "refused" | "connect_first" | "already_proposed" | "already_watching";
  from: string;
  preset: string | null;
  fields: Record<string, string>;
  why: string | null;
  cost: XCost | null;
  source_id: number | null;
  label: string | null;
  row: SourceRow | null;
}

export interface FromTextCounts {
  valid: number;
  unverified: number;
  invalid: number;
  not_found: number;
  refused: number;
  connect_first: number;
  already_proposed: number;
  already_watching: number;
}

/** What resolving a pasted text found (``resolve.Batch``): ``id`` is ``fromtext:<call id>``; ``read`` and ``total`` are characters (the model reads at most 16,000); ``stopped_at`` names the first line past 50 proposals. */
export interface FromTextBatch {
  id: string;
  call_id: number;
  topic: number | null;
  lines: FromTextLine[];
  stopped_at: string | null;
  read: number;
  total: number;
  counts: FromTextCounts;
  message: string;
}

/** Resolving a pasted text as a background job (``web/jobs.py``), one at a time. */
export interface FromTextJob {
  key: string;
  state: "running" | "done" | "failed";
  started: number;
  finished: number | null;
  elapsed_s: number;
  result: FromTextBatch | null;
  error: string | null;
}

/** ``/api/sources/from-text``: POST ``{text, topic?}`` starts resolving (202) or answers the one running; GET the latest; ``/api/sources/from-text/<n>`` batch n again. None: 404 with ``error``. */
export interface FromText {
  job: FromTextJob;
}

export interface SkippedSource {
  id: number;
  why: string;
}

/** ``POST /api/sources/approve`` ``{ids, topic?}``: what was approved, what was not and why; ``first_read``: Watch these on a topic never read started its first read (``started``), found a job running (``busy``), or started nothing (None). */
export interface SourcesApproved {
  approved: number[];
  skipped: SkippedSource[];
  first_read: "started" | "busy" | null;
}

/** A topic whose sources the card's evidence came from, with how many of its citations and the share of them that did, as written at the card's insert (``idea_topics``); the name is the topic's current one. */
export interface IdeaTopic {
  id: number | null;
  name: string;
  kind: "user" | "project";
  n: number;
  share: number;
}

/** The card's theme: its lineage's latest cluster row. */
export interface IdeaTheme {
  lineage_id: string;
  name: string | null;
  keywords: string[];
  size: number;
  snapshot_id: number;
}

export interface IdeaDemand {
  statement: string | null;
  evidence: (Record<string, unknown>)[];
  supported: number;
}

export interface IdeaCitation {
  observation_id: number | null;
  url: string | null;
  date: string | null;
  observed_at: string | null;
  claim: string;
  source: string | null;
  for: string;
  verified?: string;
}

/** A claim the verifier dropped, and why. */
export interface IdeaDropped {
  n: number | null;
  claim: string | null;
  reason: string | null;
}

/** The card's prediction; a card written without one has neither key. */
export interface IdeaPrediction {
  statement?: string;
  by?: string | null;
}

/** One of the card writer's ratings; ``rated`` when it was capped. */
export interface IdeaRating {
  value: number;
  reason: string;
  cites?: number[];
  rated?: number;
  [key: string]: unknown;
}

export interface IdeaExisting {
  n: number | null;
  name: string | null;
  covers: string | null;
}

/** A cited observation as the card shows it: the live one, else the card's snapshot of it (``compacted``). */
export interface IdeaEvidence {
  n: number | null;
  claim: string | null;
  observation_id: number | null;
  summary: string | null;
  source: string | null;
  observed_at: string | null;
  url: string | null;
  compacted: boolean;
}

/** The owner's dispatch a card was made from (``Dispatch.provenance``); an older card's may lack keys. */
export interface IdeaDispatch {
  dispatch_id?: string;
  title?: string;
  slug?: string | null;
  url?: string | null;
  date?: string;
  generated_at?: string;
  strategy?: unknown;
  cluster_ids?: string[];
  excerpt?: unknown;
  file?: string;
  [key: string]: unknown;
}

/** An archive theme a dispatch's cluster was. */
export interface IdeaLineage {
  cluster_id: string;
  lineage_id: string | null;
  name: string | null;
}

/** A dispatch's link that matched no observation. */
export interface IdeaLink {
  url: string;
  claim: string;
}

/** The card's embedding: with ``embedding=ref`` only the model and a link to the card. */
export interface IdeaEmbedding {
  model: string;
  dim: number;
  href: string;
  text?: string;
  vector?: number[];
}

/** What the card prompt made for the weekly editor adds (each key only when written). */
export interface IdeaEditorNotes {
  kind?: string;
  existing?: IdeaExisting[];
  gap?: string;
  absorber?: string;
  facets?: string[];
  integration_point?: string;
  channel?: string;
}

/** One outcome on a card (``outcomes.public``); an editor outcome's ``detail`` has ``week`` and ``why``. */
export interface IdeaOutcome {
  id: number;
  kind: string;
  value: string;
  detail: Record<string, unknown>;
  source: string;
  created_at: string;
}

/** What the loop made of a card (``outcomes.built``): the newest build, gate or publish step's word (``state``), the loop's idea id, and the repo once published. Read from the rows the loop wrote before builds left Kranto (CUT); none come after. */
export interface IdeaBuilt {
  state: string;
  kind: "build" | "gate" | "publish";
  idea: string | null;
  repo: string | null;
  url: string | null;
  at: string;
}

/** One graded item's part of a card's taste (``taste.parts_of``), strongest first. */
export interface IdeaRankPart {
  weight: number;
  why: string;
  target: "idea" | "observation";
  target_id: string;
  value: string;
  graded_at: string;
  title: string;
}

/** Where the card ranks and why (``taste.rank``,): its place among the shown cards (None when unsupported), its taste, the one line a row shows ("" when none). */
export interface IdeaRank {
  position: number | null;
  taste: number;
  line: string;
  parts: IdeaRankPart[];
}

/** A ticket whose ``because.ideas`` names the card (``tickets.resting_on``; the one-card read only). */
export interface IdeaTicket {
  id: number;
  cub: string;
  kind: string;
  title: string;
  state: string;
  created_at: string;
}

/** What a card stands on (``cards.facts``): supported citations, supported demand citations, distinct sites; the order of /api/ideas and of Review's cards. */
export interface IdeaFacts {
  cited: number;
  asks: number;
  sources: number;
}

export interface IdeaPriorArtHit {
  label: string;
  url: string;
  title: string;
  date: string | null;
}

export interface IdeaPriorArtExisting {
  label: string;
  url: string;
  title: string;
  date: string | null;
  what: string;
}

/** The card's prior-art search: ``live`` false and ``note`` the "no live search" sentence when none ran. */
export interface IdeaPriorArt {
  live: boolean;
  searched_at: string;
  query: string;
  backends: string[];
  note: string | null;
  results: number;
  hits: IdeaPriorArtHit[];
  existing: IdeaPriorArtExisting[];
}

export interface IdeaNoveltyDropped {
  field: string;
  sentence: string;
  reason: string;
}

/** The newest news story that matches a card by the three rules. */
export interface IdeaNews {
  brief_id: number;
  n: number;
  topic_id: number;
  headline: string;
  date: string;
}

/** An idea card (``ideas_api.card_record``): its text, score, grade, theme and topics, #96's fields, its citations; the insight fields are None on cards written before them; a dispatch card (``origin`` dispatch) adds the pitch and its dispatch. */
export interface Idea {
  id: number;
  title: string;
  status: "shown" | "unsupported";
  score: number | null;
  grade: string | null;
  rank: IdeaRank | null;
  facts: IdeaFacts;
  created_at: string;
  origin: string;
  lineage_id: string | null;
  theme: IdeaTheme | null;
  topics: IdeaTopic[];
  topic: IdeaTopic | null;
  output_kind: string | null;
  one_liner: string;
  who: string | null;
  smallest_v1: string;
  demand: IdeaDemand | null;
  citations: IdeaCitation[];
  dropped: IdeaDropped[];
  thesis: string;
  pattern: string;
  where_now: string;
  cheapest_test: string;
  risks: string;
  why_selected: string;
  prediction: IdeaPrediction;
  ratings: Record<string, IdeaRating>;
  insight: string | null;
  existing: IdeaExisting[] | null;
  gap: string | null;
  moment: string | null;
  mechanism: string | null;
  editor_notes: IdeaEditorNotes | null;
  prior_art: IdeaPriorArt | null;
  novelty_dropped: IdeaNoveltyDropped[];
  outcome: IdeaOutcome | null;
  editor: IdeaOutcome | null;
  outcomes: Record<string, IdeaOutcome>;
  built: IdeaBuilt | null;
  state: "waiting" | "later" | "posted" | "passed";
  later_until: string | null;
  evidence: IdeaEvidence[];
  embedding: IdeaEmbedding;
  pitch?: string;
  pitch_text?: string;
  pitch_kind?: string | null;
  pitch_label?: string | null;
  dispatch?: IdeaDispatch;
  lineages?: IdeaLineage[];
  links?: IdeaLink[];
  tickets?: IdeaTicket[];
  news?: IdeaNews | null;
}

/** When the first cards come: words, the next map's time (None while fewer than ``needed`` items are kept), how many are kept and how many the map needs. */
export interface IdeasFirst {
  words: string;
  at: string | null;
  observations: number;
  needed: number;
}

/** ``/api/ideas?status=&topic=&origin=&kind=&embedding=``: the cards in the owner's order; ``first`` while there is no card and no filter. */
export interface Ideas {
  ideas: Idea[];
  count: number;
  first?: IdeasFirst;
}

/** ``POST /api/ideas/{id}/later`` (``idea.later``): the card's state after it. */
export interface IdeaLater {
  id: number;
  state: "waiting" | "later";
  later_until: string | null;
  outcome: IdeaOutcome;
}

/** One "why" chip of a target, with the key that presses it. */
export interface FeedbackChip {
  key: string;
  label: string;
  letter: string;
}

/** ``/api/feedback/vocabulary``: what the UI draws its grading controls and chips from. */
export interface FeedbackVocabulary {
  targets: string[];
  kinds: string[];
  grades: string[];
  pairs: string[];
  origins: string[];
  labels: Record<string, string>;
  chips: Record<string, FeedbackChip[]>;
}

/** One item of the review queue: a build (only its id; the page knows the rest) or a card. ``slot`` says why it is there, for the grade's context only. */
export interface QueueItem {
  slot: "build" | "card";
  target: "build" | "idea";
  id: number | string;
  title?: string | null;
  line?: string;
  topic?: string | null;
  facts?: string[];
}

/** ``/api/review/queue?builds=&size=``: this week's queue (``feedback.build_queue``) and the chips per target. */
export interface ReviewQueue {
  week: string;
  size: number;
  items: QueueItem[];
  chips: Record<string, FeedbackChip[]>;
}

export interface WebSearchHit {
  label: string;
  url: string;
  title: string;
  date: string | null;
  snippet: string;
  backend: string;
  query: string;
  rank: number;
}

/** ``/api/websearch?q=&recency=&kind=&n=&backend=&caller=``: dated results from the live web. ``backend`` null and ``note`` the "no live search" sentence when nothing answered. */
export interface WebSearchResults {
  query: string;
  backend: string | null;
  backends: string[];
  labels: string[];
  searched_at: string;
  cached: boolean;
  note: string | null;
  live: boolean;
  hits: WebSearchHit[];
}

export interface SearchChoice {
  provider: "exa" | "brave" | "tavily" | "anthropic" | "none";
  label: string;
  key_env: string | null;
  key_set: boolean | null;
}

export interface SearchMonth {
  label: string;
  usd: number;
  reads: number;
  requests: number;
}

/** ``/api/setup/search``: live search's backend (``web`` null: none), its label (Exa's free mode says so), the free backends, each caller's switch, this month per backend, the cap, and the sentence every caller says with no live search. */
export interface SearchSetup {
  provider: string;
  web: string | null;
  web_label: string | null;
  free_mode: boolean;
  free: string[];
  note: string | null;
  monthly_usd: number | null;
  callers: Record<string, string>;
  failing: Record<string, number>;
  choices: SearchChoice[];
  free_mode_words: string | null;
  recent_weeks: number;
  cache_hours: number;
  month: Record<string, SearchMonth>;
  no_search: string;
}

/** ``/api/websearch/fetch?url=&max_chars=``: a page's text, or why it was not read. */
export interface WebFetch {
  url: string;
  text: string;
}

/** ``unreadable`` on a row that could not be built (``rowsafe``, RCA A3): what it is, the words the list shows, the error's id and class. */
export interface UnreadableMark {
  what: string;
  words: string;
  error_id: string;
  exception: string;
}

/** A row that stands for one that raised: any list of the API may hold it in a row's place, with the row's id and what was still known of it (a label, a kind). The page's reads take it out of the list and show it as "Couldn't read this <thing>" (the page's ``lib/unreadable.ts``), so the list's own type stays its rows'. */
export interface Unreadable {
  id: unknown;
  unreadable: UnreadableMark;
}

/** What a request that failed answers (status 500, ``App.error_answer``). */
export interface ErrorAnswer {
  error: string;
  error_id: string;
  exception: string;
  version: string;
  report: string;
}

/** One error kept by its id (``rowsafe.note``): Kranto's frames only, no values. */
export interface ErrorRecord {
  id: string;
  at: string;
  kind: string;
  where: string;
  exception: string;
  frames: string[];
  version: string;
  message?: string;
  signature?: string;
}

/** ``/api/errors/{id}``: what Send this error files, and GitHub's prefilled page for it. */
export interface ErrorReport {
  id: string;
  title: string;
  body: string;
  url: string;
  record: ErrorRecord;
}

export interface Errors {
  errors: ErrorRecord[];
}

/** The owner's grades on cards and evidence over the window (cleared ones apart). */
export interface GradesCounts {
  grades: number;
  cards: number;
  evidence: number;
  cleared: number;
}

export interface GradesMoved {
  id: number;
  title: string;
  taste: number;
  line: string;
  position: number | null;
}

/** ``moved``: shown cards whose taste is not 0 and that the owner did not grade; ``still``: the rest of the ungraded ones, where they would be anyway; ``top``: the five that moved most. */
export interface GradesIdeas {
  shown: number;
  moved: number;
  graded: number;
  still: number;
  top: GradesMoved[];
}

/** A theme of the latest map with a taste: ``skip`` when the next ideas run leaves it out. */
export interface GradesTheme {
  lineage_id: string;
  name: string;
  taste: number;
  skip: boolean;
  line: string;
  parts: IdeaRankPart[];
}

export interface GradesClosest {
  id: number;
  label: string;
  down: number;
  up: number;
}

export interface GradesKept {
  id: number;
  label: string;
  at: string;
  down: number;
  up: number;
}

/** The sources the rule recommends removing, the closest one otherwise, the kept ones. */
export interface GradesSources {
  window_days: number;
  remove_after: number;
  recommended: SourceToRemove[];
  closest: GradesClosest | null;
  kept: GradesKept[];
}

/** ``/api/grades/summary`` (``taste.summary``): what the owner's grades did (Your grades). */
export interface GradesSummary {
  window_days: number;
  counts: GradesCounts;
  ideas: GradesIdeas;
  themes: GradesTheme[];
  sources: GradesSources;
}

/** The home's visit marker (``home.visit``; ``POST /api/home/visit`` answers it). */
export interface HomeVisit {
  at: string;
  previous: string | null;
}

export interface HomeWaiting {
  drafts?: number;
  prepared?: number;
  error?: string;
  error_id?: string;
}

export interface HomeBriefItem {
  n: number;
  title: string;
  source: string | null;
}

export interface HomeTopicRef {
  id: number;
  name: string;
}

export interface HomeBrief {
  topic: HomeTopicRef;
  brief: number;
  at: string;
  items: HomeBriefItem[];
  more: number;
}

/** The topic of the newest good brief of any day (the console's first starter). */
export interface HomeNewest {
  id: number;
  name: string;
  at: string;
}

/** Today's brief, or ``error`` (and ``error_id``) when it could not be read. */
export interface HomeBriefs {
  topics?: HomeBrief[];
  more?: number;
  newest?: HomeNewest | null;
  error?: string;
  error_id?: string;
}

export interface HomeCard {
  id: number;
  title: string;
  at: string;
  grade: string | null;
}

/** The five newest cards in Ideas' order; ``new`` since ``since`` (null: the last 24 h). */
export interface HomeIdeas {
  rows?: HomeCard[];
  new?: number;
  since?: string | null;
  total?: number;
  error?: string;
  error_id?: string;
}

export interface HomeNext {
  kind: string;
  words: string;
  at: string;
}

/** The home's quiet line; ``reading``: a read runs now (absent from an older server). */
export interface HomeQuiet {
  topics?: number;
  sources?: number;
  read_at?: string | null;
  reading?: boolean;
  next?: HomeNext | null;
  error?: string;
  error_id?: string;
}

/** A card (``id``) or a brief's lead item (``brief``, ``n``, ``topic``, ``source``). */
export interface HomeAwayRow {
  kind: "card" | "brief";
  title: string;
  at: string;
  id?: number;
  grade?: string | null;
  brief?: number;
  n?: number;
  topic?: string;
  source?: string | null;
}

export interface HomeAway {
  since: string;
  days: number;
  rows: HomeAwayRow[];
  ideas: number;
  briefs: number;
  sentence: string;
}

/** The read as it goes, for the first hour's topic: source n of m, and that topic's items kept and read so far in this read. */
export interface HomeFirstRead {
  source_index: number;
  sources: number;
  kept: number;
  judged: number;
  started_at: string | null;
}

/** The first hour (``core.home._first``,): the newest topic that watches a place and has no first brief yet; ``brief_minutes`` the estimate of its first brief (None once enough are kept, or when nothing can be said); ``early_kept`` how many kept items write it. ``error``/``error_id`` when the block could not be read. */
export interface HomeFirst {
  topic?: HomeTopicRef;
  rows?: TopicStartRow[];
  quiet?: string | null;
  read?: HomeFirstRead | null;
  news_on?: boolean;
  no_key?: boolean;
  brief_minutes?: number | null;
  early_kept?: number;
  error?: string;
  error_id?: string;
}

/** ``/api/home`` (``core.home``): the home in one read. ``slots``, ``widgets``, ``library`` and ``rows`` are the widgets' and the cubs' rows, kept for one wave (``features/home.ts`` types them). ``first``: the first hour, None once the newest topic has its first brief. */
export interface HomeToday {
  date: string;
  now: string;
  sentence: string | null;
  waiting: HomeWaiting;
  briefs: HomeBriefs;
  ideas: HomeIdeas;
  quiet: HomeQuiet;
  first: HomeFirst | null;
  visit: HomeVisit | null;
  away_days: number;
  away: HomeAway | null;
  slots: Record<string, unknown>;
  budget_s: number;
  rows?: Record<string, unknown>;
  widgets?: unknown[];
  custom?: boolean;
  library?: unknown[];
  default?: string[];
}

/** An account a draft may go through (``web/post_api.py``): ``state`` is ``connected``, ``needs_login`` or ``not set``; ``platform`` the newsletter platform's name once one is chosen. */
export interface PostAccount {
  key: "newsletter" | "mastodon" | "blog";
  word: string;
  state: string;
  account: string | null;
  platform: string | null;
}

/** One site of a write's short posts: its newest draft, the site, its name and where the draft stands (``waiting``, ``sent``, ``earlier``). */
export interface PostSibling {
  id: number;
  site: string;
  word: string;
  state: string;
}

/** Post's one line about where short posts go, and how many sites are ticked. */
export interface PostSitesLine {
  line: string;
  ticked: number;
}

/** One draft's row on Post: ``kind`` the account it goes through (``newsletter``, ``mastodon``, ``blog``, else the service's name), ``word`` its kind in a word; ``ticket`` the open ask to Send, ``again`` the ask a press offers again; ``line`` where it stands and ``verb`` the ask's button (``core.asks.row``); ``said`` what happened in words; ``note`` and ``link`` the platform's own words and link once sent; ``account``: its account is connected. */
export interface PostDraft {
  id: number;
  ref: string;
  cub: string;
  kind: string;
  word: string;
  title: string;
  fact: string;
  at: string;
  ticket: number | null;
  again: number | null;
  verb: string | null;
  line: string | null;
  said: string | null;
  note: string | null;
  link: string | null;
  account: boolean;
  site?: string;
  site_word?: string;
  write?: string | null;
  way?: "open" | "direct";
  sites?: PostSibling[];
}

export interface PostFailed {
  about: string;
  as: string;
  error: string;
  at: string;
  title: string | null;
  fix: string | null;
}

/** ``GET /api/post``: the drafts waiting (a draft's ask has no time limit), sent and earlier, newest first, the three accounts, and the writes that failed in the last week and were not dismissed (``failed``). */
export interface Post {
  line: string;
  drafts: PostDraft[];
  sent: PostDraft[];
  earlier: PostDraft[];
  accounts: PostAccount[];
  sites: PostSitesLine;
  failed: PostFailed[];
}

/** One part of a short post or a thread: its words. */
export interface PostPart {
  text: string;
}

/** The words the editor opens with: ``title`` (None for a short post) and ``body`` (a long post, markdown) or ``parts`` (a short post). */
export interface PostEdit {
  title: string | null;
  body?: string;
  parts?: PostPart[];
}

/** The most a part may hold, and in what unit. */
export interface PostLimit {
  max: number;
  unit: string;
}

/** One post of a short post's draft, with its length counted the site's way. */
export interface PostCounted {
  text: string;
  used: number;
}

/** What else goes with a short post's words, in a line: the link, the card, what Kranto took off. ``drop``: the person may remove it. */
export interface PostExtra {
  key: string;
  words: string;
  drop: boolean;
}

/** Post directly, when the person switched the site to it: the button's words, whether the account is connected, and why not. */
export interface PostDirect {
  word: string;
  ready: boolean;
  why: string | null;
}

/** ``GET /api/post/d/{id}``: a draft's row with its group, its words as markdown (what Copy and Download give), the file name Download uses, its length and its account. */
export interface PostSheet {
  id: number;
  ref: string;
  cub: string;
  kind: string;
  word: string;
  title: string;
  fact: string;
  at: string;
  ticket: number | null;
  again: number | null;
  verb: string | null;
  line: string | null;
  said: string | null;
  note: string | null;
  link: string | null;
  account: boolean;
  site?: string;
  site_word?: string;
  write?: string | null;
  way?: "open" | "direct";
  sites?: PostSibling[];
  group: "waiting" | "sent" | "earlier";
  markdown: string;
  filename: string;
  words: number;
  account_of: PostAccount | null;
  edit: PostEdit;
  can_edit: boolean;
  cannot_edit: string | null;
  limit: PostLimit | null;
  edited: boolean;
  edited_from: number | null;
  original_draft: number;
  parts?: PostCounted[];
  extras?: PostExtra[];
  siblings?: PostSibling[];
  open?: string | null;
  open_off?: string | null;
  tier?: "open" | "send";
  direct?: PostDirect | null;
  posted_by_you?: boolean;
}

/** One site on Settings › Posting: the ways it can go (``open``, ``direct``), the person's choices, the posting account when Kranto can post there, and its limit. */
export interface PostingSite {
  id: string;
  name: string;
  ways: string[];
  ticked: boolean;
  direct: boolean;
  can_direct: boolean;
  account: string | null;
  account_state: string;
  connection: string | null;
  needs: string | null;
  instance: string | null;
  limit: number;
  unit: string;
  disclose: boolean;
}

/** A site Kranto does not offer, with why, and what would make it possible. */
export interface PostingGone {
  id: string;
  name: string;
  why: string | null;
  later: string | null;
}

/** The person's own site (Sanity), step one of Write a post. */
export interface PostingBlog {
  state: string;
  account: string | null;
  post_url: string | null;
}

/** ``GET /api/post/sites`` (Settings › Posting): every site Kranto offers with the person's choices, the ones it does not offer, the disclosure line, and the blog. */
export interface Posting {
  sites: PostingSite[];
  not_offered: PostingGone[];
  disclosure: string;
  blog: PostingBlog;
}

/** ``POST /api/post/d/{id}/edit``: the new draft, its ask, whether a waiting send was withdrawn, and what the page says. */
export interface PostEdited {
  ok: boolean;
  id: number;
  ref: string;
  ticket: number;
  withdrew: boolean;
  say: string;
}

/** What each path the page reads answers. */
export interface Routes {
  "/api/home": HomeToday;
  "/api/post": Post;
  "/api/post/d/{id}": PostSheet;
  "/api/post/sites": Posting;
  "/api/status": Status;
  "/api/topics": Topics;
  "/api/sources": Sources;
  "/api/today": Today;
  "/api/health": Health;
  "/api/observations": Observations;
  "/api/observations/{id}": ObservationPage;
  "/api/feedback": FeedbackGrades;
  "/api/rollups": Rollups;
  "/api/map": Map;
  "/api/clusters": Clusters;
  "/api/archive/themes": ArchiveThemes;
  "/api/topics/{id}": TopicPage;
  "/api/topics/{id}/scout": Scout;
  "/api/topics/{id}/start": TopicStart;
  "/api/topics/{id}/sources": TopicSourcesChange;
  "/api/topics/{id}/status": TopicStatusChange;
  "/api/sources/from-text": FromText;
  "/api/sources/from-text/{id}": FromText;
  "/api/sources/approve": SourcesApproved;
  "/api/sources/{id}": SourcePage;
  "/api/sources/preview": SourcePreview;
  "/api/catalog": Catalog;
  "/api/connections": Connections;
  "/api/newsletter": Newsletter;
  "/api/setup": Setup;
  "/api/setup/provider": ProviderSetup;
  "/api/ideas": Ideas;
  "/api/ideas/{id}/later": IdeaLater;
  "/api/feedback/vocabulary": FeedbackVocabulary;
  "/api/review/queue": ReviewQueue;
  "/api/grades/summary": GradesSummary;
  "/api/websearch": WebSearchResults;
  "/api/websearch/fetch": WebFetch;
  "/api/setup/search": SearchSetup;
  "/api/errors": Errors;
  "/api/errors/{id}": ErrorReport;
}
