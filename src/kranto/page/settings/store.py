"""The loop's settings and paths.

Everything lives under the loop home: ``$KRANTO_LOOP_HOME``, else this user's kranto install's
loop home (``kranto_loop_home``), else ``~/kranto-loop``:

- ``loop.yaml``: settings (any subset of ``DEFAULTS``; missing keys take the default);
- ``loop.db``: the ledger (``ledger.py``);
- ``inbox/``: drop ``*.md`` / ``*.txt`` ideas here; read ones move to ``inbox/done/``;
- ``PAUSE``: the kill switch (no new pitches or builds while it exists);
- ``STOP``: asks a running daemon to exit (``brb loop stop`` also stops the builds);
- ``daemon.pid``, ``daemon.lock``, ``daemon.log``; ``publish/<id>/``: the staged repos.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path

import yaml

from kranto import legacy

from .. import paths
from ..upstream import REPOS as UPSTREAM

HOME_ENV = paths.LOOP_HOME_ENV
# The server's URL from a host (the server mounting the UI passes it to ``brb loop``
# subprocesses this way): wins over ``kranto.url`` in loop.yaml.
KRANTO_URL_ENV = "KRANTO_SERVER_URL"

# The weekly editor's day and cadence (``ideas``; loop/editor.py reads them)
EDITOR_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
EDITOR_CADENCES = ("weekly", "daily")

# The owner's standing rule: no spend ceiling unless asked for (daily_usd: null).
DEFAULTS: dict = {
    "tasks_dir": "~/tasks",           # accepted ideas become tasks here (the owner's brb ui)
    "concurrency": 1,                 # builds at once (the owner: one unless configured)
    "daily_usd": None,                # optional: no new pitch or build once today's spend >= this
    "tick_s": 30,                     # the daemon's pace
    "intake_every_s": 600,            # the server and the inbox are read this often
    "pitch_per_tick": 3,
    # What is sent to the pitch (section 2). manual: nothing is pitched until
    # the owner sends it (Send to build, ``brb loop send``); rule: every new idea is pitched,
    # as before (the server cards graded not useful or wrong never are); editor: as manual, and
    # the weekly editor (``ideas``) reads the week and may nominate one idea for the owner.
    "intake": {"auto": {"mode": "manual"}},
    # The weekly editor (loop/editor.py), read only with intake.auto.mode
    # editor. Once a week (cadence weekly, on editor.day from editor.hour, local time; daily:
    # every day from editor.hour) it reads the week's papers from the server's API (the
    # 170 strongest observations and the 25 strongest releases, the map's themes, the
    # week's cards and the owner's pitches, the ledger) and the last 12 weeks of nominations
    # with the owner's verdicts (constants in loop/editor.py, #8), and nominates at most max_per_week build ideas a
    # week, or says "nothing this week" with the closest miss. model: the editor's (Opus 5.5,
    # the owner's choice). research: one call with web search (WebSearch only) checks the
    # editor's pick, and the editor decides once more on its dossier (one judge: the desk's
    # word is evidence, never a state); max_usd caps that call (null: no cap).
    # nominee_auto_build: the editor's final nominee is sent to build without a click (false:
    # the owner presses Build). Build this by hand never waits for the editor.
    # editor.command: tests only (the detached run, as build.command).
    "ideas": {"cadence": "weekly", "max_per_week": 1, "nominee_auto_build": False,
              "editor": {"day": "sunday", "hour": 18, "model": "claude-opus-5-5",
                         "command": None},
              "research": {"enabled": True, "model": "claude-sonnet-5-5", "max_usd": 1.5}},
    # The server's idea cards: through its API at ``url`` (``http://127.0.0.1:8765``) when it
    # is serving; ``db`` is read (read-only) only when no URL is set: the page on its own,
    # pointed at a workspace's ``<workspace>/data/kranto.db``. Neither set: no cards.
    # A host that mounts the UI passes its own URL, which wins over this one.
    "kranto": {"enabled": True, "url": None, "db": None,
                 "include_unsupported": False},
    "fetch": {"enabled": True, "timeout_s": 20, "max_bytes": 400_000, "max_chars": 12_000},
    # Models: Settings › Building › Models writes these (src/kranto/page/models.py lists the roles and the
    # models offered); null is the Claude Code CLI's default. Haiku 4.5 until 2026-10-08.
    "pitch": {"model": None,          # null: the Claude Code CLI's default (a strong model)
              "summary_model": "claude-haiku-5-5",
              "min_buildability": 0.6, "max_errors": 3,
              # the gate on the pitch's own scores, applied like min_buildability to a
              # pitch prompt that returns them (pitch v2); null: no gate. Recommended with
              # pitch v2: min_insight 0.5, min_differentiation 0.4, min_grounding 0.5
              "min_insight": None, "min_differentiation": None, "min_grounding": None,
              # pitch v3's durability and breadth scores (step 6), the same way
              "min_durability": None, "min_breadth": None,
              # the pitch records how it reads each claim that can't be
              # honoured as written (with a setting and its default where a number decides),
              # and holds an idea no reading of which keeps its spirit; false: as before
              "interpret_claims": True,
              # CON D-2 (the owner, 2026-10-22): the pitch reads the owner's own words about the
              # card's topic (its description, never a model's), one line; false: as before
              "topic_words": True},
    "build": {"policy": None, "harness": "claude-code",
              "owner": "none", "max_usd": None,     # null: the policy's own cap
              # stage models over the policy's (build, claims, verify, oracle, repair,
              # readiness: src/kranto/page/models.py); passed as $KRANTO_V5_MODELS (a retired
              # stage's, mutants, is ignored)
              "models": {},
              # stage caps in USD over the policy's build.stage_caps (empty: no stage cap, the
              # default); e.g. {build: 6.0, verify: 2.5}, null removes a policy cap. Passed as
              # $KRANTO_V5_STAGE_CAPS. Turn and time limits per session are the policy's.
              "stage_caps": {},
              "retries": 1,                         # a failed build is retried once, then held
              "max_resumes": 3,                     # restarts after a crash or a stop
              # #2: a build the gate holds gets this many automatic code revise rounds
              # (origin auto) with the hold as their brief, before it waits for you; they stop
              # early when a round leaves the hold as it was. 0: off. revise.max_per_build
              # bounds them too
              "auto_repair": 1,
              # which flow builds: v5 (today's, the default until the proofs pass)
              # or simple (Plan, Build, Check ⇄ Fix, Publish: policies/simple). Used when
              # build.policy is left at its default
              "flow": "v5",
              # the simple flow's fix rounds (0-5); null: the policy's (2). Passed as
              # $KRANTO_FIX_ROUNDS; build.auto_repair doesn't apply to it (its rounds are it)
              "fix_rounds": None,
              # Stop round, Close: SIGTERM, then SIGKILL after this many seconds
              "kill_grace_s": 10,
              # the flash offers Undo after Stop round and Cancel this long (OI)
              "undo_s": 10,
              "command": None,                    # null: `python -m kranto.page.cli build`
              "revise_command": None,               # null: `python -m kranto.page.cli revise`
              # the Claude Code binary builds, Open in Claude Code and the pitch run (Kranto
              # setup --claude PATH, or found off PATH by the wizard); null: claude on PATH
              "claude_command": None,
              # BL (the owner, 2026-10-18): builds, fixes, pitches, the researcher and Open in
              # Claude Code run on your Claude plan: the login token Kranto keeps (kranto setup
              # building), the unit's own token, or Claude Code's sign-in. true: without one,
              # they may log in with the watcher's Claude API key (Kranto's .env) and bill it;
              # false: a build is held until you set up your plan. A key in the unit's own
              # environment is used either way (harness/handoff.py)
              "allow_api_key": False},
    # Kranto's exam, outside the product, passed to builds as $KRANTO_EXAM:
    # reruns of a failing scenario or own test command (5 runs in all); failures out of those
    # at which an intermittent item fails (below: an amber row); a scenario failing once in 5
    # is retired as flaky (false: kept as intermittent); adopt: fixes (every fix commit comes
    # with a test of the product's own) | all (one more session asks for a test of its own
    # per scenario: costs a session per round) | off; indexes: the
    # install phase's allow-list ([] = no network at all); evidence_asset: the checks tarball
    # on the release (false: the evidence stays in the den and on the build page)
    "exam": {"reruns": 4, "intermittent_hold_min": 3, "flaky_retire": True, "adopt": "fixes",
             "indexes": ["pypi.org", "files.pythonhosted.org", "registry.npmjs.org"],
             "evidence_asset": True},
    # The regression corpus: every delivery adds its entry; after an update a
    # daily job replays it (no model) and says when a past verdict would change
    "corpus": {"auto_add": True, "replay_daily": True},
    # Kranto's own GitHub connection (github_user,): the OAuth App's client id for this
    # install; null: the release's (github_user.CLIENT_ID); "" turns the device flow off
    "github": {"client_id": None},
    "publish": {"enabled": True,
                "approval": "required",             # required | auto (public without asking)
                "owner": None,                      # null: the gh login
                "license": "MIT",                   # MIT | Apache-2.0 | none
                "copyright": None,                  # null: git config user.name
                # the model that writes a product's public text from the product and reviews
                # it once before the push (describe.py); wording is never a hold
                "honesty_model": "claude-haiku-5-5",
                "max_attempts": 3,
                # the maintenance files in the first commit, and the label scheme and repo
                # settings right after the repo is created. maintenance_files:
                # policy (.github/kranto.yml + labels.yml, the machine-read policy; AGENTS.md,
                # CI and the rest are the product's) | all (the whole MAINTAIN.md set from
                # templates) | none (a bare repo)
                "maintenance_files": "policy",
                "gh_command": None,                 # null: ["gh"] (logged in as the owner)
                # the pre-push checks run when a build stops, in a process of their own
                # (precheck.py); a press that finds them not run starts them and waits for
                # nothing
                "precheck_concurrency": 1,          # pre-push checks running at once
                # Publish anyway: the holds the owner may publish over, into
                # a private repo with the override disclosed. Never overridable, whatever this
                # says: nothing delivered, an open critical or high security finding, a
                # secrets hit, a red bind_localhost.
                # documents (SECURITY.md or READINESS.md missing) may be added here.
                "anyway": {"may_override": ["tests", "completeness", "safe_defaults"]}},
    # Ask for changes: a revise round of a held or ready build that has no
    # repo yet. max_usd null: no cap; models: the change and repair sessions' models (null:
    # the CLI's default); max_per_build null: no limit on rounds per build. max_identical: a
    # round is refused when this many rounds (stopped and failed ones included) already ran
    # against the same hold, which did not change, with the same instructions or the hold's
    # own words (never a third identical round); null: no limit.
    "revise": {"enabled": True, "max_usd": None, "models": {"build": None, "repair": None},
               "max_per_build": None, "max_identical": 2},
    # kranto mcp: actions false means the MCP server reads only (checked by
    # the service at api/act for origin mcp)
    "mcp": {"actions": True},
    # Capabilities (Settings › Capabilities): per capability, by name,
    # {enabled, pin, scope, stages, settings}: a capability runs only once enabled, and only
    # while its folder's hash equals the pin written when it was enabled; scope off |
    # pipeline (the pitch decides) | always | manual (the owner turns it on per build);
    # stages null: the manifest's; settings: the manifest's fields. A capability left out
    # here is off. max_heavy_concurrent: builds with a capability declaring ram_gb >= 2 at
    # once (within concurrency). kranto_mod: the reporter every build session loads (kind mod,
    # or classic: settings hooks, if a CLI update breaks the mod) and its two deny guards.
    "capabilities": {"max_heavy_concurrent": 1,
                     "kranto_mod": {"kind": "mod",
                                   "guards": {"acceptance": True, "evidence": True}}},
    "nudge": {"enabled": False, "path": "~/kranto-loop/kranto-notes.md"},
    "feed": {"title": "brb loop", "max_entries": 50,
             "ui_url": "http://127.0.0.1:8790/"},
    # factory_repos: where factory issues go (Kranto; the watcher). The section kept its name
    # when the project chat it was part of was removed; the chat's own keys
    # (model, timeout_s, max_turns, concurrency, sandbox, auto) are no longer read.
    "chat": {"factory_repos": dict(UPSTREAM)},
    # Feedback (FB): the repository its issues go to, Kranto's release repository (where updates
    # come from), as the person who sends it (their own gh, or GitHub's new-issue page); a
    # fork or a move sets its own here.
    "feedback": {"repo": UPSTREAM["watcher"]},
    # Open in Claude Code: the real Claude Code in the page, one session per
    # subject under <home>/term/. enabled null (automatic): offered where bubblewrap can make
    # its sandbox and Kranto has a Claude token (kranto doctor says both); true: offered, also
    # without bubblewrap (with a warning that the sandbox is absent); false: not offered.
    # max_sessions live at once (a
    # further Open says which to end); idle_min: a session nobody watches and that prints
    # nothing for this long is ended (Open again resumes the conversation). model null: the
    # CLI's default. net_hosts: what the session may reach without asking; any other host is
    # refused until you allow it in the page, for that session only. quiet_hosts: Claude Code's
    # own background traffic (its updater, changelog and telemetry), refused without asking
    # (net.jsonl says "quiet"); a host also in net_hosts is allowed. daily_usd null: no cap of
    # its own (the top-level daily_usd still applies). allow_api_key: a session may log in with
    # the watcher's Claude API key (ANTHROPIC_API_KEY from Kranto's .env) when there is no Claude
    # login token; false: Open says what it would bill and offers Use the API key (a key in the
    # unit's own environment is used either way). On an API key, a sources session runs on the
    # watcher's reason model unless model is set.
    "term": {"enabled": None, "allow_api_key": False, "max_sessions": 3, "idle_min": 60,
             "model": None,
             "net_hosts": ["api.anthropic.com"],
             "quiet_hosts": ["downloads.claude.ai", "raw.githubusercontent.com",
                             "datadoghq.com", "statsig.anthropic.com"],
             "daily_usd": None},
    # The console (term/console.py; Settings › Assistant): your own Claude Code
    # or Codex docked in the page, one conversation per harness, resumed by default. open: the
    # panel is open when Kranto opens (each browser remembers collapsed or minimized). harness
    # null: Claude Code when installed, else Codex. model.<harness>: its --model (none: its
    # own default). permission: auto (the owner's choice: Claude Code's auto mode; Kranto's tools
    # are pre-approved by Kranto's plugin, so Kranto's ladder decides them), ask (asks before edits
    # and commands) or accept-edits. config: own (your login, settings, plugins, MCP servers
    # and CLAUDE.md) or Kranto (Kranto's plugin and settings only). daily_usd null: no cap.
    "ask": {"open": True, "harness": None, "model": {}, "permission": "auto", "config": "own",
            "daily_usd": None},
    # Maintaining the published repos through GitHub (MAINTAIN.md Settings ›
    # Maintenance): the tick polls each one every poll_s and triages new issues with a
    # no-tools call (at most triage_max_per_poll a poll); the UI's GitHub reads are kept
    # cache_s. repos: more owner/name repos beyond the loop's published builds. gh_command
    # null: publish's gh (the owner's login, decision D1 for now). Revise: at most
    # concurrency fixes at once, counted in the build slots; max_usd null: no cap per fix (the
    # repo's revise.max_usd applies as well; the smaller wins); net allowlist: a fix session
    # reaches only net_hosts (public: anything public, as builds do); lesson_label: a merged fix
    # of a user-found bug is labelled lesson. revise_command: tests only (the detached
    # fix process, as build.command). token_env_file: a 0600 file with GH_TOKEN=
    # (a fine-grained token, the owner's or a bot account's) that maintenance's gh uses
    # instead of the login; null: the login. identity: which identity
    # maintenance, Projects' filing and factory issues act as: auto (Kranto's own GitHub App
    # once it is created and installed under Settings › Publishing › GitHub, else the token file, else the
    # login), app, token or login. Publishing always uses the login. doctor_days: how often
    # each repo's AGENTS.md and workflows are checked for drift and self-hosted runners (Today
    # says so); 0: never.
    # agent traces: a payload is shown page_kb at a time, and one span's
    # payload is read whole up to payload_max_mb (beyond it: open the file at its line).
    # export: where `brb trace export --otlp` sends a trace when no URL is given (empty:
    # nowhere) and whether it sends the redacted content too
    "trace": {"page_kb": 64, "payload_max_mb": 2,
              "export": {"otlp_url": None, "content": False}},
    "maintain": {"enabled": True, "poll_s": 900, "cache_s": 300,
                 "triage_model": "claude-haiku-5-5", "triage_max_per_poll": 20, "repos": [],
                 "gh_command": None, "token_env_file": None, "identity": "auto",
                 "concurrency": 1, "max_usd": None,
                 "net": "allowlist",
                 "net_hosts": ["api.anthropic.com", "pypi.org", "files.pythonhosted.org",
                               "github.com", "api.github.com", "objects.githubusercontent.com"],
                 "lesson_label": True, "doctor_days": 7, "revise_command": None,
                 # refresh_max: how many times Kranto re-does one of its fix PRs on a main that
                 # moved under it with a conflict (current.py); not an attempt; 0: never
                 "refresh_max": 2,
                 # backfill_command: tests only (the backfill PR the page starts, detached)
                 "backfill_command": None,
                 # recheck_command: tests only (Re-check, the read the page starts, detached)
                 "recheck_command": None,
                 # policy_command: tests only (the merge policy PR the switch opens, detached)
                 "policy_command": None,
                 # self lists the page among the repos the lane polls, so a
                 # factory issue the owner labels go gets a maintenance PR (Kranto never merges
                 # it: merge.kranto_patch never); exam: on a product fix PR, report runs the
                 # latest release's checks asset against the branch and posts the result,
                 # require fails the PR on a regression, off does nothing
                 "self": False, "exam": "report",
                 # adopted repositories (a repo Kranto did not build; its policy is
                 # its profile under maintain/repos/). adopt: onboarding's bounds, the one
                 # optional no-tools proposal (model on/off, model_id), re-baselining when the
                 # default branch moves (refresh), how many onboardings at once, and the index
                 # hosts the install phase's proxy may reach. detach_keep_days: a removed
                 # repo's profile is kept this long, so adding it again restores it.
                 # identity_fallback_to_login: a maintenance token that cannot reach an adopted
                 # repo never becomes the owner's login unless this is true.
                 "adopt": {"model": True, "model_id": "claude-haiku-5-5", "refresh": True,
                           "install_timeout_s": 900,
                           "test_timeout_s": 1800, "concurrency": 1,
                           "indexes": ["pypi.org", "files.pythonhosted.org", "registry.npmjs.org",
                                       "proxy.golang.org", "sum.golang.org", "static.crates.io",
                                       "index.crates.io"]},
                 "detach_keep_days": 30, "identity_fallback_to_login": False},
    # Projects (Settings › Publishing › Projects): a published build or a confirmed adopted
    # repo is a project, with a charter (one page: what it is, for whom, what it promises and
    # will not do) and a loop that asks every evolve.every_days "given this repo, its charter
    # and these sources, what can we improve?" (one no-tools call). create.on: publish (private
    # or public) | public. topic: the project topic in the server (create auto | ask | off;
    # approve core | none | all: the scout's proposals approved). evolve: skip_when_quiet makes
    # no call when nothing changed. autonomy: the preset (quiet | hands-on | off) and, per
    # class, auto | ask | list over it (null: the preset's); scope is never auto. gate: what
    # an idea needs before it is filed or asked. changes.file_issues_outside: issues on repos
    # the owner does not own. budget.monthly_usd null: no cap. Spend stays uncapped by default.
    "projects": {"enabled": True, "create": {"on": "publish"},
                 "charter": {"model": "claude-sonnet-5-5"},
                 "topic": {"create": "auto", "approve": "core"},
                 "evolve": {"every_days": 7, "skip_when_quiet": True, "min_hours_between": 24,
                            "model": "claude-sonnet-5-5", "max_ideas": 8,
                            # maintenance proposals kept per run (the drift checks are
                            # maintenance filed by code, never shown to the model)
                            "max_maintenance": 1,
                            "concurrency": 1, "dup_sim": 0.6},
                 "autonomy": {"preset": "quiet", "patch": None, "minor": None, "scope": None},
                 "gate": {"min_confidence": 0.5, "min_agree_runs": {"patch": 1, "minor": 1},
                          "require_evidence_kinds": []},
                 "changes": {"file_issues_outside": False,
                             "priority": {"security": "p2", "broken_integration": "p2",
                                          "default": "p3"}},
                 "decline_days": 30, "budget": {"monthly_usd": None},
                 "health": {"stale_pr_days": 14}},
}


def kranto_loop_home() -> Path | None:
    """The loop home of this user's kranto install, if there is one: the kranto home
    (``$KRANTO_HOME``, else the one ``kranto up`` or ``kranto adopt`` recorded in
    ``~/.config/kranto/home``, or ``home.<unit>`` for another ``$KRANTO_UNIT``), then its
    config's ``brb.loop_home``, else its ``loop/`` folder. So a ``brb`` command typed on a
    kranto install uses that install's loop, never a second, empty ``~/kranto-loop``."""
    found = os.environ.get(paths.KRANTO_HOME_ENV) or paths.read_pointer(Path.home())
    if not found:
        return None
    kranto = Path(found).expanduser()
    f = paths.Layout(kranto).config          # kranto.yaml, else an adopted home's kranto.yaml
    if f.is_file():
        try:
            brb = (yaml.safe_load(f.read_text()) or {}).get("brb") or {}
        except (OSError, yaml.YAMLError, AttributeError):
            brb = {}
        if isinstance(brb, dict) and brb.get("loop_home"):
            at = Path(str(brb["loop_home"])).expanduser()
            return at if at.is_absolute() else kranto / at
    default = paths.Layout(kranto).loop
    return default if default.is_dir() else None


