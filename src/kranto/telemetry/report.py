"""The daily report (sections 1.3, 1.4): one day's local lines folded into counts and
percentiles, with the facts the app already keeps (topics, sources, the watcher's day, update
results), the milestones reached so far, and the resource that says what kind of install sent
it. The report has no identifier and no time finer than its day; ``schema.check_report``
refuses anything else.

Milestones are set once and then stay true (``state.json``), from facts the app has, so no
code path has to remember to set them."""

from __future__ import annotations

import json
import os
import platform
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .. import __version__
from . import local
from . import schema as schema_mod

# Latency buckets (ms, upper edges) of the server's timing lines; the last bucket is open.
BUCKETS_MS = (5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)
OPEN_BUCKET_MS = 30000
MAX_FINGERPRINTS = 20
CAP = 999


def percentile(values: list[float], q: float) -> int | None:
    """Nearest rank."""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    k = max(0, min(len(vals) - 1, int(round(q / 100 * len(vals) + 0.5)) - 1))
    return int(round(vals[k]))


def hist_percentile(hist: list[int], q: float) -> int | None:
    total = sum(hist)
    if not total:
        return None
    need, seen = q / 100 * total, 0
    for i, n in enumerate(hist):
        seen += n
        if seen >= need:
            return BUCKETS_MS[i] if i < len(BUCKETS_MS) else OPEN_BUCKET_MS
    return OPEN_BUCKET_MS


def bucket(ms: float) -> int:
    for i, edge in enumerate(BUCKETS_MS):
        if ms <= edge:
            return i
    return len(BUCKETS_MS)


# -- the resource ----------------------------------------------------------------------------

def _distro() -> str:
    if sys.platform == "darwin":
        return "macos"
    try:
        text = Path("/etc/os-release").read_text()
    except OSError:
        return "other"
    ids = []
    for line in text.splitlines():
        k, _, v = line.partition("=")
        if k in ("ID", "ID_LIKE"):
            ids += v.strip().strip('"').lower().split()
    for name, family in (("debian", "debian"), ("ubuntu", "debian"), ("fedora", "fedora"),
                         ("rhel", "fedora"), ("centos", "fedora"), ("arch", "arch"),
                         ("suse", "suse"), ("opensuse", "suse"), ("alpine", "alpine"),
                         ("nixos", "nixos")):
        if name in ids:
            return family
    return "other"


# The relay keeps its own copy of the list and learns ``-devN`` and ``nightly`` only when the
# owner redeploys it (ops/telemetry/README.md); a value outside its copy refuses the whole
# report. Until then a nightly build is sent as a build from git is (X.Y.Z, channel main) and
# the nightly channel by its old name, rc, so no report is refused. True after the redeploy.
RELAY_KNOWS_NIGHTLY = False


def version_of(raw: str) -> tuple[str, bool]:
    """The version as the list allows it, and whether it is sent as a build from git: a
    release's own (0.5.25; an rc's Python form 0.5.25rc1 written as its tag, 0.5.25-rc1; a
    nightly build's wheel 0.7.0.dev12 as its tag, 0.7.0-dev12, once the relay knows the form),
    else X.Y.Z and true (a build from git, 0.5.28.dev3+g1a2b3c4). An rc's version once failed
    the list, so every page reading the report answered 500 on every rc."""
    public = raw.split("+")[0]
    base = re.sub(r"\.dev(\d+)$", r"-dev\1", re.sub(r"rc(\d+)$", r"-rc\1", public))
    from_git = ".dev" in public and public != raw          # 0.5.28.dev3+g1a2b3c4
    if not from_git and (RELAY_KNOWS_NIGHTLY or "-dev" not in base) and \
            schema_mod.value_ok({"type": "str", "pattern": "version"}, base, schema_mod.union()):
        return base, False
    m = re.match(r"\d{1,3}\.\d{1,3}\.\d{1,4}", raw)
    return (m.group(0) if m else "0.0.0"), True


def channel_of(base: str, git: bool, chosen: str) -> str:
    """The channel a report says: ``main`` for a build from git, ``nightly`` for a nightly
    build (or an old rc), else the one chosen in Settings; ``nightly`` is sent as ``rc`` until
    the relay knows the word."""
    channel = "main" if git else "nightly" if ("-dev" in base or "-rc" in base) else chosen
    return "rc" if channel == "nightly" and not RELAY_KNOWS_NIGHTLY else channel


