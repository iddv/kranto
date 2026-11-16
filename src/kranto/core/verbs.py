"""The verb registry: every write a person can make, once.

A **verb** is one press on a page, said once: its kind (``topic.add``), the button's word, the
plain words a tooltip and a tool description use, its typed fields, its **ladder kind** (what
sort of change it is: ``read``, ``reversible``, ``spend``, ``outward``, ``destructive``,
``credential``), the doors that may run it, the route that performs it and the page
its subject shows on afterwards. The page keeps pressing its routes as it always has (the route
is the verb's ``ui`` door); everyone else runs a verb by its kind through ``POST
/api/verbs/<kind>`` (``web/verbs_api.py``), which calls the same route, so a verb cannot do on
one surface what it does not do on another.

**Who may run what** is decided by the caller's token, never by a request's body
(``web/auth.py``), in one order: the door (``doors``), then the ladder, then the confirm class,
then the route. The ladder applies to every caller that is not the owner pressing
(``ui``, ``cli``): your own assistant over ``kranto mcp`` (``mcp``), the console in Kranto
(``console``), a named agent (``agent``). For each ladder kind the owner picks **Do it**
(``do``), **Ask me in the UI** (``ask``: the press is *prepared*, stored with its fields, and
waits on the page and in Needs you for the owner's press) or **Never** (``never``), with
exceptions per verb (``ask.ladder`` in ``kranto.yaml``). Three rows are locks no setting turns
(the owner's standing rules): a **credential** is never set by an assistant (made and pasted by
the owner); a **house** confirm is the page's only.

``tests/test_parity.py`` keeps the table whole: no write route without a verb (or a reason on
``ROUTE_ALLOW``), every verb's route exists, the ladder is total and the locks hold.
"""

from __future__ import annotations

import contextlib
import contextvars
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from ..config import ACTIVITY_KEEP_DAYS, ACTIVITY_MAX_ROWS, UPDATE_AUTO, UPDATE_CHANNELS

# the usage reports' modes (telemetry.local.MODES; a literal here: the registry imports no
# telemetry, and the suite's validation parity test keeps the two the same)
TELEMETRY_MODES = ("off", "local", "basic", "detailed")

LADDER_KINDS = ("read", "reversible", "spend", "outward", "destructive", "credential")
# a kind that left with its feature (the broker's, with Invest: cut 2): a choice
# stored for it is accepted and never read, so a settings file that names it still loads
RETIRED_KINDS = ("broker",)
CHOICES = ("do", "ask", "never")
# the owner's defaults (the owner's Q3): what can be undone or only costs money
# you have not capped is done; what leaves Kranto or cannot be undone waits for your press
DEFAULTS = {"read": "do", "reversible": "do", "spend": "do", "outward": "ask",
            "destructive": "ask", "credential": "never"}
# the standing rules, as locks: (choice, why) for every caller that is not the owner pressing
LOCKS = {
    "credential": ("never", "a key, a token or a login is made and pasted by you, on the page"),
}
HOUSE_WHY = "this is confirmed on the page only (the house confirm)"
CONSENT_WHY = ("sending usage reports is your consent: given by you on the page only "
               "(turning them off needs no approval: telemetry.off)")
DOORS = ("ui", "cli", "mcp", "console", "agent")
OWNER_DOORS = ("ui", "cli")
EVERYONE = DOORS
OWNERS_ONLY = ("ui", "cli")
PAGE_ONLY = ("ui",)
FIELD_TYPES = ("text", "line", "int", "number", "bool", "enum", "ids", "list", "usd", "object")
CHOICE_WORDS = {"do": "Do it", "ask": "Ask me in the UI", "never": "Never"}
KIND_WORDS = {
    "read": "Reads", "reversible": "Changes you can undo", "spend": "Spending",
    "outward": "What leaves Kranto", "destructive": "What cannot be undone",
    "credential": "Keys, tokens and logins",
}
CLIENT = re.compile(r"[a-z0-9][a-z0-9 ._-]{0,39}")


@dataclass(frozen=True)
class Field:
    """One input of a verb: its name in the route's body (or path), its type, its words."""

    name: str
    type: str = "line"
    says: str = ""
    required: bool = False
    choices: tuple[str, ...] = ()
    max: int | None = None         # a text's most characters (the press refuses more)
    min: int = 0                   # and its fewest
    lo: float | None = None        # a number's least (the press refuses less)
    hi: float | None = None        # and its most


@dataclass(frozen=True)
class Verb:
    """One write a person can make. ``path`` and ``method`` are the route that performs it
    (its page door); ``also`` are older routes that do the same (a form post of the old
    pages). ``subject`` is the kind of thing it acts on (``new`` for a verb that makes one);
    its id fills the path's first parameter. ``fixed`` are body values the verb always sends
    (``topic.archive`` is the status route with ``status: archived``); a fixed value whose name
    is a path parameter fills the path (a feature's action). ``body`` is how the route reads its
    input: ``json``, ``form`` (an old page's form post), ``fields`` (``{"fields": {...}}``, a
    feature's action) or ``act`` (``{kind, subject, fields}``, the build loop's ``api/act``).
    ``page`` and ``mark``
    are templates over the subject's id (``{id}``) and the fields: where the change shows, and
    the row that is marked there. ``lock`` is ``"ask"`` for a verb a setting cannot make Do it
    (the house confirm)."""

    kind: str
    title: str
    says: str
    ladder: str
    method: str
    path: str
    subject: str = "new"
    fields: tuple[Field, ...] = ()
    doors: tuple[str, ...] = EVERYONE
    click: str = "click"
    page: str = "#/home"
    mark: str = ""
    undo: str | None = None
    cost: str | None = None
    body: str = "json"
    fixed: tuple[tuple[str, Any], ...] = ()
    also: tuple[tuple[str, str], ...] = ()
    lock: str | None = None
    id_from: str = "id"          # the answer's key that names a new subject
    # the kinds of subject it takes, when more than one (a build loop's action: new, idea,
    # build); empty: ``subject`` alone. With ``new`` among them the id is optional.
    subjects: tuple[str, ...] = ()
    # the field the route reads the subject's id from, when the path has no place for it (a
    # feature's action: News reads topic_id)
    subject_field: str | None = None
    # fields of which the press needs at least one ("send keep_days or max_rows")
    one_of: tuple[str, ...] = ()

    def needs_id(self) -> bool:
        if self.subjects:
            return "new" not in self.subjects
        return self.subject != "new" and bool(self.params)

    @property
    def params(self) -> list[str]:
        """The path's parameters, in order (``/api/topics/{topic_id:int}`` → topic_id)."""
        return re.findall(r"{(\w+)(?::\w+)?}", self.path)

    def view(self) -> dict[str, Any]:
        return {"kind": self.kind, "title": self.title, "says": self.says,
                "ladder": self.ladder, "subject": self.subject,
                "fields": [{"name": f.name, "type": f.type, "says": f.says,
                            "required": f.required, "choices": list(f.choices),
                            "max": f.max, "min": f.min, "lo": f.lo, "hi": f.hi}
                           for f in self.fields],
                "one_of": list(self.one_of),
                "doors": list(self.doors), "click": self.click, "page": self.page,
                "mark": self.mark, "undo": self.undo, "cost": self.cost, "lock": self.lock,
                "subjects": list(self.subjects) or [self.subject],
                "route": {"method": self.method, "path": self.path}}


