"""A widget's contract: what a widget's read answers for each of the six kinds,
and the caps Kranto draws it under. One function, ``clean``, serves Kranto (``GET /api/home``
checks every answer with it before the page draws anything), ``FakeHost.widget()`` and
``python -m bears_cub.standard`` (which refuse what Kranto would drop), so a cub whose tests pass
draws on the home as its tests saw it.

``clean(kind, size, answer, cub=…)`` returns the answer as Kranto draws it (rows past the size's
count dropped, long strings cut with an ellipsis, a link that leaves the cub's own page dropped,
a markdown link to anywhere else drawn as its words) and the list of what it changed, in words.
A wrong shape (a missing key, a list where a mapping goes, a kind's required part absent) raises
``WidgetAnswerError``: Kranto draws that widget's error state and every other widget as usual.
Every string is drawn as text by the page; nothing in an answer is ever markup.

Standard library only.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

KINDS = ("stat", "rows", "series", "table", "stages", "note")
SIZES = ("S", "M", "L")
EVERY_MIN_S = 60                 # the floor for every trust (HOME D5)
EVERY_MAX_S = 86400
PER_CUB = 4                      # widgets a cub may declare (HOME D9)
ANSWER_BYTES = 64 * 1024
TONES = ("new", "wait", "quiet", "good", "bad")
DELTA_TONES = ("up", "down", "flat")
COLUMN_KINDS = ("text", "number", "money", "date", "delta")
ROWS_ANSWERED = 20
ROWS_SHOWN = {"S": 3, "M": 5, "L": 8}
TABLE_ROWS = {"S": 3, "M": 6, "L": 10}
STAGE_ITEMS = {"S": 3, "M": 4, "L": 8}
SERIES_MAX, POINTS_MAX, FACTS_MAX, COLUMNS_MAX, STEPS_MAX = 3, 52, 3, 5, 8
NOTE_CHARS = 1000
ELLIPSIS = "…"
# a link the page may follow: a route under Kranto's own page (``cub/<id>`` for a cub)
ROUTE = re.compile(r"[a-z][a-z0-9_/-]{0,80}(\?[A-Za-z0-9_=&.%-]{0,200})?")
_MD_LINK = re.compile(r"(!?)\[([^\]\n]{0,200})\]\(([^)\s]{0,400})\)")
_AUTOLINK = re.compile(r"<(https?://[^>\s]{1,400})>")
_TAG = re.compile(r"</?[A-Za-z][^>\n]{0,200}>|<!--")
_HEADING = re.compile(r"^(#{1,2})(?=\s)", re.M)


class WidgetAnswerError(ValueError):
    """An answer Kranto cannot draw as its kind: the widget shows its error state."""


class _Clean:
    def __init__(self, cub: str, hosts: tuple[str, ...], first_party: bool) -> None:
        self.cub, self.hosts, self.first_party = cub, tuple(hosts), first_party
        self.changes: list[str] = []

    # -- the parts ------------------------------------------------------------------------------

    def text(self, where: str, v, cap: int, *, required: bool = False) -> str | None:
        if v is None:
            if required:
                raise WidgetAnswerError(f"{where} is missing")
            return None
        if isinstance(v, bool) or not isinstance(v, str | int | float):
            raise WidgetAnswerError(f"{where} must be text")
        s = v if isinstance(v, str) else _num(v)
        if required and not s.strip():
            raise WidgetAnswerError(f"{where} is empty")
        if len(s) > cap:
            self.changes.append(f"{where} cut to {cap} characters")
            s = s[: cap - 1] + ELLIPSIS
        return s

    def number(self, where: str, v) -> float | int:
        if isinstance(v, bool) or not isinstance(v, int | float) or v != v:
            raise WidgetAnswerError(f"{where} must be a number")
        return v

    def when(self, where: str, v) -> str | None:
        if v is None:
            return None
        try:
            datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except ValueError:
            self.changes.append(f"{where} is not an ISO time: left out")
            return None
        return str(v)[:40]

    def link(self, where: str, v) -> str | None:
        """A row's ``open``: a route under the cub's own page, else dropped (the row draws
        without a link). A first-party feature may open any of Kranto's routes."""
        if v is None:
            return None
        if not isinstance(v, str):
            self.changes.append(f"{where} is not a route: dropped")
            return None
        route = v.removeprefix("#/")
        mine = route == f"cub/{self.cub}" or route.startswith((f"cub/{self.cub}?",
                                                               f"cub/{self.cub}/"))
        if not ROUTE.fullmatch(route) or not (mine or self.first_party) or ".." in route:
            self.changes.append(f"{where} leaves {self.cub}'s page: dropped")
            return None
        return route

    def listing(self, where: str, v, cap: int, *, required: bool = True, at_least: int = 0
                ) -> list:
        if v is None and not required:
            return []
        if not isinstance(v, list):
            raise WidgetAnswerError(f"{where} must be a list")
        if len(v) < at_least:
            raise WidgetAnswerError(f"{where} needs at least {at_least}")
        if len(v) > cap:
            self.changes.append(f"{where}: {len(v)} answered, {cap} drawn")
            v = v[:cap]
        return v

    def mapping(self, where: str, v) -> dict:
        if not isinstance(v, dict):
            raise WidgetAnswerError(f"{where} must be a mapping")
        return v

    def markdown(self, where: str, v) -> str:
        s = self.text(where, v, NOTE_CHARS, required=True) or ""
        if _TAG.search(s):
            self.changes.append(f"{where} holds HTML: drawn as text")

        def sub(m: re.Match) -> str:
            image, words, target = m.group(1), m.group(2), m.group(3)
            if image:
                self.changes.append(f"{where}: an image is drawn as its words")
                return words
            if self._target_ok(target):
                return m.group(0)
            self.changes.append(f"{where}: a link to {target[:60]} is drawn as its words")
            return words

        s = _MD_LINK.sub(sub, s)
        s = _AUTOLINK.sub(lambda m: m.group(0) if self._target_ok(m.group(1)) else m.group(1), s)
        if _HEADING.search(s):
            self.changes.append(f"{where}: headings over h3 drawn as h3")
            s = _HEADING.sub("###", s)
        return s

    def _target_ok(self, target: str) -> bool:
        if target.startswith("#/"):
            return self.link("note", target) is not None
        m = re.fullmatch(r"https://([a-z0-9.-]+)(/\S*)?", target)
        return bool(m) and any(m.group(1) == h or m.group(1).endswith("." + h)
                               for h in self.hosts)

    # -- the kinds ------------------------------------------------------------------------------

    def stat(self, a: dict, size: str) -> dict:
        out = {"value": self.text("value", a.get("value"), 16, required=True),
               "words": self.text("words", a.get("words"), 40, required=True)}
        if a.get("delta") is not None:
            d = self.mapping("delta", a["delta"])
            tone = d.get("tone", "flat")
            if tone not in DELTA_TONES:
                raise WidgetAnswerError(f"delta.tone is one of {', '.join(DELTA_TONES)}")
            out["delta"] = {"value": self.text("delta.value", d.get("value"), 16, required=True),
                            "words": self.text("delta.words", d.get("words"), 40) or "",
                            "tone": tone}
        facts = []
        for i, f in enumerate(self.listing("facts", a.get("facts"), FACTS_MAX, required=False)):
            f = self.mapping(f"facts[{i}]", f)
            facts.append({"label": self.text(f"facts[{i}].label", f.get("label"), 24,
                                             required=True),
                          "value": self.text(f"facts[{i}].value", f.get("value"), 40,
                                             required=True)})
        if facts:
            out["facts"] = facts
        line = self.text("line", a.get("line"), 120)
        if line:
            out["line"] = line
        return out

    def rows(self, a: dict, size: str) -> dict:
        given = self.listing("rows", a.get("rows"), ROWS_ANSWERED)
        rows = []
        for i, r in enumerate(given[: ROWS_SHOWN[size]]):
            r = self.mapping(f"rows[{i}]", r)
            tone = r.get("tone")
            if tone is not None and tone not in TONES:
                self.changes.append(f"rows[{i}].tone {str(tone)[:20]!r} is not a tone: quiet")
                tone = "quiet"
            row = {"id": self.text(f"rows[{i}].id", r.get("id"), 80, required=True),
                   "title": self.text(f"rows[{i}].title", r.get("title"), 120, required=True)}
            for k, cap in (("meta", 160), ("tag", 24)):
                v = self.text(f"rows[{i}].{k}", r.get(k), cap)
                if v:
                    row[k] = v
            if tone:
                row["tone"] = tone
            at = self.when(f"rows[{i}].at", r.get("at"))
            if at:
                row["at"] = at
            link = self.link(f"rows[{i}].open", r.get("open"))
            if link:
                row["open"] = link
            rows.append(row)
        return {"rows": rows, "total": len(given), **self._note(a)}

    def _note(self, a: dict) -> dict:
        """The line under a rows, table or stages widget ("Not financial advice.")."""
        note = self.text("note", a.get("note"), 200)
        return {"note": note} if note else {}

    def series(self, a: dict, size: str) -> dict:
        out_series = []
        for i, s in enumerate(self.listing("series", a.get("series"), SERIES_MAX, at_least=1)):
            s = self.mapping(f"series[{i}]", s)
            pts = []
            for j, p in enumerate(self.listing(f"series[{i}].points", s.get("points"),
                                               POINTS_MAX)):
                if not isinstance(p, list) or len(p) != 2:
                    raise WidgetAnswerError(f"series[{i}].points[{j}] is [x, y]")
                x = p[0] if isinstance(p[0], str) else self.number(f"series[{i}].points[{j}]",
                                                                   p[0])
                pts.append([x[:40] if isinstance(x, str) else x,
                            self.number(f"series[{i}].points[{j}]", p[1])])
            one = {"label": self.text(f"series[{i}].label", s.get("label"), 40,
                                      required=True), "points": pts}
            unit = self.text(f"series[{i}].unit", s.get("unit"), 12)
            if unit:
                one["unit"] = unit
            out_series.append(one)
        out: dict = {"series": out_series}
        for k, cap in (("value", 16), ("words", 40)):
            v = self.text(k, a.get(k), cap)
            if v:
                out[k] = v
        return out

    def table(self, a: dict, size: str) -> dict:
        cols = []
        for i, c in enumerate(self.listing("columns", a.get("columns"), COLUMNS_MAX,
                                           at_least=1)):
            c = self.mapping(f"columns[{i}]", c)
            kind = c.get("kind", "text")
            if kind not in COLUMN_KINDS:
                raise WidgetAnswerError(f"columns[{i}].kind is one of {', '.join(COLUMN_KINDS)}")
            cols.append({"key": self.text(f"columns[{i}].key", c.get("key"), 40, required=True),
                         "label": self.text(f"columns[{i}].label", c.get("label"), 24,
                                            required=True), "kind": kind})
        given = self.listing("rows", a.get("rows"), ROWS_ANSWERED)
        rows = []
        for i, r in enumerate(given[: TABLE_ROWS[size]]):
            r = self.mapping(f"rows[{i}]", r)
            row: dict = {}
            for c in cols:
                v = r.get(c["key"])
                if v is None:
                    row[c["key"]] = None
                elif c["kind"] in ("number", "money", "delta") and not isinstance(v, str):
                    row[c["key"]] = self.number(f"rows[{i}].{c['key']}", v)
                else:
                    row[c["key"]] = self.text(f"rows[{i}].{c['key']}", v, 80)
            link = self.link(f"rows[{i}].open", r.get("open"))
            if link:
                row["open"] = link
            rows.append(row)
        return {"columns": cols, "rows": rows, "total": len(given), **self._note(a)}

    def stages(self, a: dict, size: str) -> dict:
        steps = []
        for i, s in enumerate(self.listing("steps", a.get("steps"), STEPS_MAX, at_least=2)):
            s = self.mapping(f"steps[{i}]", s)
            steps.append({"key": self.text(f"steps[{i}].key", s.get("key"), 40, required=True),
                          "word": self.text(f"steps[{i}].word", s.get("word"), 24,
                                            required=True)})
        keys = {s["key"] for s in steps}
        given = self.listing("items", a.get("items"), ROWS_ANSWERED)
        items = []
        for i, it in enumerate(given[: STAGE_ITEMS[size]]):
            it = self.mapping(f"items[{i}]", it)
            step = it.get("step")
            if step is not None and step not in keys:
                self.changes.append(f"items[{i}].step is not one of the steps: drawn without one")
                step = None
            item = {"id": self.text(f"items[{i}].id", it.get("id"), 80, required=True),
                    "title": self.text(f"items[{i}].title", it.get("title"), 120, required=True),
                    "step": step}
            for k, cap in (("since", 40), ("meta", 160)):
                v = self.text(f"items[{i}].{k}", it.get(k), cap)
                if v:
                    item[k] = v
            if it.get("change") is not None:
                ch = self.mapping(f"items[{i}].change", it["change"])
                frm, to = ch.get("from"), ch.get("to")
                if frm in keys and to in keys:
                    item["change"] = {"from": frm, "to": to,
                                      "at": self.when(f"items[{i}].change.at", ch.get("at"))}
                else:
                    self.changes.append(f"items[{i}].change names a step it does not have")
            link = self.link(f"items[{i}].open", it.get("open"))
            if link:
                item["open"] = link
            items.append(item)
        return {"steps": steps, "items": items, "total": len(given), **self._note(a)}

    def note(self, a: dict, size: str) -> dict:
        return {"markdown": self.markdown("markdown", a.get("markdown"))}