def home(path: str | Path | None = None) -> Path:
    p = Path(path or os.environ.get(HOME_ENV) or kranto_loop_home()
             or paths.DEFAULT_LOOP_HOME).expanduser()
    return p.resolve()


_said: set = set()


def _say_once(f: Path, text: str) -> None:
    """Log a loop.yaml's problems once per version of the file (the loop reads it every tick)."""
    try:
        key = (str(f), f.stat().st_mtime_ns, text)
    except OSError:
        key = (str(f), None, text)
    if key not in _said:
        _said.add(key)
        import logging
        logging.getLogger("kranto.page.settings").warning("%s", text)


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


_parsed: dict = {}          # loop.yaml by path: (its text, the settings with defaults, problems)


def _settings(f: Path) -> tuple[dict, list]:
    """``f`` parsed and checked once per text: the pages build a Config many times a request,
    and parsing the YAML was most of ``/api/kranto`` (SL); reading the file is cheap. The
    caller gets its own copy."""
    from .schema import check
    text = f.read_text() if f.exists() else None
    hit = _parsed.get(str(f))
    if hit is None or hit[0] != text:
        user = (yaml.safe_load(text) or {}) if text is not None else {}
        user = legacy.loop_settings(user)      # an old install's section name
        hit = (text, _merge(DEFAULTS, user), check(user))   # unknown keys, wrong values (S-6b)
        _parsed[str(f)] = hit
    return copy.deepcopy(hit[1]), list(hit[2])