def F(name: str, type: str = "line", says: str = "", required: bool = False,
      choices: tuple[str, ...] = (), lo: float | None = None, hi: float | None = None) -> Field:
    return Field(name, type, says, required, choices, lo=lo, hi=hi)


ID_TOPIC = "the topic's id"
ID_SOURCE = "the source's id"
ID_CUB = "the cub's id"
NOTE = F("note", "text", "a note, in your words")

# fmt: off
CORE: tuple[Verb, ...] = (
    # -- topics: what Kranto watches --------------------------------------------------------------
    Verb("topic.add", "Add topic", "Add a topic to watch: its name and one sentence of what it "
         "covers, in the owner's words. With scout, Kranto also proposes sources for it.",
         "reversible", "POST", "/api/topics",
         fields=(F("name", "line", "the topic's name", True),
                 F("description", "text", "one sentence: what it covers", True),
                 F("scout", "bool", "also propose sources for it (one model call, about $0.05)"),
                 # the route's APPROVE_RULES (PAR: "trusted" was offered and refused)
                 F("approve", "enum", "which proposed sources are approved by themselves: none, "
                   "core (core proposals above the line) or all", choices=("none", "core", "all"))),
         page="#/watch/topic/{id}/sources", mark="topic:{id}", undo="topic.archive",
         cost="free; with scout, about $0.05 (one model call)",
         also=(("POST", "/topics"),)),
    Verb("topic.edit", "Edit topic", "Rename a topic or change its sentence.", "reversible",
         "POST", "/api/topics/{topic_id:int}", subject="topic",
         fields=(F("name", "line", "the new name"), F("description", "text", "the new sentence"),
                 NOTE),
         page="#/watch/topic/{id}", mark="topic:{id}", undo="topic.edit"),
    Verb("topic.sources", "Change sources", "Link sources to a topic or unlink them (source ids).",
         "reversible", "POST", "/api/topics/{topic_id:int}/sources", subject="topic",
         fields=(F("add", "ids", "source ids to link"), F("remove", "ids", "source ids to unlink")),
         page="#/watch/topic/{id}/sources", mark="topic:{id}", undo="topic.sources"),
    Verb("topic.pause", "Pause", "Stop reading for a topic for now; nothing is lost.",
         "reversible", "POST", "/api/topics/{topic_id:int}/status", subject="topic",
         fixed=(("status", "paused"),), page="#/watch/topic/{id}", mark="topic:{id}",
         undo="topic.resume"),
    Verb("topic.resume", "Resume", "Read for a paused topic again.", "reversible", "POST",
         "/api/topics/{topic_id:int}/status", subject="topic", fixed=(("status", "active"),),
         page="#/watch/topic/{id}", mark="topic:{id}", undo="topic.pause"),
    Verb("topic.archive", "Archive", "Put a topic away: it is no longer read and leaves the "
         "lists; Restore brings it back.", "destructive", "POST",
         "/api/topics/{topic_id:int}/status", subject="topic", fixed=(("status", "archived"),),
         page="#/watch", mark="topic:{id}", undo="topic.restore", click="confirm"),
    Verb("topic.restore", "Restore", "Bring an archived topic back.", "reversible", "POST",
         "/api/topics/{topic_id:int}/status", subject="topic", fixed=(("status", "active"),),
         page="#/watch/topic/{id}", mark="topic:{id}", undo="topic.archive"),
    Verb("topic.scout", "Scout more", "Ask for more sources for a topic: one model call that "
         "proposes sources you approve.", "spend", "POST", "/api/topics/{topic_id}/scout",
         subject="topic", page="#/watch/topic/{id}/sources", mark="topic:{id}",
         cost="about $0.05 (one model call)", also=(("POST", "/topics/{topic_id}/scout"),)),
    # -- sources ---------------------------------------------------------------------------------
    Verb("source.add", "Watch source", "Start watching a source, for a topic: a proposal by "
         "its id, or a new one from a preset (rss, reddit, hn, …) and its fields.",
         "reversible", "POST", "/api/sources",
         fields=(F("id", "int", "a proposed source's id"),
                 F("status", "enum", "a proposal's new status (retired: dismissed)",
                   choices=("approved", "retired")),
                 F("preset", "line", "a new source's preset (rss, reddit, hn, …)"),
                 F("fields", "object", "the preset's fields (its address, handle or query)"),
                 F("topic", "int", ID_TOPIC)),
         page="#/watch/sources?sel=s{id}", mark="source:{id}", undo="source.retire",
         also=(("POST", "/sources"),)),
    Verb("source.approve", "Approve", "Approve proposed sources (ids) in one go, for a topic.",
         "reversible", "POST", "/api/sources/approve",
         fields=(F("ids", "ids", "the proposals' ids", True), F("topic", "int", ID_TOPIC)),
         page="#/watch/sources", mark="", undo="source.retire"),
    Verb("source.from_text", "Find sources in text", "Resolve a pasted list of sources (names, "
         "links, handles) into proposals you approve.", "spend", "POST",
         "/api/sources/from-text",
         fields=(F("text", "text", "the pasted list", True), F("topic", "int", ID_TOPIC)),
         page="#/watch/sources", cost="a few cents (model calls to resolve the list)"),
    Verb("source.retire", "Retire", "Stop watching a source (status retired); its observations "
         "stay.", "reversible", "POST", "/api/sources/{source_id}/status", subject="source",
         fixed=(("status", "retired"),), page="#/watch/sources?sel=s{id}", mark="source:{id}",
         undo="source.reapprove", also=(("POST", "/sources/{source_id}/status"),)),
    Verb("source.reapprove", "Watch again", "Watch a retired or dismissed source again.",
         "reversible", "POST", "/api/sources/{source_id}/status", subject="source",
         fixed=(("status", "approved"),), page="#/watch/sources?sel=s{id}", mark="source:{id}",
         undo="source.retire"),
    # a dismissed proposal is retired, as the page's Dismiss sends (PAR: "dismissed" is no
    # status the route takes, so this verb was refused from every door)
    Verb("source.dismiss", "Dismiss", "Dismiss a proposed source.", "reversible", "POST",
         "/api/sources/{source_id}/status", subject="source", fixed=(("status", "retired"),),
         page="#/watch/sources", mark="source:{id}", undo="source.reapprove"),
    Verb("source.fetch", "Read now", "Read one source now instead of at its next turn.",
         "spend", "POST", "/api/sources/{source_id}/fetch", subject="source",
         page="#/watch/sources?sel=s{id}", mark="source:{id}",
         cost="the screening of what it finds, under your watching cap"),
    Verb("source.retention", "Keep for", "How many days a source's observations are kept "
         "(0: forever).", "reversible", "POST", "/api/sources/{source_id}/retention",
         subject="source", fields=(F("days", "number", "days to keep (null: the default)"),),
         page="#/watch/sources?sel=s{id}", mark="source:{id}", undo="source.retention"),
    Verb("source.mute", "Mute", "Mute a source for some days (0 undoes it).", "reversible",
         "POST", "/api/sources/{source_id}/mute", subject="source",
         fields=(F("days", "number", "days to mute; 0 unmutes", True),),
         page="#/watch/sources?sel=s{id}", mark="source:{id}", undo="source.mute"),
    Verb("source.keep", "Keep", "Keep a source Kranto recommended removing for its downvotes; "
         "the count starts again from now.", "reversible", "POST",
         "/api/sources/{source_id}/keep", subject="source", page="#/needs",
         mark="source:{id}"),
    Verb("source.preview", "Preview", "What a source would bring, before it is watched.", "read",
         "POST", "/api/sources/preview",
         fields=(F("preset", "line", "the source's preset (rss, reddit, hn, …)", True),
                 F("fields", "object", "the preset's fields (its address, handle or query)"),
                 F("topic", "int", ID_TOPIC)),
         page="#/watch/sources"),
    # -- connections (accounts a source reads through) ---------------------------------------------
    Verb("connection.test", "Test", "Check that a connected account still answers.", "read",
         "POST", "/api/connections/{conn_id}/test", subject="connection",
         page="#/settings/connections", mark="connection:{id}"),
    Verb("connection.disconnect", "Disconnect", "Disconnect an account; its sources stop "
         "reading.", "destructive", "POST", "/api/connections/{conn_id}/disconnect",
         subject="connection", click="confirm", page="#/settings/connections",
         mark="connection:{id}", also=(("POST", "/connections/{conn_id:int}/{action}"),)),
    Verb("connection.credentials", "Paste credentials", "Keep an account's token, key or app "
         "password (pasted by you).", "credential", "POST",
         "/api/connections/{provider}/credentials", subject="provider", doors=PAGE_ONLY,
         page="#/settings/connections/{id}",
         also=(("POST", "/connections/{provider}/credentials"),)),
    Verb("connection.device", "Sign in with a code", "Start a device sign-in for an account.",
         "credential", "POST", "/connections/{provider}/device", subject="provider",
         doors=PAGE_ONLY, page="#/settings/connections/{id}",
         also=(("POST", "/connections/{provider}/device/poll"),)),
    Verb("connection.start", "Connect", "Start connecting an account (its sign-in page).",
         "credential", "POST", "/connections/{provider}/start", subject="provider",
         doors=PAGE_ONLY, page="#/settings/connections/{id}"),
    # -- the library and ideas ---------------------------------------------------------------------
    Verb("library.explain", "Explain", "Explain an observation or a cluster of the map in plain "
         "words (one model call, kept once written).", "spend", "POST", "/api/explain",
         fields=(F("observation_id", "int", "an observation's id"),
                 F("cluster", "line", "a cluster's id on the map")),
         page="#/watch/evidence", cost="about $0.01 (one model call, once)",
         also=(("POST", "/obs/{obs_id}/explain"), ("POST", "/clusters/{cluster}/explain"))),
    Verb("observation.remove", "Remove this post", "Remove one observation now (a deletion "
         "request): it leaves the library and every rollup.", "destructive", "POST",
         "/api/observations/{obs_id}/remove", subject="observation", click="confirm",
         page="#/watch/evidence", mark="observation:{id}"),
    Verb("idea.later", "Later", "Put an idea card off: it leaves Waiting on Ideas and comes back "
         "after the days given (7 by default; 0 brings it back now).", "reversible", "POST",
         "/api/ideas/{idea_id}/later", subject="idea",
         fields=(F("days", "int", "days until it comes back (7; 0: back now)", lo=0, hi=365),),
         page="#/ideas/{id}", mark="idea:{id}", undo="idea.later"),
    Verb("theme.card", "Card it now", "Write one idea card on a theme of the latest map now.",
         "spend", "POST", "/api/themes/{lineage}/card", subject="theme", page="#/ideas",
         fields=(F("hint", "text", "an idea to start from (optional): a news story's own idea "
                                   "seed, or its headline"),
                 F("story", "line", "the news story it was asked from (optional): "
                                    "brief:<id>:<item>, the item counted from 1")),
         cost="about $0.06 (one card call and its check)"),
    Verb("post.write", "Write a post", "Write a draft post about an idea card (about: card:<n>), "
         "a news item (brief:<id>:<item>, the item counted from 1) or this week's news (week), as "
         "a blog post (as: blog, the default), short posts for the sites the owner ticked in "
         "Settings › Posting (as: short, a card or an item: with their blog connected, the blog "
         "post first and each short post linking to it) or a short post for Mastodon (as: toot, "
         "a card only). Model calls in the background; the drafts wait on Post, and nothing is "
         "sent until the owner opens the site or chooses to post there.", "spend", "POST",
         "/api/post/write",
         fields=(F("about", "line", "card:<n>, brief:<id>:<item> or week", True),
                 F("as", "enum", "blog (a blog post), short (short posts for the ticked "
                                 "sites) or toot (a short post for Mastodon)",
                   choices=("blog", "short", "toot")),
                 F("angle", "text", "the owner's angle, one sentence: their own, or one of "
                                    "/api/post/angles' proposals they picked (optional). The "
                                    "post opens on its claim, prediction or question; none "
                                    "writes a plain summary"),
                 F("take", "text", "the angle's old name (optional): read when angle is "
                                   "absent")),
         page="#/post", cost="about $0.03 (one model call; short posts: one a site, and the "
                             "blog post first when it is connected)"),
    Verb("post.edit", "Save", "Save the owner's own words for a waiting draft ("
         "): title and body (a long post), or parts (a short post or a thread, each its "
         "text), or drop (an extra to remove). The edit is filed as the next draft of the same "
         "series and waits on Post as before; the original draft stays under Earlier drafts. "
         "Nothing is sent.", "reversible", "POST", "/api/post/d/{id:int}/edit",
         subject="draft",
         fields=(F("title", "line", "the draft's title or subject"),
                 F("body", "text", "the draft's words, as markdown"),
                 F("parts", "list", "[{text}]: a short post or a thread, each part's words"),
                 F("drop", "line", "an extra to remove (its key)")),
         one_of=("title", "body", "parts", "drop"),
         page="#/post/d/{id}", mark="draft:{id}", undo="post.edit"),
    # -- the prose profile (three verbs, the target holds) --------------
    Verb("prose.check", "Check", "Check a piece of text against the owner's prose profile: what "
         "reads like AI, each with its span, its rule and a plain fix (no model call).", "read",
         "POST", "/api/prose/check",
         fields=(F("text", "text", "the text to check", True),
                 F("site", "line", "the site it is for: blog, newsletter, mastodon, bluesky, "
                                   "linkedin, threads, x or substack"),
                 F("take", "text", "the owner's own line for it: a first-person claim it does "
                                   "not back is flagged")),
         page="#/settings/posting"),
    Verb("prose.voice", "Save", "Change the owner's prose profile: the voice card, samples "
         "(samples_add [{text, site}], samples_remove [ids]), the never, keep and always lists "
         "(never_add, never_remove, …), the switches (length, register, opinions, emoji, "
         "hashtags, links, grade), the checker's strictness and rules_off, guides per site, "
         "disclosure per site, or take (whether Write a post asks what they think).",
         "reversible", "POST", "/api/prose/voice",
         fields=(F("voice", "text", "the voice card, in plain words (at most 2,000 characters)"),
                 F("switches", "object", "length, register, opinions, emoji, hashtags, links, "
                                         "grade"),
                 F("strictness", "enum", "the checker: off, light or strict",
                   choices=("off", "light", "strict")),
                 F("rules_off", "list", "rule ids the checker skips (GET /api/prose)"),
                 F("guides", "object", "site -> guide names, or null for Kranto's default"),
                 F("disclosure", "object", "site -> a line under the post (\"\": off)"),
                 F("take", "bool", "ask “What do you think?” on Write a post"),
                 F("never_add", "list", "words or /patterns/ never to use"),
                 F("never_remove", "list", "entries to take off the never-list"),
                 F("keep_add", "list", "phrases of the owner's the checker leaves alone"),
                 F("keep_remove", "list", "entries to take off the keep-list"),
                 F("always_add", "list", "lines every post keeps (a sign-off)"),
                 F("always_remove", "list", "entries to take off the always-list"),
                 F("samples_add", "list", "[{text, site}]: things the owner wrote"),
                 F("samples_remove", "list", "sample ids")),
         page="#/settings/posting"),
    Verb("prose.learn", "Learn", "Learn from the owner's edits: give a draft and the text they "
         "sent to get proposals for the never-list, the keep-list and the voice card; or answer "
         "one (proposal, answer yes or no). Nothing changes without a yes.", "reversible",
         "POST", "/api/prose/learn",
         fields=(F("draft", "text", "the draft as Kranto wrote it"),
                 F("sent", "text", "the text as the owner sent it"),
                 F("proposal", "line", "a proposal's id, to answer it"),
                 F("answer", "enum", "yes or no", choices=("yes", "no"))),
         one_of=("draft", "proposal"), page="#/settings/posting"),
    Verb("feedback.add", "Grade", "Grade an idea card or a piece of evidence: cards like it rank "
         "higher or lower, and a source with many downvotes is offered for removal (target idea "
         "or observation; value useful, not_useful, or skip to clear).", "reversible", "POST",
         "/api/feedback",
         fields=(F("target", "line", "what it is about", True), F("target_id", "line", "its id"),
                 F("value", "line", "the rating or label", True), NOTE),
         page="#/ideas"),   # a card's grade shows on Ideas (16: the old Learning page)
    Verb("today.seen", "Mark seen", "Mark what Today showed as seen.", "reversible", "POST",
         "/api/seen", fields=(F("at", "line", "up to when (an ISO time)"),), page="#/today"),
    # -- Kranto as a whole
    # --------------------------------------------------------------------------
    Verb("kranto.pause", "Pause", "Pause Kranto: no model spend and nothing new starts until "
         "Resume.", "reversible", "POST", "/pause", body="form",
         fields=(F("reason", "line", "why, in a few words"),), page="#/home", mark="kranto:paused",
         undo="kranto.resume"),
    Verb("kranto.resume", "Resume", "Resume Kranto after a pause.", "reversible", "POST", "/resume",
         body="form", page="#/home", mark="kranto:paused", undo="kranto.pause"),
    Verb("job.run_now", "Run now", "Run one of Kranto's jobs now (ingest, snapshot, ideas, …) "
         "instead of at its time.", "spend", "POST", "/run/{kind}", subject="job", body="form",
         page="#/activity", cost="the job's usual spend, under your caps"),
    Verb("watch.resume", "Resume watching", "Start reading again after the first setup.",
         "reversible", "POST", "/api/watch/resume", page="#/watch"),
    # -- activity ----------------------------------------------------------------------------------
    Verb("run.stop", "Stop", "Stop a run at its next step; what it did stays.", "destructive",
         "POST", "/api/activity/{uuid}/stop", subject="run", page="#/activity",
         mark="run:{id}"),
    Verb("activity.dismiss", "Dismiss", "Put a failing run or an incident away until it "
         "happens again.", "reversible", "POST", "/api/activity/dismiss",
         fields=(F("kind", "line", "the failing run's kind"),
                 F("incident", "line", "an incident's id (auth:openrouter)")),
         one_of=("kind", "incident"), page="#/activity"),
    Verb("activity.settings", "Save", "How long Activity keeps its runs.", "reversible", "POST",
         "/api/settings/activity",
         fields=(F("keep_days", "number", "days", lo=ACTIVITY_KEEP_DAYS[0],
                   hi=ACTIVITY_KEEP_DAYS[1]),
                 F("max_rows", "int", "rows at most", lo=ACTIVITY_MAX_ROWS[0],
                   hi=ACTIVITY_MAX_ROWS[1])),
         one_of=("keep_days", "max_rows"), page="#/activity"),
    # -- settings ----------------------------------------------------------------------------------
    Verb("settings.service_memory", "Save", "The memory Kranto's service runs under "
         "(service.memory): its MemoryMax in GB, or auto (from this machine's memory); applied "
         "at once, and its use is shown beside it.", "reversible", "POST",
         "/api/settings/service",
         fields=(F("memory", "object", 'GB of MemoryMax (MemoryHigh is 1 GB under it), or "auto"',
                   True),),
         page="#/settings/system?sel=eservice-memory", undo="settings.service_memory"),
    Verb("settings.models", "Save", "Which model each of Kranto's roles uses.", "reversible",
         "POST", "/api/settings/models",
         # gate is the judge's signal threshold, a number (PAR: it was typed bool, and the
         # route refuses true and false)
         fields=(F("role", "line", "the role (judge, reason, …)", True),
                 F("model", "line", "the model", True),
                 F("gate", "number", "the judge's signal threshold, above 0 and at most 1",
                   lo=0, hi=1)),
         page="#/settings/models", undo="settings.models"),
    Verb("settings.spend", "Save", "Kranto's spending caps (null: no cap).", "spend", "POST",
         "/api/settings/spend",
         fields=(F("monthly_usd", "usd", "watching's monthly cap"),
                 F("deep_dive_daily_usd", "usd", "the deep dives' daily slice"),
                 F("x_monthly_usd", "usd", "the X cap"),
                 F("search_monthly_usd", "usd", "the live search cap")),
         page="#/settings/spend", undo="settings.spend"),
    Verb("settings.reading", "Save", "How often kranto reads, and whether deep dives run.",
         "reversible", "POST", "/api/settings/reading",
         fields=(F("every_hours", "number", "hours between reads"),
                 F("deep_dive_enabled", "bool", "deep dives on or off")),
         one_of=("every_hours", "deep_dive_enabled"),
         page="#/settings/watching", undo="settings.reading"),
    Verb("settings.search_callers", "Save", "Which of Kranto's parts may use live search.",
         "reversible", "POST", "/api/setup/search/callers",
         fields=(F("callers", "object", "on or off per caller"),
                 F("recent_weeks", "int", "how recent")),
         page="#/settings/tools"),
    # consent is the owner's (TEL, 2026-10-27): an assistant may prepare the choice, never
    # make it, under every ladder setting; turning it off is telemetry.off, done directly
    Verb("settings.telemetry", "Save", "Whether Kranto sends its usage reports (what is in them "
         "is on the page). Prepared for your approval only: consent is yours.", "outward", "POST",
         "/api/settings/telemetry",
         fields=(F("mode", "enum", "the mode", choices=TELEMETRY_MODES),
                 F("dismiss", "bool", "end Today's reminder")),
         page="#/settings/privacy", lock="consent"),
    Verb("telemetry.off", "Turn usage reports off", "Stop counting and sending usage reports "
         "(the same as kranto telemetry off).", "reversible", "POST", "/api/settings/telemetry",
         fixed=(("mode", "off"),), page="#/settings/privacy", undo="settings.telemetry"),
    Verb("setup.finish", "Finish", "Finish the first setup.", "reversible", "POST",
         "/api/setup/finish", doors=OWNERS_ONLY,
         fields=(F("build_mode", "line"), F("concurrency", "int"), F("replace", "bool")),
         page="#/welcome"),
    Verb("setup.check", "Check", "Check the model provider answers.", "read", "POST",
         "/api/setup/check", page="#/settings/keys"),
    Verb("setup.key", "Save key", "Keep the model provider's key (pasted by you).", "credential",
         "POST", "/api/setup/key", doors=PAGE_ONLY, page="#/settings/keys"),
    Verb("setup.provider", "Save provider", "Choose the model provider and keep its key (pasted "
         "by you).", "credential", "POST", "/api/setup/provider", doors=PAGE_ONLY,
         page="#/settings/keys"),
    Verb("setup.search", "Save", "Choose the live search provider and keep its key (pasted by "
         "you).", "credential", "POST", "/api/setup/search", doors=PAGE_ONLY,
         page="#/settings/tools"),
    Verb("token.add", "Add token", "Make a token for an agent.", "credential", "POST",
         "/api/tokens", doors=OWNERS_ONLY, page="#/settings/access"),
    Verb("token.change", "Rotate or revoke", "Rotate, revoke or limit a token.", "credential",
         "POST", "/api/tokens/{name}/{what}", subject="token", doors=OWNERS_ONLY,
         page="#/settings/access"),
    Verb("prompt.preview", "Preview", "What a prompt would read with your additions.", "read",
         "POST", "/api/prompts/preview",
         fields=(F("id", "line", "the prompt", True),
                 F("subject", "line", "the item to fill it from")),
         page="#/settings/prompts"),
    Verb("prompt.save", "Save", "Change one of Kranto's prompts (your additions or its template; "
         "every version is kept).", "reversible", "POST", "/api/prompts/{pid}", subject="prompt",
         fields=(F("additions", "text", "your additions"), F("template", "text", "the template"),
                 NOTE),
         page="#/settings/prompts", undo="prompt.restore"),
    Verb("prompt.reset", "Reset", "Put a prompt back to Kranto's own (your versions are kept).",
         "reversible", "POST", "/api/prompts/{pid}/reset", subject="prompt", click="confirm",
         page="#/settings/prompts", undo="prompt.restore"),
    Verb("prompt.restore", "Restore", "Bring back an earlier version of a prompt.",
         "reversible", "POST", "/api/prompts/{pid}/restore", subject="prompt",
         fields=(F("version", "int", "the version", True), NOTE), page="#/settings/prompts"),
    Verb("prompt.note", "Note", "Write a note on a prompt's version.", "reversible", "POST",
         "/api/prompts/{pid}/versions/{n:int}/note", subject="prompt",
         fields=(F("n", "int", "the version", True), NOTE), page="#/settings/prompts"),
    # -- updates -----------------------------------------------------------------------------------
    Verb("update.check", "Check now", "Look for a new release now.", "reversible", "POST",
         "/api/update/check", page="#/settings/updates"),
    Verb("update.apply", "Update", "Install a release (Kranto restarts; it rolls back by itself "
         "if a page breaks).", "destructive", "POST", "/api/update", click="confirm",
         fields=(F("to", "line", "the release (default: the newest)"),
                 F("when", "enum", "now, or after what is running finishes",
                   choices=("after-build", "now"))),
         page="#/settings/updates", undo="update.rollback"),
    Verb("update.cancel", "Cancel", "Cancel an update that has not started.", "reversible",
         "POST", "/api/update/cancel", page="#/settings/updates"),
    Verb("update.rollback", "Roll back", "Go back to the release before.", "destructive", "POST",
         "/api/update/rollback", click="confirm", page="#/settings/updates"),
    Verb("update.settings", "Save", "How Kranto updates (the line, when).", "reversible", "POST",
         "/api/update/settings",
         # the route's SETTABLE (PAR: hour was a field the route never read, and quiet_window
         # one it reads that no assistant could send)
         fields=(F("channel", "enum", "the line", choices=UPDATE_CHANNELS),
                 F("auto", "enum", "update by itself when idle, or not", choices=UPDATE_AUTO),
                 F("quiet_window", "line", "when an idle update may run (HH:MM-HH:MM)")),
         one_of=("channel", "auto", "quiet_window"), page="#/settings/updates"),
    Verb("update.hold", "Hold updates", "Hold updates for now (and stop what runs, if asked).",
         "reversible", "POST", "/api/hold",
         fields=(F("reason", "line"), F("stop_builds", "bool")), page="#/settings/updates",
         undo="update.release_hold"),
    Verb("update.release_hold", "Release hold", "Release a hold on updates.", "reversible",
         "DELETE", "/api/hold", page="#/settings/updates", undo="update.hold"),
    # -- cubs --------------------------------------------------------------------------------------
    Verb("cub.check", "Check", "Check a pasted cub.yaml (nothing is installed).", "read", "POST",
         "/api/cubs/check", fields=(F("text", "text", "the cub.yaml", True),), page="#/cubs"),
    # the cubs' install jobs are the page's and the command line's (their routes refuse the
    # console and kranto mcp: PAR)
    Verb("cub.fetch", "Look at a cub", "Fetch a cub from its source to look at before "
         "installing.", "reversible", "POST", "/api/cubs/fetch", doors=OWNERS_ONLY,
         fields=(F("source", "line", "where it comes from"), F("ref", "line"),
                 F("kind", "line"), F("id", "line")),
         page="#/cubs"),
    Verb("cub.install", "Install", "Install a cub (code from outside Kranto, run in its "
         "sandbox).", "outward", "POST", "/api/cubs/{id}/install", subject="cub",
         click="confirm", fields=(F("job", "line"), F("topics", "ids", "its topics")),
         page="#/cub/{id}", mark="cub:{id}", undo="cub.remove"),
    Verb("cub.update", "Check for its update", "Look for a cub's newer version.", "reversible",
         "POST", "/api/cubs/{id}/update", subject="cub", page="#/cub/{id}", mark="cub:{id}"),
    Verb("cub.apply_update", "Update", "Install a cub's newer version.", "outward", "POST",
         "/api/cubs/{id}/apply_update", subject="cub", click="confirm",
         fields=(F("job", "line"),), page="#/cub/{id}", mark="cub:{id}"),
    Verb("cub.remove", "Remove", "Remove a cub (with purge, its data too).", "destructive",
         "POST", "/api/cubs/{id}/remove", subject="cub", click="confirm",
         fields=(F("purge", "bool", "its data too"),), page="#/cubs", mark="cub:{id}"),
    Verb("cub.enable", "Turn on", "Turn a cub on.", "reversible", "POST",
         "/api/cubs/{id}/enable", subject="cub", page="#/cub/{id}", mark="cub:{id}",
         undo="cub.disable"),
    Verb("cub.disable", "Turn off", "Turn a cub off.", "reversible", "POST",
         "/api/cubs/{id}/disable", subject="cub", page="#/cub/{id}", mark="cub:{id}",
         undo="cub.enable"),
    Verb("cub.stop", "Stop", "Stop a cub now (its jobs do not run until Resume).",
         "reversible", "POST", "/api/cubs/{id}/stop", subject="cub",
         fields=(NOTE,), page="#/cub/{id}", mark="cub:{id}", undo="cub.resume"),
    Verb("cub.resume", "Resume", "Let a stopped cub run again.", "reversible", "POST",
         "/api/cubs/{id}/resume", subject="cub", page="#/cub/{id}", mark="cub:{id}",
         undo="cub.stop"),
    Verb("cub.dry", "Practice", "A cub's actions do nothing outside Kranto (practice).",
         "reversible",
         "POST", "/api/cubs/{id}/dry", subject="cub", fields=(F("kind", "line"),),
         page="#/cub/{id}", mark="cub:{id}", undo="cub.live"),
    Verb("cub.live", "Send for real", "A cub's actions act outside Kranto (for real).",
         "outward", "POST", "/api/cubs/{id}/live", subject="cub", fields=(F("kind", "line"),),
         click="house", page="#/cub/{id}", mark="cub:{id}", undo="cub.dry", lock="ask"),
    Verb("cub.run", "Run now", "Run one of a cub's jobs now.", "spend", "POST",
         "/api/cubs/{id}/run", subject="cub", fields=(F("job", "line", "the job", True),
                                                      F("kind", "line")),
         page="#/cub/{id}", mark="cub:{id}", cost="the job's usual spend, under its caps"),
    Verb("cub.cancel_job", "Cancel", "Cancel a cub's install or update job.", "reversible",
         "POST", "/api/cubs/jobs/{job}/cancel", subject="job", doors=OWNERS_ONLY,
         page="#/cubs"),
    Verb("cubs.settings", "Save", "The cubs' switches and limits (cubs.enabled, a cub's "
         "limits).", "reversible", "POST", "/api/cubs/settings", click="house", lock="ask",
         fields=(F("key", "line", "the setting", True), F("value", "object", "its value")),
         page="#/settings/capabilities"),
    # -- features (News, the cubs) ----------------------------------------------------------------
    Verb("feature.setting", "Save", "One of a feature's settings (News, a cub's); some are "
         "confirmed on the page only.", "reversible", "POST",
         "/api/f/{feature}/settings", subject="feature",
         fields=(F("key", "line", "the setting", True), F("value", "object", "its value")),
         page="#/settings/{id}"),
    Verb("ticket.confirm", "Confirm", "Confirm what a feature or a cub asked to do (send a "
         "newsletter, post a draft): on the page only.", "outward", "POST",
         "/api/tickets/{id}/confirm", subject="ticket", doors=PAGE_ONLY, click="house",
         page="#/needs", also=(("POST", "/api/requests/{id}/confirm"),)),
    Verb("ticket.decline", "Decline", "Decline what a feature or a cub asked to do.",
         "outward", "POST", "/api/tickets/{id}/decline", subject="ticket", doors=PAGE_ONLY,
         fields=(NOTE,), page="#/needs", also=(("POST", "/api/requests/{id}/decline"),)),
    Verb("ticket.again", "Offer again", "Ask again for a cub's newest draft that was practiced, "
         "ran out of time or was refused (the same fields; no cub run): on the page only.",
         "reversible", "POST", "/api/tickets/{id}/again", subject="ticket", doors=PAGE_ONLY,
         page="#/needs"),
    Verb("newsletter.check", "Check", "Check the newsletter platform you connected.", "read",
         "POST", "/api/newsletter/check", page="#/settings/publishing"),
    Verb("newsletter.audience", "Choose audience", "Which audience on the platform the "
         "newsletter sends to.", "outward", "POST", "/api/newsletter/audience", click="confirm",
         doors=PAGE_ONLY,                 # the route's: "made on the Accounts page only" (PAR)
         fields=(F("name", "line", "the audience", True),), page="#/settings/publishing"),
    # -- the assistant's own ladder: the owner's only ----------------------------------------------
    Verb("assistant.ladder", "Save", "What an assistant may do by itself: per kind of action "
         "and per verb (the locks cannot be turned).", "credential", "POST",
         "/api/settings/assistant", doors=OWNERS_ONLY, page="#/settings/assistant"),
    # the owner's Q6 (2026-10-25): outside Kranto's folder only when asked, the change shown
    # first; an assistant asked for it prepares the press, the owner makes it
    Verb("assistant.global", "Add Kranto to my own client", "Add Kranto to your own Claude Code "
         "or Codex: their own commands, shown first, outside Kranto's folder.", "outward",
         "POST", "/api/assistant/global", lock="ask",
         fields=(F("harness", "enum", "claude or codex", True, choices=("claude", "codex")),),
         page="#/settings/assistant?sel=outside"),
)
# fmt: on

