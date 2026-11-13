"""The shapes of the JSON Kranto UI reads from the server, as TypedDicts.

The one source Kranto UI's TypeScript types for the server are generated from
(``scripts/gen_ts.py`` writes the page's ``ui/web/src/api/afk.gen.ts``), and checked against
the routes' real answers at test time (``tests/test_web_types.py``), so neither side drifts
without a red test.

``HOST_API_VERSION`` is the number the page compares with its own: bump it when a field here
changes meaning or is removed (adding one is not a change). ``/api/status`` answers it as
``host_api``. ``OPEN`` names the types whose answers may carry keys not written here (rows
whose keys come from a table, a config or a run's summary); every key written here must still
be there with its type. ``RETURNS`` maps the paths the page reads to what they answer
(``{id}`` stands for an id; the source preview is a POST that writes nothing).

Standard library only; nothing here runs on a request. (No ``from __future__ import
annotations``: TypedDict reads ``NotRequired`` only from evaluated annotations.)
"""
from typing import Any, Literal, NotRequired, TypedDict

# 2 (CUT): /api/ideas lost ``intake`` and ``default_output_kind`` and ``output_kind`` may be
# null; a prepared item says ``available`` (a verb that left Kranto: Dismiss only); the build
# loop's b.* verbs and token actions are gone
HOST_API_VERSION = 2

# "in" is a Python keyword: the shape is written in TypedDict's call form
Tokens = TypedDict("Tokens", {"in": int, "out": int})


class Grade(TypedDict):
    """The latest grade on a target (``grades.latest``): from the ``grades`` table or the
    app's ``feedback``."""
    id: int
    target: str
    target_id: str
    grade: str
    note: str | None
    context: str
    created_at: str
    table: Literal["grades", "feedback"]
    reasons: NotRequired[Any]
    origin: NotRequired[str | None]


class GradeBrief(TypedDict):
    grade: str
    created_at: str


class Message(TypedDict):
    """A message (strike, heartbeat or alarm), as on the Health page and in the feed."""
    id: int
    kind: Literal["strike", "heartbeat", "alarm"]
    dedup_key: str
    origin: str
    title: str
    body: str
    links: list[str]
    evidence_ids: list[int]
    created_at: str
    grade: NotRequired[GradeBrief | None]


class ObservationPublic(TypedDict):
    """An observation's own fields as the JSON API shows them (``app._public``)."""
    id: int
    kind: str
    title: str | None
    summary: str
    why_it_matters: str
    content_quality: float
    durability: float
    opportunity: float
    signal: float
    override: bool
    override_reason: str | None
    tags: list[str]
    source_url: str | None
    source_excerpt: str | None
    item_published_at: str | None
    source_id: int | None
    source_label: str | None
    admitted_by: str | None
    created_at: str
    llm_call_id: int | None
    prompt_version: str | None


class Observation(ObservationPublic):
    """An observation as the JSON API shows it (``app._public``); ``new`` and ``grade`` on
    the library's rows, ``score`` and ``weak`` on a search's."""
    grade: GradeBrief | None
    new: NotRequired[bool]
    score: NotRequired[float]
    weak: NotRequired[bool]


class ObservationBrief(TypedDict):
    """An observation as a list row (``kranto_api._brief``)."""
    id: int
    title: str | None
    summary: str
    signal: float
    kind: str
    source_label: str | None
    created_at: str


class Synthesis(TypedDict):
    text: str
    input_ids: list[int]


class Rollup(TypedDict):
    """What compaction kept of expired observations (``app._rollup``); ``score`` on a
    search's."""
    id: int
    period_start: str
    period_end: str
    first_at: str
    last_at: str
    size: int
    source_mix: dict[str, int]
    platform_mix: dict[str, int]
    topic_mix: dict[str, int]
    mean_signal: float
    kind_counts: dict[str, int]
    keywords: list[str]
    name: str | None
    summary: str | None
    summary_call_id: int | None
    urls: list[str]
    embedding_model: str
    replaced_count: int
    replaced_fingerprint: str
    run_uuid: str | None
    created_at: str
    label: str
    score: NotRequired[float]


# -- /api/status: the header ------------------------------------------------------------------


class StatusTopic(TypedDict):
    id: int
    name: str
    description: str
    kind: str
    ref: str | None


class StatusSource(TypedDict):
    id: int
    kind: str
    label: str
    status: str | None
    params: dict[str, Any]


class StatusRun(TypedDict):
    run_uuid: str
    kind: str
    status: str
    started_at: str
    finished_at: str
    error: str | None


class UpdateBroke(TypedDict):
    """How many pages the new version could not answer on this install's data, and the first
    one's error id (Send this error)."""
    pages: int
    error_id: str | None


class UpdateSummary(TypedDict):
    """The header's update pill (``update.check.summary``)."""
    available: str | None
    installed: str | None
    channel: str | None         # the installed build's line: stable or nightly (main, dev)
    chosen: NotRequired[str]    # the channel in Settings (REL); absent from a server before it
    state: str
    detail: str | None
    reason: str | None
    to: str | None
    notes: list[str]
    notes_url: str | None
    can_apply: bool
    checked_at: str | None
    check_failing: str | None    # the check's error once it has failed for more than two days
    failing_since: str | None
    # the post-update self-check that rolled it back (RCA D1); absent from a server before it
    broke: NotRequired[UpdateBroke | None]


class Hold(TypedDict):
    reason: str
    since: str
    stopped: list[Any]


class IngestProgress(TypedDict):
    """How far a running ingest is (``tick.Progress``): source ``source_index`` of
    ``sources``, its ``item`` of ``items`` (None until fetched), the run's ``done_items`` and
    ``kept`` so far."""
    run_uuid: str
    started_at: str
    sources: int
    source_index: int
    source: str | None
    items: int | None
    item: int
    done_items: int
    kept: int


class PreviewStatus(TypedDict):
    """``/api/status``'s ``preview`` (``kranto.preview.status``): the status bar's sentence,
    when the copy was taken, and the branch commits it was built from (None when unknown)."""
    line: str
    copied_at: str | None
    commits: dict[str, str] | None


class Status(TypedDict):
    """``/api/status``: what the header and the shell read; ``host_api`` is this module's
    ``HOST_API_VERSION``."""
    version: str
    host_api: int
    observations: int
    rollups: int
    spend_this_month_usd: float
    budget_usd: float | None           # None: no monthly cap
    tokens_today: Tokens | None
    paused: str | None
    preview: PreviewStatus | None      # None on every install but the preview
    topics: list[StatusTopic]
    sources: list[StatusSource]
    runs: list[StatusRun]
    scheduler: bool
    running: str | None
    ingest_progress: IngestProgress | None
    next_run: dict[str, str | None]
    lanes: dict[str, dict[str, Any]]
    update: UpdateSummary
    hold: Hold | None
    builds: bool                       # builds.enabled (and brb): the Build door, projects, repos
    browser: bool                      # browser.enabled: Settings › Browser, Read in your browser
    cubs_developer: bool               # cubs.developer: the cub shop (Available, Made by Kranto)


# -- /api/topics ----------------------------------------------------------------------------


class Topic(TypedDict):
    """One topic with its facts (``topics_api._facts``)."""
    id: int
    name: str
    description: str
    kind: str
    ref: str | None
    status: Literal["active", "paused", "archived"]
    created_at: str
    sources: int
    proposed: int
    items_per_day: float
    kept_per_day: float
    observations: int
    themes: int
    rising: int
    spend_month_usd: float
    tokens_month: Tokens | None


class BroadSource(TypedDict):
    """A watched source with no topic: the broad lane."""
    id: int
    label: str
    kind: str
    items_per_day: float
    kept_per_day: float
    wildcard: bool


class TopicsAll(TypedDict):
    observations: int
    sources: int
    themes: int
    items_per_day: float
    map: str | None


class Topics(TypedDict):
    """``/api/topics?kind=``: ``topics`` active and paused, ``archived`` the owner's archived
    ones."""
    topics: list[Topic]
    archived: list[Topic]
    broad: list[BroadSource]
    all: TopicsAll
    progress: str
    every_hours: float
    theme_min_share: float


# -- /api/sources ----------------------------------------------------------------------------


class TopicRef(TypedDict):
    id: int
    name: str


class SourceLink(TopicRef):
    """A topic a source feeds (``topic_links``), with its kind: user (yours) or project."""
    kind: str


# What the test fetch found (only the keys it set); for a source described in a pasted list,
# the line it came from (``from``, a Python keyword: the call form) and its batch.
SourceValidation = TypedDict("SourceValidation", {
    "status": NotRequired[str], "items": NotRequired[int], "recent": NotRequired[int],
    "median_similarity": NotRequired[float], "error": NotRequired[str],
    "discovered_from": NotRequired[str], "checked": NotRequired[str],
    "from": NotRequired[str], "batch": NotRequired[str],
    # the stored record's other keys (kranto.stored.sources.Validation.api), when set
    "latest": NotRequired[str], "topic_id": NotRequired[int], "role": NotRequired[str],
    "preset": NotRequired[str], "why": NotRequired[str], "replaces": NotRequired[str]})