class Config:
    """``cfg["build"]["retries"]``, plus the loop's paths."""

    def __init__(self, root: str | Path | None = None, overrides: dict | None = None):
        self.home = home(root)
        self.layout = paths.LoopLayout(self.home)
        f = self.layout.settings
        data, self.problems = _settings(f)
        self.data = _merge(data, overrides or {}) if overrides else data
        from .schema import describe
        if self.problems:
            _say_once(f, describe(self.problems))
        if os.environ.get(KRANTO_URL_ENV):
            self.data["kranto"]["url"] = os.environ[KRANTO_URL_ENV]

    def __getitem__(self, k):
        return self.data[k]

    def get(self, k, default=None):
        return self.data.get(k, default)

    def path(self, value: str | None) -> Path | None:
        return Path(value).expanduser() if value else None

    @property
    def tasks_dir(self) -> Path:
        return self.path(self.data["tasks_dir"])

    @property
    def inbox(self) -> Path:
        return self.layout.inbox

    @property
    def pause_file(self) -> Path:
        return self.layout.pause

    @property
    def stop_file(self) -> Path:
        return self.layout.stop

    @property
    def db(self) -> Path:
        return self.layout.db

    def ensure(self) -> Config:
        (self.layout.inbox / "done").mkdir(parents=True, exist_ok=True)
        return self

    def paused(self) -> bool:
        return self.pause_file.exists()