# write routes that are no verb, and why (the parity test's allow-list)
ROUTE_ALLOW: dict[tuple[str, str], str] = {
    ("POST", "/auth/code"): "signing a browser in: how the page gets its token",
    ("POST", "/auth/signout"): "signing this browser out",
    ("POST", "/api/telemetry/view"): "the page's own count of a page view (usage reports)",
    ("POST", "/api/post/d/{id:int}/posted"): "I posted it: the person's own record, on the page "
                                             "only, that they posted a draft in the site "
                                             "themselves; never an assistant's (nothing is sent)",
    ("POST", "/api/post/d/{id:int}/cancel"): "a scheduled post's Cancel, on the page: it only "
                                             "takes back the person's yes for an hour (nothing "
                                             "is sent); never a send",
    ("POST", "/api/post/sites"): "Settings › Posting's choices (the sites ticked, Post "
                                 "directly): the person's, on the page; an assistant may read "
                                 "them (GET), never switch on a send",
    ("POST", "/api/home/visit"): "the home's own visit marker, moved as the page draws the home "
                                 "(While you were away counts from it); nobody's decision",
    ("POST", "/brb/{path:path}"): "the page's writes: its own registry and parity test",
    ("POST", "/api/post/write/dismiss"): "Post's own Dismiss of a failed write's line: "
                                         "the owner puts it away; nothing else changes",
    # three verbs dropped from what an assistant can call: their routes are the page's
    # (or the build loop's) own until the factory leaves (cut 3)
    ("POST", "/api/ideas/{idea_id}/outcome"): "the build loop's record of what became of a "
                                              "card: no assistant verb",
    ("POST", "/api/shell"): "the home's arrangement, written by Settings' own pane only: no "
                            "assistant verb",
    ("POST", "/api/update/promote"): "the maintainer's promotion of a nightly, on the page "
                                     "only: no assistant verb",
    ("POST", "/api/verbs/{kind}"): "the verbs' own door: it runs a verb of this table",
    ("POST", "/api/prepared/{uuid}/{what}"): "a prepared action: the owner approves or dismisses "
                                             "a verb an assistant prepared",
    ("POST", "/api/f/{feature}/act/{action}"): "a feature's or a cub's action: each is a verb "
                                               "f.<feature>.<action> (feature_verbs)",
    ("POST", "/api/prose/voice/draft"): "the page's draft of a voice card from samples: shown "
                                        "to the owner to edit; nothing is stored until "
                                        "prose.voice saves it",
    ("POST", "/api/prose/revise"): "the draft's Fix: the text with its flagged spans rewritten, "
                                   "returned to the page; nothing is stored until the owner "
                                   "saves the draft",
    ("POST", "/api/post/angles"): "Write a post's angle step: three proposed sentences shown "
                                  "to the owner to pick or edit; nothing is stored until "
                                  "post.write sends the one chosen",
}