class Mute(TypedDict):
    muted_until: str | None
    read_less: bool
    since: str


class SourceGrades(TypedDict):
    """The owner's latest grade of each of a source's observations, trailing 90 days
    (``source_health.source_grades``), and the why chips given."""
    useful: int
    not_useful: int
    wrong: int
    missed: int
    reasons: dict[str, int]


class SourceSpend(TypedDict):
    """A paid API's reads for one source (X, ``spend.by_source``): this month's estimate at
    list price and how many resources, and what one fetch reads at most."""
    usd: float
    reads: int
    run_usd: float


class SourceKept(TypedDict):
    """The owner's latest Keep of a source Kranto recommended removing (``source_rule.keeps``)."""
    at: str
    row: int
    down: int
    up: int
    window_days: int


class SourceRemoval(TypedDict):
    """The source rule's state (``source_rule.state``,): ``recommend`` when its
    downvoted posts since the window's start (or the latest Keep) call for removal."""
    recommend: bool
    down: int
    up: int
    window_days: int
    kept: SourceKept | None


class Source(TypedDict):
    """A source as Settings › Sources lists it (``source_health.list_sources``)."""
    id: int
    kind: str
    label: str
    origin: Literal["manual", "scout", "import"]
    review: str | None
    group: str
    status: str
    detail: str
    site: str
    site_name: str
    preset: str | None
    fields: dict[str, Any] | None
    topics: list[SourceLink]
    proposed_for: str | None
    # the topic the scout proposed it for, else the first it was added to (SRC)
    found_for: SourceLink | None
    why: str | None
    replaces: Any
    validation: SourceValidation
    items_7d: int
    items_per_day: float | None
    kept_30d: int
    judged_30d: int
    kept_rate: float | None
    yield_per_day: float
    mute: Mute | None
    grades: SourceGrades | None
    removal: SourceRemoval | None
    last_fetch: str | None
    last_error: str | None
    retry_at: str | None
    failing_runs: int
    backoff_until: str | None
    needs_fixing: bool
    connection: str | None
    retention_days: float | None
    note: str | None
    spend: SourceSpend | None


class SourceTopic(TypedDict):
    """An active topic a source can be added to, with its watched sources."""
    id: int
    name: str
    description: str
    kind: str
    ref: str | None
    sources: int


class RedditNote(TypedDict):
    watched: int
    note: str


class Sources(TypedDict):
    """``/api/sources``."""
    sources: list[Source]
    topics: list[SourceTopic]
    reddit: RedditNote
    connections_need_you: int
    every_hours: float
    default_retention_days: float


class SourceFetch(TypedDict):
    """One fetch of a source, in a run or by Fetch now (a ``source_fetches`` row)."""
    id: int
    source_id: int
    run_uuid: str | None
    trigger: Literal["run", "manual"]
    state: Literal["ok", "paced", "failing", "needs_login"]
    fetched: int
    new: int
    error: str | None
    created_at: str
    retry_at: str | None


class SourceHow(TypedDict):
    """How a source is read (``source_health.describe``)."""
    request: str | None
    pacing: str
    terms: str


class SourceTopicFacts(SourceLink):
    """A topic a source feeds, on the source's page: the topic's watched sources and
    the items they kept this month."""
    status: str
    sources: int
    kept_month: int


class SourceModelSpend(TypedDict):
    """This month's model calls on a source's items (``source_health.model_spend``)."""
    usd: float
    tokens: Tokens | None


class SourcePage(Source):
    """``/api/sources/<id>``: the source's row, its last seven fetches and how it is read
    (``source_health.source_detail``); each topic it feeds with that topic's counts, what it
    kept this month and what judging its items cost. Not found: 404 with ``error``."""
    params: dict[str, Any]
    fetches: list[SourceFetch]
    how: SourceHow
    added_at: str
    retention_override: bool
    retention_kind_days: float
    topic_facts: list[SourceTopicFacts]
    kept_month: int
    spend_month: SourceModelSpend
    every_hours: float


class PresetField(TypedDict):
    key: str
    label: str
    placeholder: str
    hint: str


class Preset(TypedDict):
    """A kind of source in the catalog (``catalog.Preset.to_json``)."""
    key: str
    provider: str
    provider_name: str
    name: str
    blurb: str
    access: Literal["public", "login", "not_offered"]
    needs: str | None
    available: bool
    reason: str | None
    retention_days: float | None
    fields: list[PresetField]


class CatalogProvider(TypedDict):
    key: str
    name: str
    presets: list[Preset]


class ConnectedAccount(TypedDict):
    """An account connected for a provider, as the catalog lists it."""
    instance: str
    account: str
    state: Literal["connected", "needs_login"]


class Catalog(TypedDict):
    """``/api/catalog``: the presets by provider, the topics a source can be added to, the
    accounts connected per provider, the prefilter line."""
    providers: list[CatalogProvider]
    topics: list[SourceTopic]
    connected: dict[str, list[ConnectedAccount]]
    prefilter: float


class PreviewItem(TypedDict):
    title: str
    url: str | None
    link: str | None
    published_at: str | None


class SourcePreview(TypedDict):
    """``POST /api/sources/preview`` ({preset, fields, topic}): one fetch, nothing saved. A
    fetch that fails: 422 with ``error`` and ``state``."""
    preset: str
    kind: str
    params: dict[str, Any]
    label: str
    existing_id: int | None
    prefilter: float
    retention_days: float | None
    items: int
    recent: int
    median_similarity: float | None
    newest: list[PreviewItem]


# -- /api/connections -------------------------------------------------------------------------


class AccountSource(TypedDict):
    id: int
    label: str


class ConnectionTest(TypedDict):
    note: str | None
    created_at: str


class ConnectionAccount(TypedDict):
    """A live connected account (``Connections.accounts``): never a secret."""
    id: int
    provider: str
    provider_name: str
    instance: str
    account: str
    scopes: list[str]
    state: Literal["connected", "needs_login"]
    note: str | None
    connected_at: str
    state_at: str
    last_used_at: str | None
    last_test: ConnectionTest | None
    sources: list[AccountSource]
    writes: NotRequired[bool]     # a credential that sends (a cub's broker), not read-only


class ProviderField(TypedDict):
    """What is pasted for a provider; a ``secret`` one is never echoed back."""
    key: str
    label: str
    placeholder: NotRequired[str]
    secret: NotRequired[bool]


class ConnectionProvider(TypedDict):
    """A provider as the Connections page lists it (``PROVIDER_INFO``, with ``client_set``
    on a client provider, YouTube and X, and ``device`` on GitHub); one not offered has only
    its ``reason``. A client provider names its first part (``client_section``), what that
    part says until the client is saved (``client_ready``) and after Remove
    (``client_removed``); ``cost`` is what reading with it costs, for a paid API."""
    key: str
    name: str
    state: Literal["available", "not_offered"]
    flow: NotRequired[Literal["browser", "paste", "both", "client"]]
    blurb: NotRequired[str]
    redirect_host: NotRequired[str]
    scopes: NotRequired[list[str]]
    reads: NotRequired[str]
    never: NotRequired[str]
    revoke_at: NotRequired[str]
    expiry: NotRequired[str]
    steps: NotRequired[list[str]]
    alt_steps: NotRequired[list[str]]
    device_steps: NotRequired[list[str]]
    fields: NotRequired[list[ProviderField]]
    sources: NotRequired[list[str]]
    reason: NotRequired[str]
    client_set: NotRequired[bool]
    client_section: NotRequired[str]
    client_ready: NotRequired[str]
    client_removed: NotRequired[str]
    cost: NotRequired[str]
    device: NotRequired[bool]
    writes: NotRequired[bool]     # a newsletter platform, Mastodon (posting): cubs that send
    group: NotRequired[Literal["newsletter"]]   # offered under Accounts › Newsletter instead


class Connections(TypedDict):
    """``/api/connections``: the accounts, the providers, why connections are off (None: they
    are on), how tokens are kept, and each browser sign-in's callback path."""
    accounts: list[ConnectionAccount]
    providers: list[ConnectionProvider]
    unavailable: str | None
    storage: dict[str, str]
    callback: dict[str, str]


# -- /api/newsletter -------------------------------------------------------------------------


class NewsletterPlatform(TypedDict):
    """A newsletter platform as the Connect dialog offers it (``newsletter.Platform.words``)."""
    id: str
    name: str
    about: str
    docs: str
    can_schedule: bool


class NewsletterConnection(TypedDict):
    id: int
    account: str
    state: str


class Newsletter(TypedDict):
    """``/api/newsletter``: the platform in use (``None`` until one is connected; the words
    then say ``unnamed``), the ones offered, its connection, the from address and audience in
    words, whether an issue can go out now and what is missing. ``POST
    /api/newsletter/check`` answers the same with ``ok``, ``said`` and ``message``."""
    platform: NewsletterPlatform | None
    name: str | None
    unnamed: str
    platforms: list[NewsletterPlatform]
    connection: NewsletterConnection | None
    from_address: str | None
    audience: str | None
    audiences: bool               # the platform in use has audiences Kranto can make (a press)
    ready: bool
    missing: list[str]