def resource(home: Path, tier: str, environ=None) -> dict:
    env = environ if environ is not None else os.environ
    from ..update.check import settings as update_settings

    base, dev = version_of(__version__)
    system = platform.system().lower()
    machine = platform.machine().lower()
    py = f"{sys.version_info.major}.{sys.version_info.minor}"
    out = {
        "schema": 1, "tier": tier, "version": base,
        "channel": channel_of(base, dev, update_settings(home).channel),
        "os": system if system in ("linux", "darwin", "windows") else "other",
        "distro": _distro(),
        "arch": {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "arm64",
                 "arm64": "arm64"}.get(machine, "other"),
        "python": py if py in ("3.12", "3.13", "3.14") else "other",
        "run_mode": "systemd" if env.get("INVOCATION_ID") else
                    "docker" if Path("/.dockerenv").exists() else "foreground",
    }
    if tier == "detailed":
        out["install_id"] = install_id(home)
    return out


def install_id(home: Path, now: datetime | None = None) -> str:
    """The detailed tier's random id, made on first use and replaced after 180 days."""
    import uuid

    now = now or datetime.now(UTC)
    st = local.read_state(home)
    made = st.get("install_id_made")
    try:
        old = made and now - datetime.fromisoformat(made) > timedelta(days=180)
    except ValueError:
        old = True
    if not st.get("install_id") or old:
        st["install_id"] = str(uuid.uuid4())
        st["install_id_made"] = now.isoformat(timespec="seconds")
        local.write_state(home, st)
    return st["install_id"]


# -- the fold --------------------------------------------------------------------------------

def _model(name: str | None) -> str:
    n = (name or "").split("/")[-1].replace(".", "-")
    if n.startswith("claude-haiku-4-5"):
        n = "claude-haiku-4-5"
    return n if n in schema_mod.union()["enums"]["model"] else "other"


def fold_lines(lines: list[dict]) -> dict:
    """Counts and percentiles from one day's lines."""
    out: dict = {}
    dropped = 0

    def add(key, n=1):
        out[key] = out.get(key, 0) + n

    views_ms: list = []
    hist = [0] * (len(BUCKETS_MS) + 1)
    errors: dict[str, int] = {}
    for ln in lines:
        dropped += int(ln.get("_dropped") or 0)
        e = ln.get("e")
        if e == "dropped":
            dropped += 0 if ln.get("_dropped") else 1
        elif e == "action":
            add(f"actions.{ln['kind']}")
            if ln.get("origin"):
                add(f"actions_by_origin.{ln['origin']}")
            if ln.get("outcome") not in (None, "ok"):
                add("actions_refused")
        elif e == "view":
            add(f"pages.{ln['node']}")
            if ln.get("ms") is not None:
                views_ms.append(ln["ms"])
        elif e == "api":
            n4, n5 = int(ln.get("n4") or 0), int(ln.get("n5") or 0)
            add("api.requests", sum(int(ln.get(k) or 0) for k in ("n2", "n3")) + n4 + n5)
            add("api.errors_4xx", n4)
            add("api.errors_5xx", n5)
            if ln.get("slow"):
                add(f"api.slow.{ln['route']}", int(ln["slow"]))
            for i, n in enumerate((ln.get("h") or [])[:len(hist)]):
                hist[i] += int(n)
        elif e == "error":
            errors[ln["fingerprint"]] = errors.get(ln["fingerprint"], 0) + 1
        # any other line (a build's, kept before builds left Kranto) is read past: it stays in
        # the local file and counts in no report
    for i, (fp, n) in enumerate(sorted(errors.items(), key=lambda kv: (-kv[1], kv[0]))):
        if i < MAX_FINGERPRINTS:
            out[f"errors.{fp}"] = n
        else:
            add("errors.other", n)
    pairs = [("pages.load_ms_p50", percentile(views_ms, 50)),
             ("api.latency_ms_p50", hist_percentile(hist, 50)),
             ("api.latency_ms_p95", hist_percentile(hist, 95)),
             ("api.latency_ms_p99", hist_percentile(hist, 99))]
    out.update({k: v for k, v in pairs if v is not None})
    out["dropped_fields"] = dropped
    return out