# -- feature and cub actions -------------------------------------------------------------------

def _feature_ladder(action) -> str:
    """A feature's action's ladder kind: its manifest's ``kind`` when it says one (cubs,),
    else from its confirm class: a click is reversible, a confirm is outward."""
    kind = getattr(action, "ladder", None)
    if kind in ("reversible", "spend", "outward", "destructive"):
        return kind
    return "outward" if action.click in ("confirm", "house") else "reversible"


# the field a feature's action reads its subject's id from, by the subject's kind (PAR: the id
# went nowhere, so News' Brief now said "no topic None" to every assistant)
SUBJECT_FIELDS = {"topic": "topic_id"}


# the features with a page of their own in the UI; every other feature's page is its cub page,
# as the cubs' are
OWN_PAGES = ("news",)

# what an action reads that its manifest does not declare as a form (its page sends them from its
# own controls), so an assistant may send them too (PAR: News' toggle refused every assistant,
# "on is true or false", since on was no field it could send)
FEATURE_FIELDS: dict[str, tuple[Field, ...]] = {
    "news.toggle": (Field("on", "bool", "News on (true) or off (false) for this topic", True),
                    Field("cadence", "enum", "how often (news.brief.CADENCES)",
                          choices=("daily", "weekdays", "weekly")),
                    Field("hour", "int", "the hour its brief is written (0 to 23)"),
                    Field("weekday", "int", "a weekly brief's day (0 is Monday)")),
    "news.article_now": (Field("brief_id", "int", "the brief's id", True),
                         Field("n", "int", "the item's number in the brief, from 0", True)),
}


