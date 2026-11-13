"""``kranto archive``: the owner's record of the features that left Kranto.

Writes ``<home>/archive/`` (or ``--out``): one JSON file per group and ``index.html``, one
self-contained page that lists them. Builds and projects come from the loop's ``loop.db``;
Invest, the trend radar, the deep dives and the browser extension from Kranto's own database.
Every source is opened read-only (``mode=ro``): the archive never changes a table, and no table
or file is ever dropped (the tables stay, empty on a fresh install). Run it again at any time;
it writes the files anew from what the databases hold then.

Each JSON file holds ``counts`` (every table's rows, as the database counts them) and the rows
themselves, so the record is whole even where the page shows only a summary.
"""

from __future__ import annotations

import html
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Kranto's own database: the tables of each feature that left, by prefix (the last row)
# (migration 30's frozen tables of the same features are left out: migration 31 copied their rows
# into the cubs' tables, which stay in Kranto and its backups)
GROUPS: dict[str, tuple[str, tuple[str, ...]]] = {
    "invest": ("Invest", ("invest_",)),
    "radar": ("The trend radar", ("radar_",)),
    "deepdives": ("Deep dives", ("deep_dive",)),
    "extension": ("The browser extension", ("browser_",)),
}
# the loop's database: builds (an idea with its history and spend) and projects
LOOP_TABLES = ("ideas", "history", "spend", "projects", "charter_versions", "changes")


@dataclass
class Written:
    """What one run wrote: the folder, each file's counts, and what it could not read."""
    out: Path
    counts: dict[str, dict[str, int]] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {"out": str(self.out), "counts": self.counts, "missing": self.missing}


def _ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _value(v: Any) -> Any:
    """A stored value as JSON: text that holds a JSON object or list is read as one."""
    if isinstance(v, bytes):
        return None                            # no blob belongs in a record a person reads
    if isinstance(v, str) and v[:1] in "{[":
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def _rows(con: sqlite3.Connection, table: str, order: str = "rowid") -> list[dict[str, Any]]:
    return [{k: _value(r[k]) for k in r.keys()}  # noqa: SIM118 - a Row iterates its values
            for r in con.execute(f'SELECT * FROM "{table}" ORDER BY {order}')]


def _tables(con: sqlite3.Connection) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]


