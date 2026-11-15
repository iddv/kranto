"""kranto mcp generated from the verb registry (rule 4).

The server serves the one registry (``GET /api/verbs``: its own verbs, the features' and cubs'
actions) and the one door (``POST /api/verbs/<kind>``, where the owner's ladder decides). So the
tool list is the table: one tool per verb the client's door may run, plus the reads and four
generic tools, and a verb's call goes to that door with the client's own name for Activity,
never ``confirm``. A cub's own verbs (``cub.*``: ``kranto_cub_*``) are the cub developer's: listed
only with ``cubs.developer`` on (``/api/status``). The compact profile is the few generic tools.
Against a Kranto without the registry, the tools are the reads (test_mcp_tools.py)."""
import json

import pytest

from kranto.page.mcp import tools as T


def afk_table() -> list[dict]:
    """What the server's GET /api/verbs answers: its own verbs (one on two kinds of thing), a
    locked one, and a cub's own two."""
    own = [
        {"kind": "topic.add", "title": "Add topic", "says": "Add a topic to watch.",
         "ladder": "reversible", "subject": "new", "choice": "do", "page": "#/watch",
         "fields": [{"name": "name", "type": "line", "says": "its name", "required": True,
                     "choices": []},
                    {"name": "scout", "type": "bool", "says": "", "required": False,
                     "choices": []}],
         "doors": ["ui", "cli", "mcp", "console", "agent"]},
        {"kind": "settings.telemetry", "title": "Save", "says": "Usage reports.",
         "ladder": "outward", "subject": "new", "choice": "ask", "page": "#/settings/privacy",
         "fields": [], "doors": ["ui", "cli", "mcp", "console", "agent"]},
        {"kind": "setup.key", "title": "Save key", "says": "The provider's key.",
         "ladder": "credential", "subject": "new", "choice": "never", "page": "#/settings/keys",
         "fields": [], "doors": ["ui"]},
    ]
    doors = ["ui", "cli", "mcp", "console", "agent"]
    return own + [
        {"kind": "feedback.add", "title": "Grade", "says": "Grade an idea or a source.",
         "ladder": "reversible", "subject": "idea|source", "choice": "do", "page": "#/ideas",
         "fields": [{"name": "value", "type": "line", "says": "", "required": True,
                     "choices": ["useful", "not_useful"]}], "doors": doors},
        {"kind": "idea.later", "title": "Later", "says": "Put an idea away for some days.",
         "ladder": "reversible", "subject": "idea", "choice": "do", "page": "#/ideas",
         "fields": [{"name": "days", "type": "int", "says": "", "required": False,
                     "choices": []}], "doors": doors},
        {"kind": "cub.fetch", "title": "Fetch a cub", "says": "Fetch a cub's code.",
         "ladder": "reversible", "subject": "new", "choice": "ask", "page": "#/settings",
         "fields": [], "doors": doors},
        {"kind": "cub.remove", "title": "Remove a cub", "says": "Remove one.",
         "ladder": "destructive", "subject": "new", "choice": "ask", "page": "#/settings",
         "fields": [], "doors": doors}]


class Fake:
    def __init__(self, table=None, reads=None, developer=False):
        self.table = afk_table() if table is None else table
        self.reads = reads or []
        self.posts: list = []
        self.developer = developer

    def client(self, door="mcp"):
        def afk_get(path, q=None):
            if path == "/api/verbs":
                return 200, {"verbs": self.table, "reads": self.reads}
            if path == "/api/status":
                return 200, {"builds": False, "cubs_developer": self.developer}
            return 200, {"path": path, "q": q}

        def afk_post(path, body):
            self.posts.append((path, body))
            return 200, {"ok": True, "say": "done", "page": "#/watch/topic/7/sources",
                         "mark": "topic:7", "run": "r1", "answer": {"id": 7, "_run": "r1"}}
        return T.Client(get=lambda p, q=None: (404, {}), post=lambda p, b: (404, {}),
                        afk_get=afk_get, afk_post=afk_post, door=door)


def test_rule_4_the_tool_list_is_the_registry():
    fake = Fake()
    tools = T.tools(fake.client())
    names = [t["name"] for t in tools]
    assert len(names) == len(set(names)), "a tool name twice"
    verbs = {T.verb_tool_name(v["kind"]) for v in fake.table if "mcp" in v["doors"]
             and not v["kind"].startswith("cub.")}
    assert set(names) == verbs | set(T.READS) | set(T.GENERIC)
    assert len(names) == 10 + 4 + 4                       # the reads, the generic, the verbs
    assert T.verb_tool_name("setup.key") not in names     # the owner's own: no tool
    assert {"kranto_topic_add", "kranto_feedback_add", "kranto_idea_later"} <= set(names)
    for t in tools:
        s = t["schema"]
        assert s["type"] == "object" and s["additionalProperties"] is False, t["name"]
        assert set(s.get("required") or []) <= set(s["properties"]), t["name"]
        assert "confirm" not in s["properties"] or t["name"] in T.READS, t["name"]
        json.dumps(s)
        assert t["description"]