def feature_verbs() -> tuple[Verb, ...]:
    """Kranto's features' and the installed cubs' actions, as verbs ``f.<feature>.<action>``."""
    try:
        from .registry import features
        feats = features()
    except Exception:  # noqa: BLE001 - a cub that cannot load leaves the core's verbs whole
        return ()
    out = []
    for f in feats:
        if _feature_off(f):
            continue                       # a feature that is off offers no verb (PR 1.2)
        for a in getattr(f, "actions", ()) or ():
            fid, _, name = a.kind.partition(".")
            house = a.click == "house"
            fields = tuple(Field(x.key, {"enum": "enum", "choice": "enum", "bool": "bool",
                                         "int": "int", "usd": "usd"}.get(x.kind, "text"),
                                 x.label + (f": {x.hint}" if x.hint else ""), x.required,
                                 tuple(str(c[0] if isinstance(c, (list, tuple)) else c)
                                       for c in x.choices))
                           for x in a.fields)
            fields += tuple(f for f in FEATURE_FIELDS.get(a.kind, ())
                            if f.name not in {x.name for x in fields})
            subject = a.subjects[0] if a.subjects else "feature"
            out.append(Verb(
                kind=f"f.{a.kind}", title=a.title,
                says=a.says or f"{a.title} ({getattr(f, 'title', fid)})",
                ladder=_feature_ladder(a), method="POST",
                path="/api/f/{feature}/act/{action}", subject=subject, fields=fields,
                doors=PAGE_ONLY if house else EVERYONE, click=a.click,
                page=f"#/{fid}" if fid in OWN_PAGES and not _is_cub(f) else f"#/cub/{fid}",
                mark="",
                lock="ask" if house else None, body="fields",
                fixed=(("feature", fid), ("action", name)),
                subject_field=SUBJECT_FIELDS.get(subject)))
    return tuple(out)