# -- /api/setup ------------------------------------------------------------------------------


class KeyTest(TypedDict):
    """The endpoint's last answer to a key tried here (``setup.record_key_test``)."""
    ok: bool
    detail: str
    base_url: str
    at: str


class SetupKey(TypedDict):
    """Whether the watcher's provider has its key (never the key), the variable it is kept
    under, the endpoint (``openai_compat``), which provider, its last test. ``choice``,
    ``label`` and ``endpoint``: what the metered client uses (``providers.in_use``)."""
    set: bool
    env: str
    base_url: str
    provider: str
    choice: str
    label: str
    endpoint: str | None
    test: KeyTest | None


class ProviderKey(TypedDict):
    """A key provider found or not (``providers.detect``); never the key."""
    key_set: bool
    env: str
    label: str


class ProviderEndpoint(ProviderKey):
    base_url: str | None


class ProviderClaudeCode(TypedDict):
    """Claude Code on this machine, from ``claude --version`` and ``claude auth status``;
    ``offered``: whether it can be chosen as the watcher's model; ``terms``: the sentence shown
    wherever it is chosen (an explicit choice, never the default)."""
    installed: bool
    version: str | None
    logged_in: bool
    auth_method: str | None
    subscription: str | None
    token_in_service: bool
    offered: bool
    label: str
    terms: str


class ProviderCurrent(TypedDict):
    """What the metered client sends with (``providers.in_use``): ``provider`` as the ledger
    records it, ``choice`` as offered (an endpoint at openrouter.ai is ``openrouter``),
    ``endpoint`` the URL its calls go to (None: Claude Code's login)."""
    provider: str
    choice: str
    label: str
    endpoint: str | None
    key_env: str | None
    models: dict[str, str]
    tiers: dict[str, str]
    key_set: bool


class ProviderSetup(TypedDict):
    """``/api/setup/provider``: what can serve the watcher's models, offered in ``choices``
    order (``providers.detect``)."""
    current: ProviderCurrent | None
    choices: list[str]
    anthropic: ProviderKey
    openrouter: ProviderKey
    openai_compat: ProviderEndpoint
    claude_code: ProviderClaudeCode


class Login(TypedDict):
    """One of the two logins builds need; ``command`` is what to run when it is missing;
    ``installed`` (Claude Code's only: Welcome's Ready tells not installed from not signed in)."""
    ok: bool
    detail: str
    command: str
    installed: NotRequired[bool]


class SetupLogins(TypedDict):
    claude: Login
    gh: Login


class BuildChoice(TypedDict):
    mode: Literal["auto", "manual"] | None
    concurrency: int


class Setup(TypedDict):
    """``/api/setup``: whether setup is done, the key, the two logins, what builds may do;
    ``budget_usd`` None: no monthly cap."""
    done: bool
    done_at: str | None
    needs_setup: bool
    key: SetupKey
    logins: SetupLogins
    builds_ok: bool
    build: BuildChoice
    topics: int
    sources: int
    scheduler: bool
    budget_usd: float | None
    # Welcome's Ready line: the cost on your own key, and the cap or none; on the
    # Claude Code login the plan's usage (fix 9)
    cost: str
    first_brief_minutes: int           # Ready's "The first brief: in about 5 minutes"
    every_hours: float
    brb: bool
    builds: bool                       # builds.enabled: Welcome's Building and Publishing steps


# -- /api/today ------------------------------------------------------------------------------


class TodayTopic(TypedDict):
    """A topic's part of Today: kept since the marker, its best three, proposed sources."""
    id: int
    name: str
    status: Literal["active", "paused"]
    kind: str
    ref: str | None
    new_kept: int
    top: list[Observation]
    proposed: int
    proposed_ticked: list[int]
    proposed_items_per_day: float


class Movement(TypedDict):
    """A cluster's change since the previous map (``map.read.movement``)."""
    since: str
    delta: float
    excess: float | None
    points: int
    new_total: int | None
    new_in_cluster: int | None
    expected_new: float | None
    burst: int | None
    entered_burst: bool
    p_value: float | None
    q_value: float | None


class TrajectoryPoint(TypedDict):
    """One map's measures of a lineage; older maps lack the later keys."""
    at: str
    share: float
    size: int
    stories: NotRequired[int | None]
    expected_share: NotRequired[float | None]
    new_total: NotRequired[int | None]
    new_in_cluster: NotRequired[int | None]
    new_max_origin_share: NotRequired[float | None]
    expected_new: NotRequired[float | None]
    burst: NotRequired[int | None]
    p_value: NotRequired[float | None]
    q_value: NotRequired[float | None]


class RisingTheme(TypedDict):
    """A rising theme on Today, with the topic most of its stories come from."""
    cluster: int
    lineage_id: str
    label: str
    name: str | None
    size: int
    stories: int | None
    keywords: list[str]
    cross_source: bool
    rising: bool
    movement: Movement | None
    trajectory: list[TrajectoryPoint]
    source_mix: dict[str, int]
    topic: TopicRef
    topic_share: float


class TopicName(TypedDict):
    id: int
    name: str


class SourceToRemove(TypedDict):
    """A source Kranto recommends removing (``source_rule.to_remove``): a Needs you row."""
    id: int
    label: str
    kind: str
    down: int
    up: int
    window_days: int
    topics: list[TopicName]
    items_per_day: float


class FailingSource(TypedDict):
    """A watched source failing run after run (``source_health.needs_fixing``)."""
    id: int
    label: str
    kind: str
    failing_runs: int
    backoff_until: str | None
    error: str | None


class IngestLast(TypedDict):
    status: str
    finished_at: str
    contributed: int | None
    error: str | None


class WatchPause(TypedDict):
    """A provider's pause (a spend limit at the provider, a plan's usage window): watching
    resumes by itself at ``until``."""
    until: str
    reason: str
    provider: str


class HealthWord(TypedDict):
    """Kranto's health word and why (``health.health``,): the status bar's word in every
    layout, and the console's answer to "why is Kranto degraded?". ``reason``: one line in plain
    words, None when Healthy; ``trace``: the run it is about (``#/afk/<run>/trace``). "Not set up
    yet" (grey): no source is watched and nothing was read, a new home, not a broken one.
    "Reading for the first time" (grey): sources are watched and no read has ended yet."""
    word: Literal["Healthy", "Degraded", "Paused", "Not set up yet",
                  "Reading for the first time"]
    tone: Literal["green", "amber", "grey"]
    reason: str | None
    at: str | None
    run: str | None
    trace: str | None


class IngestLine(TypedDict):
    last: IngestLast | None
    judge_calls_24h: int
    judge_errors_24h: int
    observations: int
    sources: int
    topics: int
    paused: str | None
    watch_paused: WatchPause | None
    health: HealthWord


class Today(TypedDict):
    """``/api/today?since=``: the inbox; ``topics`` are the user's, ``project_topics``
    the page's."""
    since: str
    seen_at: str | None
    now: str
    default_window_hours: int
    topics: list[TodayTopic]
    project_topics: list[TodayTopic]
    new_kept: int
    proposed: int
    rising: list[RisingTheme]
    messages: list[Message]
    sources_failing: list[FailingSource]
    sources_to_remove: list[SourceToRemove]
    ingest: IngestLine


# -- /api/health -----------------------------------------------------------------------------


class Overrides(TypedDict):
    rated: int
    set: int
    lifted: int
    refused: int
    rate: float | None


class RunSourceReport(TypedDict):
    """One source's part of an ingest run's summary (``tick.SourceReport``); ``label`` None on
    a summary that did not keep it (``stored.runs.SourceReport``)."""
    label: str | None
    source_id: NotRequired[int]
    fetched: NotRequired[int]
    judged: NotRequired[int]
    contributed: NotRequired[int]
    prefiltered: NotRequired[int]
    fetch_error: NotRequired[str | None]
    fetch_state: NotRequired[str | None]
    retry_at: NotRequired[str | None]
    waiting_until: NotRequired[str | None]
    failing_runs: NotRequired[int]
    not_reached: NotRequired[bool]
    empty_replies: NotRequired[int]
    refused: NotRequired[int]


class RunSummary(TypedDict):
    """A run's summary; its keys depend on the run's kind (ingest, compact, snapshot...)."""
    contributed: NotRequired[int | None]
    tokens: NotRequired[Tokens | None]
    expired: NotRequired[int | None]
    rollups: NotRequired[int]
    overrides: NotRequired[Overrides | None]
    sponsored: NotRequired[int]
    sponsor_links: NotRequired[int]
    sources: NotRequired[list[RunSourceReport]]


class HealthRun(TypedDict):
    run_uuid: str
    kind: str
    status: str
    started_at: str
    finished_at: str
    summary: RunSummary
    error: str | None
    tokens: Tokens | None


class CompactRun(TypedDict):
    run_uuid: str
    kind: str
    status: str
    started_at: str
    finished_at: str
    summary: RunSummary
    error: str | None