def _day_bounds(day: str) -> tuple[str, str]:
    start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC)
    fmt = "%Y-%m-%dT%H:%M:%S"
    return start.strftime(fmt), (start + timedelta(days=1)).strftime(fmt)


def store_facts(store, cfg, day: str) -> dict:
    """What the watcher's own tables say about the install and the day."""
    from .. import library

    out: dict = {}
    if store is None:
        return out
    a, b = _day_bounds(day)
    topics = [t for t in library.active_topics(store) if t.kind == "user"]
    sources = library.list_sources(store)
    out["topics_count"] = min(len(topics), CAP)
    out["sources_count"] = min(len(sources), CAP)
    kinds = set(schema_mod.union()["enums"]["source_kind"])
    for s in sources:
        k = s.kind if s.kind in kinds else "other"
        key = f"watch.sources_by_kind.{k}"
        out[key] = min(out.get(key, 0) + 1, CAP)
    q = store.query_one
    out["watch.items_judged"] = q("SELECT COUNT(*) AS n FROM llm_calls WHERE purpose IN "
                                  "('judge', 'judge_gathered') AND created_at >= ? AND "
                                  "created_at < ?", (a, b))["n"]
    out["watch.items_kept"] = q("SELECT COUNT(*) AS n FROM observations WHERE created_at >= ? "
                                "AND created_at < ?", (a, b))["n"]
    out["watch.cards_written"] = q("SELECT COUNT(*) AS n FROM ideas WHERE status = 'shown' AND "
                                   "created_at >= ? AND created_at < ?", (a, b))["n"]
    usd = q("SELECT COALESCE(SUM(cost_usd), 0) AS s FROM llm_calls WHERE created_at >= ? AND "
            "created_at < ?", (a, b))["s"]
    out["watch.usd_cents"] = int(round(float(usd or 0) * 100))
    runs = store.query("SELECT status FROM runs WHERE kind = 'update' AND finished_at >= ? AND "
                       "finished_at < ?", (a, b))
    out["update.checked"] = sum(1 for r in runs if r["status"] == "ok")
    out["update.check_failed"] = sum(1 for r in runs if r["status"] != "ok")
    if cfg is not None:
        caps = [n for n, on in (("watch", cfg.budget.monthly_usd is not None),
                                ("deep_dive", cfg.deep_dive.enabled
                                 and cfg.deep_dive.daily_usd is not None)) if on]
        out["settings.caps_set"] = caps[0] if len(caps) == 1 else "several" if caps else "none"
        out["models.judge"] = _model(cfg.llm.models.get("judge"))
        out["models.reason"] = _model(cfg.llm.models.get("reason"))
        provider = cfg.llm.provider or ("openrouter" if "openrouter.ai" in cfg.llm.base_url
                                        else "openai_compat")
        out["provider"] = provider
        out["settings.auto_update_idle"] = cfg.update.auto == "idle"
    return out


def update_facts(home: Path, day: str) -> dict:
    from ..update.apply import history

    out: dict = {}
    for h in reversed(history(home, 50)):
        if not str(h.get("finished") or "").startswith(day):
            continue
        state = h.get("state")
        key = {"done": "update.applied", "rolled_back": "update.rolled_back",
               "failed": "update.failed"}.get(state)
        if key:
            out[key] = out.get(key, 0) + 1
        if h.get("warning"):
            out["update.stop_warning"] = out.get("update.stop_warning", 0) + 1
        frm = str(h.get("from") or "").lstrip("v")
        if state == "done" and schema_mod.value_ok({"type": "str", "pattern": "version"}, frm,
                                                   schema_mod.union()):
            out["update.from_version"] = frm
    return out


def page_facts(cfg) -> dict:
    """The page's own facts (the console's), when the page is on here. A fact the list no
    longer names (an older the page's ``projects_count``, its build milestones) is dropped and
    counted by ``allowed``, as any unknown key is."""
    if cfg is None or not cfg.brb.enabled:
        return {}
    try:
        from kranto.page.host_api import telemetry_facts

        from ..paths import loop_home
        facts = telemetry_facts(loop_home(cfg.brb.loop_home))
    except Exception:  # noqa: BLE001 - without the page's facts the report has the rest
        return {}
    return facts if isinstance(facts, dict) else {}


MILESTONE_FACTS = {"first_update": "update.applied"}