def _is_cub(feature) -> bool:
    try:
        from .registry import is_cub
        return bool(is_cub(feature))
    except Exception:  # noqa: BLE001
        return False


# -- the build loop's actions (the page's registry, through its host API) ---------------------

BRB_PATH = "/brb/{path:path}"

# Whether the build loop's actions are verbs in this process (``configure``; the runtime sets
# it from ``builds.enabled``). Off until set: absent means off.
BUILDS = False
# The runtime whose config says what else is off: a feature's verbs while it is
# off, the cub shop's without cubs.developer. Read at each listing, so a switch turned on the
# page counts at once.
# None (no runtime opened, as in a unit test): nothing more is hidden.
_RT: Any = None
SHOP = frozenset({"cub.check", "cub.fetch", "cub.install", "cub.update", "cub.apply_update",
                  "cub.remove"})


def configure(*, builds: bool, rt: Any = None) -> None:
    global BUILDS, _RT
    BUILDS = bool(builds)
    _RT = rt


def _hidden(kind: str) -> bool:
    """Whether a core verb is off by a switch: the cub shop's."""
    cfg = getattr(_RT, "cfg", None)
    if cfg is None:
        return False
    try:
        if kind in SHOP:
            from .cubs.settings import developer
            return not developer(cfg)
    except Exception:  # noqa: BLE001 - a config that cannot say hides nothing
        return False
    return False