class Removed(TypedDict):
    table_name: str
    n: int


class Retention(TypedDict):
    line: str
    last: CompactRun | None
    rollups: int
    replaced: int
    removed: list[Removed]
    last_purge: str | None


class ModelError(TypedDict):
    """Failed model calls over the last week, by purpose and HTTP status (0: none)."""
    purpose: str
    http_status: int
    n: int
    last_at: str
    example: str | None


class Exploration(TypedDict):
    admitted_by: str
    n: int
    mean_signal: float | None
    in_cross_source: int | None


class Decision(TypedDict):
    """A strike gate decision with its candidate (``gate.recent_decisions``). ``promoted``
    is SQLite's 0 or 1."""
    decision_id: int
    promoted: int
    reason: Literal["promoted", "below_threshold", "no_threshold", "warmup", "refractory",
                    "weekly_cap", "stale"]
    threshold: float | None
    detail: str
    message_id: int | None
    decided_at: str
    candidate_id: int
    origin: str
    subject_key: str
    score: float
    title: str
    created_at: str


class Delivery(TypedDict):
    sent: list[str]
    failed: int
    last_error: str | None


class Budget(TypedDict):
    monthly_usd: float | None
    alarm_fraction: float


class StrikeConfig(TypedDict):
    """``strike:`` in the config, whole."""
    max_per_week: int
    min_card_score: float
    min_burst_score: float
    min_watch_score: float
    refractory_days: float
    warmup_snapshots: int
    warmup_days: float


class Memory(TypedDict):
    """Kranto's memory and its caps (``memory.py``): ``level`` ``high`` past 80% of the lowest
    cap, ``uncapped`` with none. ``used_mb`` is the server's group (its builds included), or
    the process alone without one."""
    level: Literal["ok", "high", "uncapped"]
    used_mb: int | None
    rss_mb: int | None
    high_mb: int | None
    max_mb: int | None
    group: str | None
    words: str


class Health(TypedDict):
    """``/api/health``: what Settings › System › Health shows (the server's /health page)."""
    memory: Memory
    month: str
    spent_usd: float
    tokens_month: Tokens | None
    budget: Budget
    alarm: bool
    paused: str | None
    watch_paused: WatchPause | None
    busy: bool
    can_run: bool
    running: str | None
    ingest_progress: IngestProgress | None
    next_run: dict[str, str | None]
    lanes: dict[str, dict[str, Any]]
    api_key: bool
    models: dict[str, str]
    outcomes: dict[str, int]
    exploration: list[Exploration]
    errors: list[ModelError]
    runs: list[HealthRun]
    messages: list[Message]
    deliveries: dict[str, Delivery]
    delivery_status: str
    decisions: list[Decision]
    strike: StrikeConfig
    grade_labels: dict[str, str]
    retention: Retention


# -- the library: /api/observations, /api/rollups ---------------------------------------------


class Compacted(TypedDict):
    n: int
    replaced: int


class Observations(TypedDict):
    """``/api/observations``: without ``q`` filtered and paged (``compacted``, ``progress``);
    with ``q`` a search (``query``; with ``cutoff=1`` also what /library says about it)."""
    total: int
    offset: int
    cluster_label: str | None
    seen_at: str | None
    marker: str
    since: str | None
    new_total: int
    results: list[Observation]
    compacted: NotRequired[Compacted]
    progress: NotRequired[str]
    query: NotRequired[str]
    cutoff: NotRequired[float]
    off_topic_below: NotRequired[float]
    closest: NotRequired[float | None]
    rollups: NotRequired[list[Rollup]]


class Rollups(TypedDict):
    """``/api/rollups``: newest first and paged (``total``, ``offset``), or with ``q`` the
    ``k`` best matches."""
    rollups: int
    replaced: int
    retention_line: str
    results: list[Rollup]
    total: NotRequired[int]
    offset: NotRequired[int]
    query: NotRequired[str]


# -- one observation's page: /api/observations/<id>?k= -------------------------------------


class Similar(TypedDict):
    """One of the ``k`` nearest observations by meaning (``search.similar_to``)."""
    id: int
    score: float
    weak: bool


class Neighbour(ObservationPublic):
    """A nearest observation that is still in the library, with its score."""
    score: float
    weak: bool


class LlmCall(TypedDict):
    """The model call that judged an observation."""
    id: int
    model: str
    prompt_version: str | None
    cost_usd: float | None
    prompt_tokens: int | None
    completion_tokens: int | None
    response: str | None
    created_at: str


class DiveParent(TypedDict):
    """The item an observation was read one step from (``library.parent_of``)."""
    relation: Literal["discussion", "link", "repository"]
    id: int
    title: str | None
    summary: str


class DiveChild(TypedDict):
    """An item read one step from this one (``library.children_of``)."""
    relation: Literal["discussion", "link", "repository"]
    id: int
    title: str | None
    summary: str
    signal: float
    source_url: str | None


class CitedBy(TypedDict):
    """What cites an observation: the cards (newest first) and the News briefs."""
    ideas: list[int]
    briefs: list[int]


class ObservationPage(ObservationPublic):
    """``/api/observations/<id>?k=``: everything /obs/<id> shows. Not found: 404 with
    ``error``."""
    source_kind: str | None
    topic_similarity: float | None
    similar: list[Similar]
    neighbours: list[Neighbour]
    call: LlmCall | None
    synthesis: Synthesis | None
    dive_parent: DiveParent | None
    dive_children: list[DiveChild]
    grade: Grade | None
    grade_choices: list[str]
    grade_labels: dict[str, str]
    cited_by: CitedBy
    # the topics its source feeds: why it is in a topic's evidence
    topics: list[SourceLink]


# -- /api/feedback?target=&ids= --------------------------------------------------------------


class FeedbackGrade(TypedDict):
    """A row's latest grade as the feedback read gives it (cleared grades left out)."""
    value: str
    reasons: list[str]
    created_at: str


class FeedbackGrades(TypedDict):
    """``/api/feedback?target=&ids=``: the latest grade of each id that has one, by id."""
    target: str
    grades: dict[str, FeedbackGrade]


# -- /api/archive/themes: the Parallax archive's themes --------------------------------------


class ArchivePoint(TypedDict):
    """One Parallax snapshot's measures of a theme."""
    at: str
    share: float | None
    size: int


class ArchiveCard(TypedDict):
    id: int
    kind: str | None
    title: str | None
    status: str


class ArchiveDispatch(TypedDict):
    """A Parallax dispatch whose clusters a theme was, with the cards made from it."""
    dispatch_id: str | None
    title: str | None
    date: str | None
    url: str | None
    cards: list[ArchiveCard]


class ArchiveTheme(TypedDict):
    """A lineage of the archive's own clustering (``archive_api.theme_records``)."""
    lineage_id: str
    name: str | None
    named: bool
    names: list[str]
    name_count: int
    keywords: list[str]
    alive: bool
    size: int
    first_at: str
    last_at: str
    epochs: int
    members: int
    trajectory: list[ArchivePoint]
    dispatches: list[ArchiveDispatch]
    bundle: str


class ArchiveThemes(TypedDict):
    """``/api/archive/themes``: every theme, alive first then by size."""
    archive: str
    themes: list[ArchiveTheme]
    count: int


# -- the map: /api/map, /api/clusters --------------------------------------------------------


class StructureNull(TypedDict):
    """The map's clusters against structure-free data (``compute.structure_null``); older
    maps lack the single-blob keys."""
    reps: NotRequired[int]
    null_mean: NotRequired[float]
    null_sd: NotRequired[float]
    real: NotRequired[float]
    z: NotRequired[float | None]
    covariance_null_mean: NotRequired[float]
    covariance_null_sd: NotRequired[float]
    covariance_z: NotRequired[float | None]
    clustered: NotRequired[bool]


class MapStories(TypedDict):
    """How many distinct stories the map's observations tell (copies count once)."""
    observations: int
    distinct: int


class MapQuality(TypedDict):
    """A map's measures (``compute.cluster`` and the snapshot's); older maps lack some."""
    silhouette_umap: NotRequired[float]
    silhouette_native: NotRequired[float]
    structure_null: NotRequired[StructureNull]
    stories: NotRequired[MapStories]


class MapSnapshot(TypedDict):
    id: int
    created_at: str
    n: int
    k: int
    quality: MapQuality


class MapCluster(TypedDict):
    cluster: int
    label: str
    name: str | None
    keywords: list[str]
    size: int
    share: float
    centroid_2d: list[float]
    cross_source: bool
    max_source_share: float


class MapPoints(TypedDict):
    """The map's points as columns: id, x, y, cluster (``c``), signal (``s``), text (``t``)
    and the index of its source in ``sources`` (``src``)."""
    id: list[int]
    x: list[float]
    y: list[float]
    c: list[int]
    s: list[float]
    t: list[str]
    src: list[int]


class Map(TypedDict):
    """``/api/map``: the latest snapshot. Before the first map: 404 with ``MapNotYet``."""
    snapshot: MapSnapshot
    density: list[list[float]]
    clusters: list[MapCluster]
    sources: list[str]
    points: MapPoints