def test_a_cubs_own_verbs_are_tools_only_for_the_cub_developer():
    """CUT: kranto_cub_* left the default tool set; ``cubs.developer`` on brings them back."""
    default = {t["name"] for t in T.tools(Fake().client())}
    assert not [n for n in default if n.startswith("kranto_cub_")]
    assert "cub.fetch" not in {v["kind"] for v in T.kranto_verbs(Fake().client())["verbs"]}
    with pytest.raises(T.ToolError, match="no tool"):
        T.call(Fake().client(), "kranto_cub_fetch", {})
    with pytest.raises(T.ToolError, match="no verb"):
        T.call(Fake().client(), "kranto_act", {"verb": "cub.fetch"})
    dev = Fake(developer=True)
    names = {t["name"] for t in T.tools(dev.client())}
    assert {"kranto_cub_fetch", "kranto_cub_remove"} <= names
    T.call(dev.client(), "kranto_cub_fetch", {})
    assert dev.posts[-1][0] == "/api/verbs/cub.fetch"


def test_the_ladder_is_said_in_the_description():
    by = {t["name"]: t for t in T.tools(Fake().client())}
    assert "Asks the owner first" in by["kranto_settings_telemetry"]["description"]
    assert "Shows on #/watch" in by["kranto_topic_add"]["description"]
    assert by["kranto_topic_add"]["schema"]["required"] == ["name"]
    fb = by["kranto_feedback_add"]["schema"]
    assert fb["properties"]["id"] and fb["properties"]["subject"]["enum"] == ["idea", "source"]


def test_a_verb_goes_to_krantos_door_with_the_clients_name():
    fake = Fake()
    c = fake.client()
    c.who = "codex"
    out = T.call(c, "kranto_topic_add", {"name": "Marine robotics", "scout": False,
                                        "confirm": True})
    path, body = fake.posts[-1]
    assert path == "/api/verbs/topic.add"
    assert body == {"fields": {"name": "Marine robotics", "scout": False}, "client": "codex"}
    assert out["page"] == "#/watch/topic/7/sources" and out["run"] == "r1"
    assert "<<<document" in out["answer"] and "_run" not in out["answer"]
    T.call(c, "kranto_feedback_add", {"id": "7", "subject": "source", "value": "useful"})
    assert fake.posts[-1] == ("/api/verbs/feedback.add",
                              {"fields": {"value": "useful"}, "client": "codex",
                               "subject": {"kind": "source", "id": "7"}})
    T.call(c, "kranto_act", {"verb": "idea.later", "id": 3, "fields": {"days": 2}})
    assert fake.posts[-1][1]["subject"] == {"kind": "idea", "id": 3}


def test_the_console_door_lists_its_own_verbs():
    table = afk_table()
    table[0] = {**table[0], "doors": ["ui", "console"]}
    names = {t["name"] for t in T.tools(Fake(table).client(door="console"))}
    assert "kranto_topic_add" in names
    assert "kranto_topic_add" not in {t["name"] for t in T.tools(Fake(table).client())}


def test_the_compact_profile():
    names = [t["name"] for t in T.tools(Fake().client(), compact=True)]
    assert names and set(names) == set(T.COMPACT)
    assert "kranto_act" in names and "kranto_topic_add" not in names


def test_reads():
    fake = Fake(reads=[{"path": "/api/topics", "says": "your topics"}])
    c = fake.client()
    got = T.call(c, "kranto_reads", {})
    paths = [r["path"] for r in got["reads"]]
    assert "/api/topics" in paths and any(p.startswith("/brb/api/") for p in paths)
    out = T.call(c, "kranto_read", {"path": "/api/topics", "query": {"q": "robots"}})
    assert out["path"] == "/api/topics" and "<<<document" in out["data"]
    for bad in ("/etc/passwd", "/api/../auth/code", "//evil", "/static/x"):
        try:
            T.call(c, "kranto_read", {"path": bad})
        except T.ToolError as e:
            assert "/api/" in str(e)
        else:
            raise AssertionError(bad)


def test_without_the_registry_the_tools_are_the_reads():
    c = Fake().client()
    c.afk_get = lambda p, q=None: (404, {"error": "not found"})
    names = {t["name"] for t in T.tools(c)}
    assert names == set(T.READS) and "kranto_topic_add" not in names
    assert T.kranto_verbs(c)["verbs"] == []


def test_the_clients_own_name_is_read_from_both_sdks():
    """MCP's initialize names the client: the SDK's 2.x keeps it as client_info, 1.x clientInfo.
    Found on the scratch: Claude Code's verbs read "by your own assistant" until both were read."""
    from types import SimpleNamespace as NS

    from kranto.page.mcp.server import client_name
    two = NS(client_params=NS(client_info=NS(name="claude-code")))
    one = NS(client_params=NS(clientInfo=NS(name="Codex")))
    assert client_name(two) == "claude-code" and client_name(one) == "Codex"
    assert client_name(NS(client_params=None)) is None and client_name(None) is None