def _feature_off(feature) -> bool:
    cfg = getattr(_RT, "cfg", None)
    if cfg is None:
        return False
    try:
        from .registry import enabled
        return not enabled(cfg, feature)
    except Exception:  # noqa: BLE001
        return False


def brb_verbs(*, gated: bool = True) -> tuple[Verb, ...]:
    """the page's actions as verbs ``b.<kind>`` (``host_api.verb_rows``): run through its
    ``api/act`` in this process, so the ladder, the prepared presses and Activity are the same
    for a build as for a topic. None without the page, or with one from before the registry,
    and none while builds are off (``gated``; the guard asks with ``gated=False`` whether
    the page has verbs at all, so an assistant never reaches ``api/act`` around the ladder)."""
    if gated and not BUILDS:
        return ()
    try:
        from kranto.page.host_api import verb_rows
        rows = verb_rows()
    except Exception:  # noqa: BLE001 - no the page, or an older one: the core's verbs only
        return ()
    out = []
    for r in rows:
        try:
            ladder = r["ladder"] if r["ladder"] in LADDER_KINDS else "outward"
            doors = tuple(d for d in r.get("doors") or OWNERS_ONLY if d in DOORS) or OWNERS_ONLY
            if ladder in LOCKS:
                doors = tuple(d for d in doors if d in OWNER_DOORS)
            fields = tuple(Field(str(f["name"]), f.get("type") if f.get("type") in FIELD_TYPES
                                 else "text", str(f.get("says") or ""), bool(f.get("required")),
                                 tuple(str(c) for c in f.get("choices") or ()),
                                 _whole(f.get("max")), _whole(f.get("min")) or 0)
                           for f in r.get("fields") or ())
            out.append(Verb(
                kind=f"b.{r['kind']}", title=str(r["title"]), says=str(r["says"]),
                ladder=ladder, method="POST", path=BRB_PATH,
                subject=str(r.get("subject") or "new"), fields=fields, doors=doors,
                click="confirm" if r.get("click") == "confirm" else "click",
                page=str(r.get("page") or "#/build"), mark=str(r.get("mark") or ""),
                body="act", fixed=(("path", "api/act"),),
                subjects=tuple(str(s) for s in r.get("subjects") or ())))
        except (KeyError, TypeError):
            continue                       # a row this Kranto cannot read: left out, not fatal
    return tuple(out)


def _whole(x: Any) -> int | None:
    """A limit from a row of the page's (absent or null from an older one: none)."""
    return x if isinstance(x, int) and not isinstance(x, bool) and x >= 0 else None


def all_verbs() -> tuple[Verb, ...]:
    return tuple(v for v in CORE if not _hidden(v.kind)) + feature_verbs() + brb_verbs()


def get(kind: str) -> Verb | None:
    for v in CORE:
        if v.kind == kind:
            return None if _hidden(kind) else v
    if kind.startswith("f."):
        return next((v for v in feature_verbs() if v.kind == kind), None)
    if kind.startswith("b."):
        return next((v for v in brb_verbs() if v.kind == kind), None)
    return None


def routes_of(verb: Verb) -> Iterator[tuple[str, str]]:
    yield verb.method, verb.path
    yield from verb.also


# -- doors and the ladder ----------------------------------------------------------------------