class MapNotYet(TypedDict):
    error: str
    progress: str
    can_run: bool


class ClusterRow(TypedDict):
    """A cluster of the latest map (``map.read.clusters``) with its synthesis and grade, as
    /clusters and a topic's themes share it."""
    snapshot_id: int
    cluster: int
    lineage_id: str
    size: int
    share: float
    stories: int | None
    keywords: list[str]
    name: str | None
    name_call_id: int | None
    label: str
    source_mix: dict[str, int]
    topic_mix: dict[str, int]
    origin_mix: dict[str, int]
    max_source_share: float
    max_origin_share: float | None
    cross_source: bool
    representatives: list[int]
    trajectory: list[TrajectoryPoint]
    movement: Movement | None
    rising: bool
    synthesis: Synthesis | None
    grade: Grade | None


class Cluster(ClusterRow):
    """A cluster of the latest map as /clusters shows it (``map.read.clusters`` with its
    synthesis, grade and three examples)."""
    centroid_2d: list[float]
    examples: list[ObservationBrief]


class ClusterSnapshot(TypedDict):
    id: int
    created_at: str
    n: int
    k: int


class Clusters(TypedDict):
    """``/api/clusters?sort=``; before the first map only ``snapshot`` (None), ``clusters``
    (empty) and ``progress``."""
    snapshot: ClusterSnapshot | None
    clusters: list[Cluster]
    quality: NotRequired[dict[str, Any]]
    sort: NotRequired[str]
    grade_labels: NotRequired[dict[str, str]]
    grade_choices: NotRequired[list[str]]
    progress: NotRequired[str]


# -- one topic's page and its scout: /api/topics/<id>, /api/topics/<id>/scout -----------------


class TopicTheme(ClusterRow):
    """A theme of a topic: a cluster of the latest map whose stories come from the topic's
    sources for at least ``theme_min_share`` of it, with that share."""
    topic_share: float


class SourceRow(Source):
    """A source as ``TopicsAPI.source_rows`` gives it: its row in Settings › Sources, the
    topic it was proposed for, its role (core, wildcard) and whether onboarding's proposal
    list ticks it (``pretick``)."""
    proposed_topic: int | None
    role: str
    pretick: bool


class TopicSource(SourceRow):
    """One of a topic's sources, with the items a day it gave over the last seven days."""
    items_per_day_7d: float


class TopicSnapshot(TypedDict):
    id: int
    created_at: str


class TopicPage(Topic):
    """``/api/topics/<id>``: the topic's facts, its themes, the ones rising now, its sources
    with the scout's proposals (``topics_api.one_topic``); ``budget_usd`` None: no monthly
    cap. Not found: 404 with ``error``."""
    themes_list: list[TopicTheme]
    rising_now: list[TopicTheme]
    snapshot: TopicSnapshot | None
    source_rows: list[TopicSource]
    prefilter: float
    every_hours: float
    budget_usd: float | None
    progress: str
    grade_labels: dict[str, str]
    grade_choices: list[str]
    history: list["TopicChange"]


class TopicStartRow(TypedDict):
    """One of a new topic's four rows (``progress.topic_start``): Sources, First read, First
    brief, First ideas; ``at`` the time it happened or the scheduler's next run, None when
    neither is known; ``brief_id`` on the brief's row once written."""
    key: Literal["sources", "read", "brief", "ideas"]
    title: str
    state: Literal["waiting", "running", "done", "quiet", "off", "failed"]
    words: str
    at: str | None
    brief_id: NotRequired[int]


class TopicStart(TypedDict):
    """``/api/topics/{id}/start``: a new topic's first hour; ``done`` once it has an
    idea card (the page then draws none of it); ``quiet`` the line under the rows."""
    topic_id: int
    done: bool
    rows: list[TopicStartRow]
    quiet: str | None
    observations: int
    needed: int


class TopicChange(TypedDict):
    """One line of a topic's history (``library.topic_history``), newest first: ``what`` edit
    (``changed``: name, description; ``name`` the name it took), link or unlink (a source added
    or removed: ``source_id``, ``source`` its label), status (``status``); ``by`` the door it
    came through (ui, chat, mcp, cli), None on a status change."""
    what: Literal["edit", "link", "unlink", "status"]
    at: str
    by: NotRequired[str]
    note: str | None
    changed: NotRequired[list[str]]
    name: NotRequired[str]
    source_id: NotRequired[int]
    source: NotRequired[str | None]
    status: NotRequired[str]


class TopicWords(TypedDict):
    name: str
    description: str


class TopicRevision(TypedDict):
    id: int
    topic_id: int
    changed: list[str]
    by: str
    created_at: str
    before: TopicWords
    after: TopicWords


class TopicEdit(TypedDict):
    """``POST /api/topics/<id>``: the edit made (``revision``; ``before`` is what Undo sends
    back), or ``changed`` None when the words were the same."""
    id: int
    changed: list[str] | None
    revision: TopicRevision | None


class TopicSourcesChange(TypedDict):
    """``POST /api/topics/<id>/sources``: the sources linked and unlinked, and among them those
    approved (added back) or retired (left with no topic); ``remaining``: by removed source
    id, the topics it still feeds."""
    id: int
    added: list[int]
    removed: list[int]
    retired: list[int]
    approved: list[int]
    remaining: dict[str, list[SourceLink]]


class TopicStatusChange(TypedDict):
    """``POST /api/topics/<id>/status``: ``was`` the status before (what Undo sends back)."""
    id: int
    status: str
    was: str | None
    changed: bool


class ScoutSearch(TypedDict):
    """The scout run's live search (``scout.search_summary``): the chip "from Exa, searched
    2026-10-17", or ``live`` false with the "no live search" sentence in ``note``."""
    live: bool
    backends: list[str]
    searched_at: str | None
    results: int
    note: str | None


class NoFeed(TypedDict):
    label: str
    why: str | None


class ScoutResult(TypedDict):
    """What a finished scout found: the sources it proposed (new or already watched), how
    many failed validation, the sites live search found that have no feed, and the run's live
    search."""
    message: str
    proposals: list[SourceRow]
    invalid: int
    no_feed: NotRequired[list[NoFeed]]
    search: NotRequired[ScoutSearch | None]


class ScoutJob(TypedDict):
    """The scout as a background job (``web/jobs.py``): ``result`` once it is done, ``error``
    when it failed."""
    key: str
    state: Literal["running", "done", "failed"]
    started: float
    finished: float | None
    elapsed_s: float
    result: ScoutResult | None
    error: str | None


class Scout(TypedDict):
    """``/api/topics/<id>/scout``: GET the topic's scout job; POST starts it (202) or answers
    the one running. No job yet: 404 with ``error``."""
    job: ScoutJob


# -- sources described in a pasted text: /api/sources/from-text ------------

FromTextStatus = Literal["valid", "unverified", "invalid", "not_found", "refused",
                         "connect_first", "already_proposed", "already_watching"]


class XCost(TypedDict):
    """An X line's cost at X's list price: what checking it read, one run, and a month at
    the configured cadence."""
    check: float
    run: float
    month: float


# One line of a described batch, in the order the text named them. ``row``: the source's row
# (as a scout proposal's) where the line is a source; None for lines that are not (not found,
# refused, an account to connect first). "from" is a Python keyword: the call form again.
FromTextLine = TypedDict("FromTextLine", {
    "status": FromTextStatus, "from": str, "preset": str | None, "fields": dict[str, str],
    "why": str | None, "cost": XCost | None, "source_id": int | None, "label": str | None,
    "row": SourceRow | None})


class FromTextCounts(TypedDict):
    valid: int
    unverified: int
    invalid: int
    not_found: int
    refused: int
    connect_first: int
    already_proposed: int
    already_watching: int


class FromTextBatch(TypedDict):
    """What resolving a pasted text found (``resolve.Batch``): ``id`` is
    ``fromtext:<call id>``; ``read`` and ``total`` are characters (the model reads at most
    16,000); ``stopped_at`` names the first line past 50 proposals."""
    id: str
    call_id: int
    topic: int | None
    lines: list[FromTextLine]
    stopped_at: str | None
    read: int
    total: int
    counts: FromTextCounts
    message: str


class FromTextJob(TypedDict):
    """Resolving a pasted text as a background job (``web/jobs.py``), one at a time."""
    key: str
    state: Literal["running", "done", "failed"]
    started: float
    finished: float | None
    elapsed_s: float
    result: FromTextBatch | None
    error: str | None


class FromText(TypedDict):
    """``/api/sources/from-text``: POST ``{text, topic?}`` starts resolving (202) or answers
    the one running; GET the latest; ``/api/sources/from-text/<n>`` batch n again. None:
    404 with ``error``."""
    job: FromTextJob


class SkippedSource(TypedDict):
    id: int
    why: str


class SourcesApproved(TypedDict):
    """``POST /api/sources/approve`` ``{ids, topic?}``: what was approved, what was not and
    why; ``first_read``: Watch these on a topic never read started its first read
    (``started``), found a job running (``busy``), or started nothing (None)."""
    approved: list[int]
    skipped: list[SkippedSource]
    first_read: Literal["started", "busy"] | None