def _num(v: int | float) -> str:
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return f"{v:,}" if isinstance(v, int) else f"{v:,.4g}"


def clean(kind: str, size: str, answer, *, cub: str, hosts: tuple[str, ...] = (),
          first_party: bool = False) -> tuple[dict, list[str]]:
    """The answer as Kranto draws it, and what was changed to draw it (in words). Raises
    ``WidgetAnswerError`` for an answer that is not its kind's shape."""
    if kind not in KINDS:
        raise WidgetAnswerError(f"no widget kind {kind}")
    if size not in SIZES:
        raise WidgetAnswerError(f"no size {size}")
    if not isinstance(answer, dict):
        raise WidgetAnswerError("the answer must be a mapping")
    try:
        n = len(json.dumps(answer, default=str))
    except (TypeError, ValueError):
        raise WidgetAnswerError("the answer is not JSON") from None
    if n > ANSWER_BYTES:
        raise WidgetAnswerError(f"the answer is over {ANSWER_BYTES // 1024} KiB")
    c = _Clean(cub, hosts, first_party)
    out = getattr(c, kind)(answer, size)
    as_of = c.when("as_of", answer.get("as_of"))
    if as_of:
        out["as_of"] = as_of
    return out, c.changes


def describe(w: dict) -> str:
    """A declared widget in words, for the install dialog and ``kranto cub check``: "Trends I
    follow (stages, M or L, from its read widget_trends, every 5 minutes)"."""
    sizes = list(w.get("sizes") or ["M"])
    said = sizes[0] if len(sizes) == 1 else ", ".join(sizes[:-1]) + " or " + sizes[-1]
    s = int(w.get("every_s") or 300)
    every = (f"every {s // 3600} hour{'s' if s // 3600 != 1 else ''}" if s % 3600 == 0
             else f"every {s // 60} minute{'s' if s // 60 != 1 else ''}" if s % 60 == 0
             else f"every {s} seconds")
    return f"{w.get('title')} ({w.get('kind')}, {said}, from its read {w.get('read')}, {every})"