def door_of(identity: dict[str, Any] | None) -> str | None:
    """The verb door a caller came through: ``ui`` (the page's cookie, or the UI's token),
    ``cli``, ``mcp`` (an outside client over ``kranto mcp``), ``console`` (the console in Kranto),
    ``agent`` (a named agent's token)."""
    if not identity:
        return None
    origin = str(identity.get("origin") or "")
    if origin.startswith("agent:"):
        return "agent"
    return origin if origin in DOORS else None


def by_of(identity: dict[str, Any] | None, client: str | None = None) -> str:
    """Who did it, as Activity and the page's marks say it: ``ui``, ``cli``,
    ``console:<harness>``, ``mcp:<client>``, ``mcp``, ``agent:<name>``. ``client`` is the
    words a client gives for itself (MCP's ``clientInfo.name``, the console's harness): words
    for the mark only, never authority (the token is the door)."""
    origin = str((identity or {}).get("origin") or "")
    door = door_of(identity)
    c = " ".join(str(client or "").lower().split())[:40]
    if door in ("mcp", "console") and c and CLIENT.fullmatch(c):
        return f"{door}:{c}"
    return origin or "unknown"


BY_NAMES = {"claude": "Claude Code", "claude-code": "Claude Code", "codex": "Codex",
            "gemini": "Gemini CLI", "opencode": "OpenCode"}


def by_words(by: str | None) -> str:
    """"by Claude Code", "by Codex (outside)", "by your own assistant", "by agent RC"."""
    by = str(by or "")
    door, _, who = by.partition(":")
    name = BY_NAMES.get(who, who)
    if door == "console":
        return f"by {name or 'the console'}"
    if door == "mcp":
        return f"by {name} (outside)" if name else "by your own assistant"
    if door == "agent":
        return f"by agent {who}"
    if door in ("ui", "cli"):
        return "by you"
    return "by an assistant"


@dataclass(frozen=True)
class Choice:
    """What the ladder says for one verb and one caller: ``do``, ``ask`` or ``never``; whether
    a setting may change it; why, in words."""

    choice: str
    locked: bool = False
    why: str = ""


def ladder_setting(cfg) -> dict[str, dict[str, str]]:
    """``ask.ladder`` as set: ``{"kinds": {kind: choice}, "verbs": {kind: choice}}``."""
    ask = getattr(cfg, "ask", None)
    raw = getattr(ask, "ladder", None) or {}
    return {"kinds": dict(raw.get("kinds") or {}), "verbs": dict(raw.get("verbs") or {})}


def choice_for(cfg, verb: Verb) -> Choice:
    """The ladder's answer for a caller that is not the owner pressing."""
    if verb.ladder in LOCKS:
        c, why = LOCKS[verb.ladder]
        return Choice(c, True, why)
    if verb.lock == "consent":
        return Choice("ask", True, CONSENT_WHY)
    if verb.lock == "ask":
        return Choice("ask", True, HOUSE_WHY)
    s = ladder_setting(cfg)
    by_verb = s["verbs"].get(verb.kind)
    if by_verb in CHOICES:
        return Choice(str(by_verb), False, f"your setting for {verb.title} ({verb.kind})")
    by_kind = s["kinds"].get(verb.ladder)
    if by_kind in CHOICES:
        return Choice(str(by_kind), False,
                      f"your setting for {KIND_WORDS[verb.ladder].lower()}")
    return Choice(DEFAULTS[verb.ladder], False,
                  f"Kranto's default for {KIND_WORDS[verb.ladder].lower()}")


def check_ladder(raw: Any, lookup: bool = True) -> dict[str, dict[str, str]]:
    """``ask.ladder`` from a request or the file: refuses a lock turned and an unknown kind;
    with ``lookup``, a verb that is locked too (the page's save)."""
    if raw is None:
        return {"kinds": {}, "verbs": {}}
    if not isinstance(raw, dict) or set(raw) - {"kinds", "verbs"}:
        raise ValueError("ask.ladder has kinds and verbs, each a map of names to do, ask or "
                         "never")
    out: dict[str, dict[str, str]] = {"kinds": {}, "verbs": {}}
    for part in ("kinds", "verbs"):
        m = raw.get(part) or {}
        if not isinstance(m, dict):
            raise ValueError(f"ask.ladder.{part} maps names to do, ask or never")
        for name, c in m.items():
            if c not in CHOICES:
                raise ValueError(f"ask.ladder.{part}.{name}: {c!r} is not one of do, ask, never")
            if part == "kinds":
                if name in RETIRED_KINDS:
                    continue                   # accepted, never read (its feature left)
                if name not in LADDER_KINDS:
                    raise ValueError(f"ask.ladder.kinds.{name}: not a kind "
                                     f"({', '.join(LADDER_KINDS)})")
                if name in LOCKS and c != LOCKS[name][0]:
                    raise ValueError(f"{KIND_WORDS[name]} cannot be changed: {LOCKS[name][1]}")
            elif lookup:
                v = get(str(name))
                if v is not None and (v.ladder in LOCKS or v.lock) and \
                        c != choice_for(None, v).choice:
                    raise ValueError(f"{v.title} ({v.kind}) cannot be changed: "
                                     f"{choice_for(None, v).why}")
            out[part][str(name)] = c
    return out


# -- the page and the mark ---------------------------------------------------------------------

def fill(template: str, subject_id: Any, fields: dict[str, Any]) -> str:
    """A page or mark template filled from the subject's id and the fields. A page with a
    value missing is its section (``#/watch``); a mark with one is empty."""
    if not template:
        return ""
    values = {k: v for k, v in (fields or {}).items()
              if isinstance(v, (str, int, float)) and v != ""}
    if subject_id not in (None, ""):
        values["id"] = subject_id

    def one(m: re.Match) -> str:
        v = values.get(m.group(1))
        return m.group(0) if v is None else quote_part(str(v))
    out = re.sub(r"{(\w+)}", one, template)
    if "{" not in out:
        return out
    if not template.startswith("#/"):
        return ""
    return "#/" + template[2:].split("/", 1)[0]


def quote_part(s: str) -> str:
    from urllib.parse import quote
    return quote(s, safe="")


# -- who is acting, for the runs a verb starts -------------------------------------------------

_ACTING: contextvars.ContextVar[str | None] = contextvars.ContextVar("kranto_verb_by",
                                                                       default=None)


def acting_by() -> str | None:
    """While a verb runs for a caller that is not the page: who (``console:claude``,
    ``mcp:codex``); None otherwise. A job a verb starts says it in Activity."""
    return _ACTING.get()


@contextlib.contextmanager
def acting(by: str | None) -> Iterator[None]:
    """``with verbs.acting("console:claude"):`` around a verb's route."""
    token = _ACTING.set(by)
    try:
        yield
    finally:
        _ACTING.reset(token)


def table_view(cfg) -> list[dict[str, Any]]:
    """Every verb with the ladder's answer for an assistant (``GET /api/verbs``)."""
    out = []
    for v in all_verbs():
        c = choice_for(cfg, v)
        out.append({**v.view(), "choice": c.choice, "locked": c.locked, "why": c.why,
                    "assistant": bool(set(v.doors) & {"mcp", "console", "agent"})})
    return out


__all__ = ["CHOICES", "CORE", "DEFAULTS", "DOORS", "LADDER_KINDS", "LOCKS", "RETIRED_KINDS",
           "ROUTE_ALLOW",
           "Choice", "Field", "Verb", "acting", "acting_by", "all_verbs", "by_of", "by_words",
           "check_ladder", "choice_for", "door_of", "feature_verbs", "fill", "get",
           "ladder_setting", "routes_of", "table_view"]