# -- /api/ideas: the idea cards --------------------------------------------------------------


class IdeaTopic(TypedDict):
    """A topic whose sources the card's evidence came from, with how many of its citations
    and the share of them that did, as written at the card's insert (``idea_topics``); the
    name is the topic's current one."""
    id: int | None
    name: str
    kind: Literal["user", "project"]
    n: int
    share: float


class IdeaTheme(TypedDict):
    """The card's theme: its lineage's latest cluster row."""
    lineage_id: str
    name: str | None
    keywords: list[str]
    size: int
    snapshot_id: int


class IdeaDemand(TypedDict):
    statement: str | None
    evidence: list[dict[str, Any]]
    supported: int


# "for" is a Python keyword: the shape is written in TypedDict's call form
IdeaCitation = TypedDict("IdeaCitation", {
    "observation_id": int | None, "url": str | None, "date": str | None,
    "observed_at": str | None, "claim": str, "source": str | None, "for": str,
    "verified": NotRequired[str]})


class IdeaDropped(TypedDict):
    """A claim the verifier dropped, and why."""
    n: int | None
    claim: str | None
    reason: str | None


class IdeaPrediction(TypedDict):
    """The card's prediction; a card written without one has neither key."""
    statement: NotRequired[str]
    by: NotRequired[str | None]


class IdeaRating(TypedDict):
    """One of the card writer's ratings; ``rated`` when it was capped."""
    value: float
    reason: str
    cites: NotRequired[list[int]]
    rated: NotRequired[float]


class IdeaExisting(TypedDict):
    n: int | None
    name: str | None
    covers: str | None


class IdeaEvidence(TypedDict):
    """A cited observation as the card shows it: the live one, else the card's snapshot of it
    (``compacted``)."""
    n: int | None
    claim: str | None
    observation_id: int | None
    summary: str | None
    source: str | None
    observed_at: str | None
    url: str | None
    compacted: bool


class IdeaDispatch(TypedDict):
    """The owner's dispatch a card was made from (``Dispatch.provenance``); an older card's
    may lack keys."""
    dispatch_id: NotRequired[str]
    title: NotRequired[str]
    slug: NotRequired[str | None]
    url: NotRequired[str | None]
    date: NotRequired[str]
    generated_at: NotRequired[str]
    strategy: NotRequired[Any]
    cluster_ids: NotRequired[list[str]]
    excerpt: NotRequired[Any]
    file: NotRequired[str]


class IdeaLineage(TypedDict):
    """An archive theme a dispatch's cluster was."""
    cluster_id: str
    lineage_id: str | None
    name: str | None


class IdeaLink(TypedDict):
    """A dispatch's link that matched no observation."""
    url: str
    claim: str


class IdeaEmbedding(TypedDict):
    """The card's embedding: with ``embedding=ref`` only the model and a link to the card."""
    model: str
    dim: int
    href: str
    text: NotRequired[str]
    vector: NotRequired[list[float]]


class IdeaEditorNotes(TypedDict):
    """What the card prompt made for the weekly editor adds (each key only when written)."""
    kind: NotRequired[str]
    existing: NotRequired[list[IdeaExisting]]
    gap: NotRequired[str]
    absorber: NotRequired[str]
    facets: NotRequired[list[str]]
    integration_point: NotRequired[str]
    channel: NotRequired[str]


class IdeaOutcome(TypedDict):
    """One outcome on a card (``outcomes.public``); an editor outcome's ``detail`` has
    ``week`` and ``why``."""
    id: int
    kind: str
    value: str
    detail: dict[str, Any]
    source: str
    created_at: str


class IdeaBuilt(TypedDict):
    """What the loop made of a card (``outcomes.built``): the newest build, gate or publish
    step's word (``state``), the loop's idea id, and the repo once published. Read from the
    rows the loop wrote before builds left Kranto (CUT); none come after."""
    state: str
    kind: Literal["build", "gate", "publish"]
    idea: str | None
    repo: str | None
    url: str | None
    at: str


class IdeaRankPart(TypedDict):
    """One graded item's part of a card's taste (``taste.parts_of``), strongest first."""
    weight: float
    why: str                   # "cites the same evidence", "same theme", "reads alike (0.54)"
    target: Literal["idea", "observation"]
    target_id: str
    value: str                 # the grade: useful, not_useful, wrong
    graded_at: str
    title: str


class IdeaRank(TypedDict):
    """Where the card ranks and why (``taste.rank``,): its place among the shown
    cards (None when unsupported), its taste, the one line a row shows ("" when none)."""
    position: int | None
    taste: float
    line: str
    parts: list[IdeaRankPart]


class IdeaTicket(TypedDict):
    """A ticket whose ``because.ideas`` names the card (``tickets.resting_on``; the one-card
    read only)."""
    id: int
    cub: str
    kind: str
    title: str
    state: str
    created_at: str


class IdeaFacts(TypedDict):
    """What a card stands on (``cards.facts``): supported citations, supported demand
    citations, distinct sites; the order of /api/ideas and of Review's cards."""
    cited: int
    asks: int
    sources: int


class IdeaPriorArtHit(TypedDict):
    label: str                 # how the card cites it: "exa 2"
    url: str
    title: str
    date: str | None


class IdeaPriorArtExisting(IdeaPriorArtHit):
    what: str                  # what the card says the result shows already exists


class IdeaPriorArt(TypedDict):
    """The card's prior-art search: ``live`` false and ``note`` the "no live
    search" sentence when none ran."""
    live: bool
    searched_at: str
    query: str
    backends: list[str]
    note: str | None
    results: int
    hits: list[IdeaPriorArtHit]
    existing: list[IdeaPriorArtExisting]


class IdeaNoveltyDropped(TypedDict):
    field: str
    sentence: str
    reason: str


class IdeaNews(TypedDict):
    """The newest news story that matches a card by the three rules."""
    brief_id: int
    n: int
    topic_id: int
    headline: str
    date: str


class Idea(TypedDict):
    """An idea card (``ideas_api.card_record``): its text, score, grade, theme and topics,
    #96's fields, its citations; the insight fields are None on cards written before them;
    a dispatch card (``origin`` dispatch) adds the pitch and its dispatch."""
    id: int
    title: str
    status: Literal["shown", "unsupported"]
    score: float | None
    grade: str | None
    rank: IdeaRank | None
    facts: IdeaFacts
    created_at: str
    origin: str
    lineage_id: str | None
    theme: IdeaTheme | None
    topics: list[IdeaTopic]
    topic: IdeaTopic | None
    output_kind: str | None        # the card writer's own word; None without one (CUT)
    one_liner: str
    who: str | None
    smallest_v1: str
    demand: IdeaDemand | None
    citations: list[IdeaCitation]
    dropped: list[IdeaDropped]
    thesis: str
    pattern: str
    where_now: str
    cheapest_test: str
    risks: str
    why_selected: str
    prediction: IdeaPrediction
    ratings: dict[str, IdeaRating]
    insight: str | None
    existing: list[IdeaExisting] | None
    gap: str | None
    moment: str | None
    mechanism: str | None
    editor_notes: IdeaEditorNotes | None
    prior_art: IdeaPriorArt | None
    novelty_dropped: list[IdeaNoveltyDropped]
    outcome: IdeaOutcome | None
    editor: IdeaOutcome | None
    outcomes: dict[str, IdeaOutcome]
    built: IdeaBuilt | None
    # where it sits on Ideas (H1, ``ideas_api.card_state``) and when a Later ends
    state: Literal["waiting", "later", "posted", "passed"]
    later_until: str | None
    evidence: list[IdeaEvidence]
    embedding: IdeaEmbedding
    pitch: NotRequired[str]
    pitch_text: NotRequired[str]
    pitch_kind: NotRequired[str | None]
    pitch_label: NotRequired[str | None]
    dispatch: NotRequired[IdeaDispatch]
    lineages: NotRequired[list[IdeaLineage]]
    links: NotRequired[list[IdeaLink]]
    tickets: NotRequired[list[IdeaTicket]]
    # "In the news" (``features.news.ideas.card_story``): one card's read only
    news: NotRequired[IdeaNews | None]


class IdeasFirst(TypedDict):
    """When the first cards come: words, the next map's time (None while fewer than
    ``needed`` items are kept), how many are kept and how many the map needs."""
    words: str
    at: str | None
    observations: int
    needed: int


class Ideas(TypedDict):
    """``/api/ideas?status=&topic=&origin=&kind=&embedding=``: the cards in the owner's order;
    ``first`` while there is no card and no filter."""
    ideas: list[Idea]
    count: int
    first: NotRequired[IdeasFirst]


class IdeaLater(TypedDict):
    """``POST /api/ideas/{id}/later`` (``idea.later``): the card's state after it."""
    id: int
    state: Literal["waiting", "later"]
    later_until: str | None
    outcome: IdeaOutcome


# -- grading: /api/feedback/vocabulary, /api/review/queue ------------------------------------