def milestones(home: Path, report: dict, store) -> dict:
    """The milestones reached, this day's facts added to those kept (and kept). A milestone
    kept before its name left the list (``first_build_ready``...) stays in ``state.json`` and
    is sent no more."""
    st = local.read_state(home)
    have = set(st.get("milestones") or ())
    for name, key in MILESTONE_FACTS.items():
        if report.get(key) or report.get(f"milestones.{name}") is True:   # or the page's facts
            have.add(name)
    if store is not None:
        from .. import setup

        if setup.is_done(store):
            have.add("setup_done")
        if report.get("topics_count"):
            have.add("first_topic")
        if report.get("sources_count"):
            have.add("first_source")
        if store.query_one("SELECT 1 AS x FROM ideas WHERE status = 'shown' LIMIT 1"):
            have.add("first_idea")
    names = schema_mod.union()["enums"]["milestone"]
    if sorted(have) != sorted(st.get("milestones") or ()):
        st["milestones"] = sorted(have)
        local.write_state(home, st)
    return {f"milestones.{n}": n in have for n in names}


def install_age_weeks(home: Path, store, day: str) -> int:
    first = None
    if store is not None:
        row = store.query_one("SELECT MIN(started_at) AS t FROM runs")
        first = row["t"] if row else None
    st = local.read_state(home)
    if not first:
        first = st.get("first_seen")
    if not first:
        st["first_seen"] = day
        local.write_state(home, st)
        first = day
    try:
        start = datetime.fromisoformat(str(first)[:10])
        weeks = (datetime.strptime(day, "%Y-%m-%d") - start).days // 7
    except ValueError:
        weeks = 0
    return max(0, min(52, weeks))


def allowed(rep: dict, schema: dict | None = None) -> dict:
    """The report's keys and values the list allows; the rest dropped and counted in
    ``dropped_fields``, as the list says. A line kept before an update that took its route or
    page out of the list (#325 retired /api/watches) once failed the whole day's report: the
    privacy page answered 500, so the update's self-check rolled a good release back."""
    schema = schema or schema_mod.union()
    out, n = {}, 0
    for k, v in rep.items():
        spec = schema_mod.report_spec(k, schema)
        if k != "day" and (spec is None or not schema_mod.value_ok(spec, v, schema)):
            n += 1
            continue
        out[k] = v
    if n:
        out["dropped_fields"] = min(int(out.get("dropped_fields") or 0) + n, 100_000_000)
    return out


def build(home: Path, day: str, *, store=None, cfg=None, tier: str = "basic",
          environ=None) -> dict:
    """``{"resource", "report"}`` for ``day``, checked against the list (``SchemaError``
    when it is not)."""
    rep = fold_lines(local.lines(home, day))
    rep.update(store_facts(store, cfg, day))
    rep.update(update_facts(home, day))
    rep.update(page_facts(cfg))
    rep.update(milestones(home, rep, store))
    rep["day"] = day
    rep["install_age_weeks"] = install_age_weeks(home, store, day)
    rep["sample_rate"] = 100
    rep = allowed({k: rep[k] for k in sorted(rep)})
    res = resource(home, tier, environ)
    schema_mod.check_resource(res)
    schema_mod.check_report(rep)
    payload = {"resource": res, "report": rep}
    if scrubbed(payload):
        raise schema_mod.SchemaError("a value matched a personal-data pattern")
    return payload


_UUID4 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")


def scrubbed(payload: dict) -> int:
    """How many replacements ``scrub`` would make in the payload's strings (the second net,
     4.3): 0 in a correct build, since the allow-list lets no free text through."""
    from collections import Counter

    from ..scrub import scrub

    counts: Counter = Counter()
    for part in payload.values():
        for k, v in part.items():
            if k == "install_id" and isinstance(v, str) and _UUID4.fullmatch(v):
                # Kranto's own random id, checked as a uuid4 by the list: about 1 in 250 has
                # digit groups the phone pattern reads ("9741-4438-8093"), and that install's
                # every daily report was refused, for as long as it kept the id
                v = ""
            for s in (k, v) if isinstance(v, str) else (k,):
                scrub(s, counts)
    return sum(counts.values())


def pretty(payload: dict) -> str:
    return json.dumps(payload, indent=1, sort_keys=True)