def _count(con: sqlite3.Connection, table: str) -> int:
    return int(con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def _ts(v: Any) -> str | None:
    """The loop's times are epoch seconds; the record shows them as UTC text too."""
    if isinstance(v, int | float):
        return datetime.fromtimestamp(v, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return v if isinstance(v, str) else None


def _repo(idea: dict[str, Any]) -> tuple[str | None, str | None]:
    """A build's repository (``owner/name``) and its address, from what publish stored."""
    pub = idea.get("publish")
    if not isinstance(pub, dict):
        return None, None
    repo = pub.get("repo")
    url = pub.get("url") or (f"https://github.com/{repo}" if repo else None)
    return (repo if isinstance(repo, str) else None), (url if isinstance(url, str) else None)


def loop_records(loop_db: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Builds and projects from ``loop.db``, read-only; empty when there is no loop."""
    empty_b = {"title": "Builds", "source": str(loop_db), "counts": {}, "builds": []}
    empty_p = {"title": "Projects", "source": str(loop_db), "counts": {}, "projects": []}
    if not loop_db.is_file():
        return empty_b, empty_p
    con = _ro(loop_db)
    try:
        have = set(_tables(con))
        counts = {t: _count(con, t) for t in LOOP_TABLES if t in have}
        history = _rows(con, "history", "id") if "history" in have else []
        spend = _rows(con, "spend", "id") if "spend" in have else []
        builds = []
        for idea in (_rows(con, "ideas", "created") if "ideas" in have else []):
            repo, url = _repo(idea)
            mine_s = [s for s in spend if s.get("idea") == idea["id"]]
            builds.append({
                "id": idea["id"], "title": idea.get("title") or "", "state": idea.get("state"),
                "kind": idea.get("kind"), "repo": repo, "url": url,
                "task_dir": idea.get("task_dir"), "created": _ts(idea.get("created")),
                "updated": _ts(idea.get("updated")),
                "spend_usd": round(sum(float(s.get("usd") or 0) for s in mine_s), 4),
                "idea": idea,
                "history": [h for h in history if h.get("idea") == idea["id"]],
                "spend": mine_s,
            })
        charters = _rows(con, "charter_versions", "project, v") \
            if "charter_versions" in have else []
        changes = _rows(con, "changes", "created") if "changes" in have else []
        projects = []
        for p in (_rows(con, "projects", "created") if "projects" in have else []):
            repos = p.get("repos") if isinstance(p.get("repos"), list) else []
            projects.append({
                "id": p["id"], "name": p.get("name") or "", "kind": p.get("kind"),
                "state": p.get("state"), "repos": repos, "created": _ts(p.get("created")),
                "project": p,
                "charters": [c for c in charters if c.get("project") == p["id"]],
                "changes": [c for c in changes if c.get("project") == p["id"]],
            })
        spare = [s for s in spend if not any(s.get("idea") == b["id"] for b in builds)]
    finally:
        con.close()
    return ({**empty_b, "counts": {t: counts[t] for t in ("ideas", "history", "spend")
                                   if t in counts},
             "builds": builds, "spend_without_build": spare},
            {**empty_p, "counts": {t: counts[t] for t in ("projects", "charter_versions",
                                                          "changes") if t in counts},
             "projects": projects})


def library_records(db: Path) -> dict[str, dict[str, Any]]:
    """Each group of Kranto's own retired tables, every row, read-only."""
    out: dict[str, dict[str, Any]] = {}
    con = _ro(db) if db.is_file() else None
    try:
        names = _tables(con) if con is not None else []
        for key, (title, prefixes) in GROUPS.items():
            tables = [n for n in names if n.startswith(prefixes)]
            assert con is not None or not tables
            out[key] = {"title": title, "source": str(db),
                        "counts": {t: _count(con, t) for t in tables} if con else {},
                        "tables": {t: _rows(con, t) for t in tables} if con else {}}
    finally:
        if con is not None:
            con.close()
    return out


def write(home: Path, db: Path, loop_db: Path, out: Path | None = None) -> Written:
    """Write the archive's files under ``out`` (default ``<home>/archive``); returns counts."""
    out = out or home / "archive"
    out.mkdir(parents=True, exist_ok=True)
    done = Written(out)
    builds, projects = loop_records(loop_db)
    if not loop_db.is_file():
        done.missing.append(f"no loop database at {loop_db}: no builds or projects")
    if not db.is_file():
        done.missing.append(f"no library at {db}")
    files: dict[str, dict[str, Any]] = {"builds": builds, "projects": projects,
                                        **library_records(db)}
    made = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    for name, rec in files.items():
        rec = {"made_at": made, **rec}
        tmp = out / f".{name}.json.tmp"
        tmp.write_text(json.dumps(rec, indent=1, ensure_ascii=False, default=str) + "\n",
                       encoding="utf-8")
        tmp.replace(out / f"{name}.json")
        done.counts[name] = dict(rec["counts"])
    page = out / ".index.html.tmp"
    page.write_text(render(files, made), encoding="utf-8")
    page.replace(out / "index.html")
    return done


# -- the page ------------------------------------------------------------------------------------

CSS = """body{font:15px/1.5 system-ui,sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem;
color:#222;background:#fdfcf9}h1{font-size:1.5rem}h2{font-size:1.15rem;margin-top:2rem}
table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:.25rem .5rem;
border-bottom:1px solid #e6e2da;vertical-align:top}th{font-weight:600}.m{color:#777}
@media (prefers-color-scheme:dark){body{background:#1c1b19;color:#e8e6e1}td,th{border-color:#3a3833}
a{color:#9cc3ff}.m{color:#9a968e}}"""


def _e(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def _link(url: str | None, text: str | None) -> str:
    if not url or not url.startswith("https://"):
        return _e(text or "–")
    return f'<a href="{_e(url)}">{_e(text or url)}</a>'


def _counts_line(counts: dict[str, int]) -> str:
    return ", ".join(f"{_e(t)} {n}" for t, n in counts.items()) or "no tables"


def render(files: dict[str, dict[str, Any]], made: str) -> str:
    b, p = files["builds"], files["projects"]
    parts = [f"<!doctype html><meta charset=utf-8><title>Kranto: the archive</title>"
             f"<meta name=viewport content='width=device-width,initial-scale=1'>"
             f"<style>{CSS}</style><h1>Kranto: the archive</h1>"
             f"<p class=m>What the features that left Kranto kept, made {made}. Every table is "
             "still in its database, untouched; each JSON file beside this page holds all "
             "of its rows.</p>"]
    parts.append(f"<h2>Builds ({len(b['builds'])})</h2><p class=m>{_counts_line(b['counts'])}"
                 " · builds.json</p><table><tr><th>Build</th><th>State</th><th>Repository</th>"
                 "<th>Started</th><th>Spend</th></tr>")
    for x in b["builds"]:
        parts.append(f"<tr><td>{_e(x['title'] or x['id'])}</td><td>{_e(x['state'])}</td>"
                     f"<td>{_link(x['url'], x['repo'])}</td><td>{_e((x['created'] or '')[:10])}"
                     f"</td><td>${x['spend_usd']:.2f}</td></tr>")
    parts.append("</table>")
    parts.append(f"<h2>Projects ({len(p['projects'])})</h2><p class=m>"
                 f"{_counts_line(p['counts'])} · projects.json</p><table><tr><th>Project</th>"
                 "<th>Repositories</th><th>Charters</th><th>Changes</th></tr>")
    for x in p["projects"]:
        repos = ", ".join(_link(r.get("url"), r.get("repo")) for r in x["repos"]
                          if isinstance(r, dict)) or "–"
        parts.append(f"<tr><td>{_e(x['name'])}</td><td>{repos}</td>"
                     f"<td>{len(x['charters'])}</td><td>{len(x['changes'])}</td></tr>")
    parts.append("</table>")
    inv = files["invest"]["tables"]
    cards = inv.get("invest_cards") or []
    parts.append(f"<h2>Invest ({len(cards)} cards)</h2><p class=m>"
                 f"{_counts_line(files['invest']['counts'])} · invest.json</p>")
    if cards:
        parts.append("<table><tr><th>Card</th><th>Kind</th><th>State</th><th>Made</th>"
                     "</tr>")
        for c in cards:
            thesis = c.get("thesis") if isinstance(c.get("thesis"), dict) else {}
            ask = c.get("ask") if isinstance(c.get("ask"), dict) else {}
            title = thesis.get("instrument_name") or thesis.get("title") \
                or ask.get("trend") or c.get("instrument") or f"#{c.get('id')}"
            parts.append(f"<tr><td>{_e(title)}</td><td>{_e(c.get('kind'))}</td>"
                         f"<td>{_e(c.get('state'))}</td>"
                         f"<td>{_e(str(c.get('created_at') or '')[:10])}</td></tr>")
        parts.append("</table>")
    rad = files["radar"]["tables"]
    trends, props = rad.get("radar_trends") or [], rad.get("radar_proposals") or []
    parts.append(f"<h2>The trend radar ({len(trends)} trends, {len(props)} proposals)</h2>"
                 f"<p class=m>{_counts_line(files['radar']['counts'])} · radar.json</p>")
    if trends:
        parts.append("<table><tr><th>Trend</th><th>Kind</th><th>State</th></tr>")
        for t in trends:
            parts.append(f"<tr><td>{_e(t.get('title'))}</td><td>{_e(t.get('kind'))}</td>"
                         f"<td>{_e(t.get('state'))}</td></tr>")
        parts.append("</table>")
    for key in ("deepdives", "extension"):
        rec = files[key]
        rows = sum(rec["counts"].values())
        parts.append(f"<h2>{_e(rec['title'])} ({rows} rows)</h2><p class=m>"
                     f"{_counts_line(rec['counts'])} · {key}.json</p>")
    return "\n".join(parts) + "\n"