class FeedbackChip(TypedDict):
    """One "why" chip of a target, with the key that presses it."""
    key: str
    label: str
    letter: str


class FeedbackVocabulary(TypedDict):
    """``/api/feedback/vocabulary``: what the UI draws its grading controls and chips from."""
    targets: list[str]
    kinds: list[str]
    grades: list[str]
    pairs: list[str]
    origins: list[str]
    labels: dict[str, str]
    chips: dict[str, list[FeedbackChip]]


QueueSlot = Literal["build", "card"]


class QueueItem(TypedDict):
    """One item of the review queue: a build (only its id; the page knows the rest) or a
    card. ``slot`` says why it is there, for the grade's context only."""
    slot: QueueSlot
    target: Literal["build", "idea"]
    id: int | str
    title: NotRequired[str | None]
    line: NotRequired[str]
    topic: NotRequired[str | None]
    facts: NotRequired[list[str]]


class ReviewQueue(TypedDict):
    """``/api/review/queue?builds=&size=``: this week's queue
    (``feedback.build_queue``) and the chips per target."""
    week: str
    size: int
    items: list[QueueItem]
    chips: dict[str, list[FeedbackChip]]


# -- /api/websearch ---------------------------------------------------------------------------


class WebSearchHit(TypedDict):
    label: str                 # how a prompt cites it: "exa 1"
    url: str
    title: str
    date: str | None           # YYYY-MM-DD as the backend reports it; null: undated
    snippet: str
    backend: str
    query: str
    rank: int


class WebSearchResults(TypedDict):
    """``/api/websearch?q=&recency=&kind=&n=&backend=&caller=``: dated results from the live
    web. ``backend`` null and ``note`` the "no live search" sentence when nothing answered."""
    query: str
    backend: str | None
    backends: list[str]
    labels: list[str]
    searched_at: str
    cached: bool
    note: str | None
    live: bool
    hits: list[WebSearchHit]


class SearchChoice(TypedDict):
    provider: Literal["exa", "brave", "tavily", "anthropic", "none"]
    label: str
    key_env: str | None
    key_set: bool | None       # null: the choice takes no key of its own


class SearchMonth(TypedDict):
    label: str
    usd: float
    reads: int
    requests: int


class SearchSetup(TypedDict):
    """``/api/setup/search``: live search's backend (``web`` null: none), its label (Exa's free
    mode says so), the free backends, each caller's switch, this month per backend, the cap,
    and the sentence every caller says with no live search."""
    provider: str
    web: str | None
    web_label: str | None
    free_mode: bool
    free: list[str]
    note: str | None
    monthly_usd: float | None
    callers: dict[str, str]
    failing: dict[str, int]
    choices: list[SearchChoice]
    free_mode_words: str | None
    recent_weeks: int
    cache_hours: float
    month: dict[str, SearchMonth]
    no_search: str


class WebFetch(TypedDict):
    """``/api/websearch/fetch?url=&max_chars=``: a page's text, or why it was not read."""
    url: str
    text: str


class UnreadableMark(TypedDict):
    """``unreadable`` on a row that could not be built (``rowsafe``, RCA A3): what it is, the
    words the list shows, the error's id and class."""
    what: str
    words: str
    error_id: str
    exception: str


class Unreadable(TypedDict):
    """A row that stands for one that raised: any list of the API may hold it in a row's
    place, with the row's id and what was still known of it (a label, a kind). The page's
    reads take it out of the list and show it as "Couldn't read this <thing>" (the page's
    ``lib/unreadable.ts``), so the list's own type stays its rows'."""
    id: Any
    unreadable: UnreadableMark


class ErrorAnswer(TypedDict):
    """What a request that failed answers (status 500, ``App.error_answer``)."""
    error: str
    error_id: str
    exception: str
    version: str
    report: str


class ErrorRecord(TypedDict):
    """One error kept by its id (``rowsafe.note``): Kranto's frames only, no values."""
    id: str
    at: str
    kind: str
    where: str
    exception: str
    frames: list[str]
    version: str
    message: NotRequired[str]       # errtrace's template: known words, <x>, <n>
    signature: NotRequired[str]     # errtrace's: the id is its first eight characters


class ErrorReport(TypedDict):
    """``/api/errors/{id}``: what Send this error files, and GitHub's prefilled page for it."""
    id: str
    title: str
    body: str
    url: str
    record: ErrorRecord


class Errors(TypedDict):
    errors: list[ErrorRecord]


OPEN = frozenset({"Grade", "RunSummary", "RunSourceReport", "StrikeConfig", "TrajectoryPoint",
                  "MapQuality", "StructureNull", "MapStories", "IdeaRating", "IdeaDispatch"})

class GradesCounts(TypedDict):
    """The owner's grades on cards and evidence over the window (cleared ones apart)."""
    grades: int
    cards: int
    evidence: int
    cleared: int


class GradesMoved(TypedDict):
    id: int
    title: str
    taste: float
    line: str
    position: int | None


class GradesIdeas(TypedDict):
    """``moved``: shown cards whose taste is not 0 and that the owner did not grade; ``still``:
    the rest of the ungraded ones, where they would be anyway; ``top``: the five that moved most."""
    shown: int
    moved: int
    graded: int
    still: int
    top: list[GradesMoved]


class GradesTheme(TypedDict):
    """A theme of the latest map with a taste: ``skip`` when the next ideas run leaves it out."""
    lineage_id: str
    name: str
    taste: float
    skip: bool
    line: str
    parts: list[IdeaRankPart]


class GradesClosest(TypedDict):
    id: int
    label: str
    down: int
    up: int


class GradesKept(TypedDict):
    id: int
    label: str
    at: str
    down: int
    up: int


class GradesSources(TypedDict):
    """The sources the rule recommends removing, the closest one otherwise, the kept ones."""
    window_days: int
    remove_after: int
    recommended: list[SourceToRemove]
    closest: GradesClosest | None
    kept: list[GradesKept]


class GradesSummary(TypedDict):
    """``/api/grades/summary`` (``taste.summary``): what the owner's grades did (Your grades)."""
    window_days: int
    counts: GradesCounts
    ideas: GradesIdeas
    themes: list[GradesTheme]
    sources: GradesSources


class HomeVisit(TypedDict):
    """The home's visit marker (``home.visit``; ``POST /api/home/visit`` answers it)."""
    at: str
    previous: str | None


class HomeWaiting(TypedDict):
    drafts: NotRequired[int]
    prepared: NotRequired[int]
    error: NotRequired[str]
    error_id: NotRequired[str]


class HomeBriefItem(TypedDict):
    n: int
    title: str
    source: str | None


class HomeTopicRef(TypedDict):
    id: int
    name: str


class HomeBrief(TypedDict):
    topic: HomeTopicRef
    brief: int
    at: str
    items: list[HomeBriefItem]
    more: int


class HomeNewest(TypedDict):
    """The topic of the newest good brief of any day (the console's first starter)."""
    id: int
    name: str
    at: str


class HomeBriefs(TypedDict):
    """Today's brief, or ``error`` (and ``error_id``) when it could not be read."""
    topics: NotRequired[list[HomeBrief]]
    more: NotRequired[int]
    newest: NotRequired[HomeNewest | None]
    error: NotRequired[str]
    error_id: NotRequired[str]


class HomeCard(TypedDict):
    id: int
    title: str
    at: str
    grade: str | None


class HomeIdeas(TypedDict):
    """The five newest cards in Ideas' order; ``new`` since ``since`` (null: the last 24 h)."""
    rows: NotRequired[list[HomeCard]]
    new: NotRequired[int]
    since: NotRequired[str | None]
    total: NotRequired[int]
    error: NotRequired[str]
    error_id: NotRequired[str]


class HomeNext(TypedDict):
    kind: str
    words: str
    at: str


class HomeQuiet(TypedDict):
    topics: NotRequired[int]
    sources: NotRequired[int]
    read_at: NotRequired[str | None]
    next: NotRequired[HomeNext | None]
    error: NotRequired[str]
    error_id: NotRequired[str]


class HomeAwayRow(TypedDict):
    """A card (``id``) or a brief's lead item (``brief``, ``n``, ``topic``, ``source``)."""
    kind: Literal["card", "brief"]
    title: str
    at: str
    id: NotRequired[int]
    grade: NotRequired[str | None]
    brief: NotRequired[int]
    n: NotRequired[int]
    topic: NotRequired[str]
    source: NotRequired[str | None]


class HomeAway(TypedDict):
    since: str
    days: int
    rows: list[HomeAwayRow]
    ideas: int
    briefs: int
    sentence: str


class HomeFirstRead(TypedDict):
    """The read as it goes, for the first hour's topic: source n of m, and that topic's items
    kept and read so far in this read."""
    source_index: int
    sources: int
    kept: int
    judged: int
    started_at: str | None


class HomeFirst(TypedDict):
    """The first hour (``core.home._first``,): the newest topic that watches a
    place and has no first brief yet; ``brief_minutes`` the estimate of its first brief (None
    once enough are kept, or when nothing can be said); ``early_kept`` how many kept items write
    it. ``error``/``error_id`` when the block could not be read."""
    topic: NotRequired[HomeTopicRef]
    rows: NotRequired[list[TopicStartRow]]
    quiet: NotRequired[str | None]
    read: NotRequired[HomeFirstRead | None]
    news_on: NotRequired[bool]
    no_key: NotRequired[bool]
    brief_minutes: NotRequired[int | None]
    early_kept: NotRequired[int]
    error: NotRequired[str]
    error_id: NotRequired[str]


class HomeToday(TypedDict):
    """``/api/home`` (``core.home``): the home in one read. ``slots``, ``widgets``, ``library``
    and ``rows`` are the widgets' and the cubs' rows, kept for one wave (``features/home.ts``
    types them). ``first``: the first hour, None once the newest topic has its first brief."""
    date: str
    now: str
    sentence: str | None
    waiting: HomeWaiting
    briefs: HomeBriefs
    ideas: HomeIdeas
    quiet: HomeQuiet
    first: HomeFirst | None
    visit: HomeVisit | None
    away_days: int
    away: HomeAway | None
    slots: dict[str, Any]
    budget_s: float
    rows: NotRequired[dict[str, Any]]
    widgets: NotRequired[list[Any]]
    custom: NotRequired[bool]
    library: NotRequired[list[Any]]
    default: NotRequired[list[str]]


# what the page reads, by the path it asks for
class PostAccount(TypedDict):
    """An account a draft may go through (``web/post_api.py``): ``state`` is ``connected``,
    ``needs_login`` or ``not set``; ``platform`` the newsletter platform's name once one is
    chosen."""
    key: Literal["newsletter", "mastodon", "blog"]
    word: str
    state: str
    account: str | None
    platform: str | None


class PostSibling(TypedDict):
    """One site of a write's short posts: its newest draft, the site, its name and where the
    draft stands (``waiting``, ``sent``, ``earlier``)."""
    id: int
    site: str
    word: str
    state: str


class PostSitesLine(TypedDict):
    """Post's one line about where short posts go, and how many sites are ticked."""
    line: str
    ticked: int


class PostDraft(TypedDict):
    """One draft's row on Post: ``kind`` the account it goes through (``newsletter``,
    ``mastodon``, ``blog``, else the service's name), ``word`` its kind in a word; ``ticket`` the
    open ask to Send, ``again`` the ask a press offers again; ``line`` where it stands and
    ``verb`` the ask's button (``core.asks.row``); ``said`` what happened in words; ``note`` and
    ``link`` the platform's own words and link once sent; ``account``: its account is
    connected."""
    id: int
    ref: str
    cub: str
    kind: str
    word: str
    title: str
    fact: str
    at: str
    ticket: int | None
    again: int | None
    verb: str | None
    line: str | None
    said: str | None
    note: str | None
    link: str | None
    account: bool
    # a short post's own (``post_api._short_row``): its site, the write it belongs to, how it
    # goes (``open``: the person posts it in the site; ``direct``: Kranto posts it after their
    # yes), and on Post's waiting row, every site of the write
    site: NotRequired[str]
    site_word: NotRequired[str]
    write: NotRequired[str | None]
    way: NotRequired[Literal["open", "direct"]]
    sites: NotRequired[list[PostSibling]]


# A Write a post that wrote no draft: ``about`` and ``as`` as it was asked (Try again
# asks the same), ``error`` why in the owner's words, ``title`` what it was about, ``fix`` the
# route that fixes it (``settings/watching`` when no model key is set) or null.
PostFailed = TypedDict("PostFailed", {
    "about": str, "as": str, "error": str, "at": str, "title": str | None, "fix": str | None})


class Post(TypedDict):
    """``GET /api/post``: the drafts waiting (a draft's ask has no time limit), sent and
    earlier, newest first, the three accounts, and the writes that failed in the last week
    and were not dismissed (``failed``)."""
    line: str
    drafts: list[PostDraft]
    sent: list[PostDraft]
    earlier: list[PostDraft]
    accounts: list[PostAccount]
    sites: PostSitesLine
    failed: list[PostFailed]


class PostPart(TypedDict):
    """One part of a short post or a thread: its words."""
    text: str


class PostEdit(TypedDict):
    """The words the editor opens with: ``title`` (None for a short post) and ``body`` (a long
    post, markdown) or ``parts`` (a short post)."""
    title: str | None
    body: NotRequired[str]
    parts: NotRequired[list[PostPart]]


class PostLimit(TypedDict):
    """The most a part may hold, and in what unit."""
    max: int
    unit: str


class PostCounted(TypedDict):
    """One post of a short post's draft, with its length counted the site's way."""
    text: str
    used: int


class PostExtra(TypedDict):
    """What else goes with a short post's words, in a line: the link, the card, what Kranto
    took off. ``drop``: the person may remove it."""
    key: str
    words: str
    drop: bool


class PostDirect(TypedDict):
    """Post directly, when the person switched the site to it: the button's words, whether the
    account is connected, and why not."""
    word: str
    ready: bool
    why: str | None


class PostSheet(PostDraft):
    """``GET /api/post/d/{id}``: a draft's row with its group, its words as markdown (what Copy
    and Download give), the file name Download uses, its length and its account."""
    group: Literal["waiting", "sent", "earlier"]
    markdown: str
    filename: str
    words: int
    account_of: PostAccount | None
    # the draft's editor (``post_api.editable``)
    edit: PostEdit
    can_edit: bool
    cannot_edit: str | None
    limit: PostLimit | None
    edited: bool
    edited_from: int | None
    original_draft: int
    # a short post's draft page (``post_api.short_sheet``)
    parts: NotRequired[list[PostCounted]]
    extras: NotRequired[list[PostExtra]]
    siblings: NotRequired[list[PostSibling]]
    open: NotRequired[str | None]
    open_off: NotRequired[str | None]
    tier: NotRequired[Literal["open", "send"]]
    direct: NotRequired[PostDirect | None]
    posted_by_you: NotRequired[bool]


class PostingSite(TypedDict):
    """One site on Settings › Posting: the ways it can go (``open``, ``direct``), the person's
    choices, the posting account when Kranto can post there, and its limit."""
    id: str
    name: str
    ways: list[str]
    ticked: bool
    direct: bool
    can_direct: bool
    account: str | None
    account_state: str
    connection: str | None
    needs: str | None
    instance: str | None
    limit: int
    unit: str
    disclose: bool


class PostingGone(TypedDict):
    """A site Kranto does not offer, with why, and what would make it possible."""
    id: str
    name: str
    why: str | None
    later: str | None


class PostingBlog(TypedDict):
    """The person's own site (Sanity), step one of Write a post."""
    state: str
    account: str | None
    post_url: str | None


class Posting(TypedDict):
    """``GET /api/post/sites`` (Settings › Posting): every site Kranto offers with the person's
    choices, the ones it does not offer, the disclosure line, and the blog."""
    sites: list[PostingSite]
    not_offered: list[PostingGone]
    disclosure: str
    blog: PostingBlog


class PostEdited(TypedDict):
    """``POST /api/post/d/{id}/edit``: the new draft, its ask, whether a waiting send was
    withdrawn, and what the page says."""
    ok: bool
    id: int
    ref: str
    ticket: int
    withdrew: bool
    say: str


RETURNS: dict[str, type] = {
    "/api/home": HomeToday,
    "/api/post": Post,
    "/api/post/d/{id}": PostSheet,
    "/api/post/sites": Posting,
    "/api/status": Status,
    "/api/topics": Topics,
    "/api/sources": Sources,
    "/api/today": Today,
    "/api/health": Health,
    "/api/observations": Observations,
    "/api/observations/{id}": ObservationPage,
    "/api/feedback": FeedbackGrades,
    "/api/rollups": Rollups,
    "/api/map": Map,
    "/api/clusters": Clusters,
    "/api/archive/themes": ArchiveThemes,
    "/api/topics/{id}": TopicPage,
    "/api/topics/{id}/scout": Scout,
    "/api/topics/{id}/start": TopicStart,
    "/api/topics/{id}/sources": TopicSourcesChange,
    "/api/topics/{id}/status": TopicStatusChange,
    "/api/sources/from-text": FromText,
    "/api/sources/from-text/{id}": FromText,
    "/api/sources/approve": SourcesApproved,
    "/api/sources/{id}": SourcePage,
    "/api/sources/preview": SourcePreview,
    "/api/catalog": Catalog,
    "/api/connections": Connections,
    "/api/newsletter": Newsletter,
    "/api/setup": Setup,
    "/api/setup/provider": ProviderSetup,
    "/api/ideas": Ideas,
    "/api/ideas/{id}/later": IdeaLater,
    "/api/feedback/vocabulary": FeedbackVocabulary,
    "/api/review/queue": ReviewQueue,
    "/api/grades/summary": GradesSummary,
    "/api/websearch": WebSearchResults,
    "/api/websearch/fetch": WebFetch,
    "/api/setup/search": SearchSetup,
    "/api/errors": Errors,
    "/api/errors/{id}": ErrorReport,
}
