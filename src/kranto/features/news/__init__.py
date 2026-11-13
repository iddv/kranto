"""News (Part A): a short professional brief per topic, every item cited to the
topic's observations or dated live search results, never to model memory. Off for every topic
until the owner turns it on; the first feature built on the core. After each
brief the item with the most behind it earns an article: a deep dive into the
pages behind it, the library's earlier lines and the week's briefs, every claim checked."""

from __future__ import annotations

from kranto.core import (
    UI,
    Action,
    Docs,
    Events,
    Feature,
    Job,
    Model,
    Nav,
    Permissions,
    Prompt,
    Setting,
    Settings,
    Spend,
    Telemetry,
    Tile,
    TodayRow,
    Widget,
    placed,
)

from . import api, articles, brief, cli

FEATURE = Feature(
    id="news",
    title="News",
    says="A short brief per topic of what happened, each item cited to what your watchers "
         "kept or to dated search results; the day's main item as a full article.",
    version="1.1.0",
    jobs=(Job("news.brief", brief.run_due, every_hours=1, when="news.enabled",
              purpose="news_brief",
              says="hourly: writes the brief of each topic News is on for, when it is due, "
                   "then the article for the item with the most behind it"),),
    owns=("news_topics", "news_briefs", "news_articles", "news_article_pages"),
    api={"briefs.list": api.briefs_list, "briefs.get": api.briefs_get,
         "topic_rows": api.topics, "latest": api.latest, "count": api.count,
         "today": api.today, "widget_brief": api.widget_brief,
         "brief": api.brief_page, "articles.list": api.articles_list,
         "articles.get": api.articles_get, "article_for_item": api.article_for_item},
    actions=(Action("news.toggle", "Turn News on or off for this topic", api.toggle,
                    doors=("ui", "cli"), subjects=("topic",),
                    says="News on or off for one topic, with its cadence and hour"),
             Action("news.write_now", "Brief now", api.write_now, doors=("ui", "cli"),
                    subjects=("topic",), says="writes this topic's brief now"),
             Action("news.article_now", "Deep dive now", api.article_now, doors=("ui", "cli"),
                    click="confirm",
                    says="writes an article for one item of a brief now: reads the pages "
                         "behind it and calls the model once (about 10 cents on the reason "
                         "model)")),
    settings=Settings(keys=placed({
        "news.enabled": Setting("bool", True, words="News: briefs for the topics it is on for"),
        "news.hour": Setting("int", 7, lo=0, hi=23, words="hour a topic's brief is written "
                                                          "(local)"),
        "news.cadence": Setting("enum", "daily", ("daily", "weekdays", "weekly"),
                                words="how often a topic turned on gets a brief"),
        "news.model": Setting("enum", "reason", ("reason", "judge"),
                              words="the model that writes briefs (reason: the stronger one)"),
        "news.max_items": Setting("int", 7, lo=3, hi=7, words="items a brief at most"),
        "news.max_words": Setting("int", 60, lo=20, hi=120,
                                  words="words an item's body and why at most"),
        "news.max_age_days": Setting("int", 3, lo=1, hi=30,
                                     words="older than this is background (Earlier)"),
        "news.max_observations": Setting("int", 40, lo=5, hi=100,
                                         words="observations a brief reads at most"),
        "news.monthly_usd": Setting("usd", None, words="News a month, briefs and articles "
                                                        "(null: no cap)"),
        "news.articles_per_day": Setting("int", 1, lo=0, hi=3,
                                         words="articles a day per topic: the items with the "
                                               "most behind them, after the brief"),
        "news.depth": Setting("enum", "standard", articles.DEPTH_CHOICES,
                              words="light: your observations; standard: 4 pages behind them "
                                    "and two searches; deep: 6 longer pages"),
        "news.sources": Setting("list", list(articles.SOURCES), articles.SOURCES,
                                words="what an article reads besides your observations"),
        "news.lead_image": Setting("bool", True, words="pictures from sources: the page's own "
                                                       "image, credited and linked, shown here "
                                                       "only"),
        "news.article_min": Setting("float", 0.15, lo=0.0, hi=2.0, by_hand=True,
                                    words="the score an item needs to earn an article")},
        groups={"News": ("news.hour", "news.cadence", "news.model"),
                "Articles": ("news.articles_per_day", "news.depth", "news.sources",
                             "news.lead_image")},
        advanced=("news.max_items", "news.max_words", "news.max_age_days",
                  "news.max_observations", "news.article_min"))),
    permissions=Permissions(reads=("topics", "library", "objects", "spend", "ideas"),
                            model=Model(tiers=("reason", "judge"),
                                        purposes=("news_brief", "news_article")),
                            search=("web", "discussion"), fetch=("cited",)),
    events=Events(publishes=("brief.published",)),
    ui=UI(nav=(Nav("news", "News", under="Desk", count="count"),), pages=("news",),
          today_rows=(TodayRow("brief", "today", group="new", primary="open"),),
          cards={"brief": {"title": "headline", "lines": ["body", "why"],
                           "fields": [{"key": "date", "label": "Date", "kind": "date"},
                                      {"key": "sources", "label": "Sources", "kind": "list"}],
                           "actions": []}},
          settings_group=("watching", "News"), keys={"g n": "news"},
          kind="watch", glyph="grid",
          tile=Tile(line="A brief per topic", count="count", words="ready", tone="new"),
          # the first manifest widget of a feature of Kranto's own: the path cubs use
          widgets=(Widget("brief", "The brief", "rows", "widget_brief",
                          says="The newest brief's headlines, each opening the brief.",
                          sizes=("M", "L"), every_s=600,
                          empty="No brief yet: turn News on for a topic on its page."),)),
    spend=Spend(purposes=("news_brief", "news_article"),
                caps={"news.monthly_usd": "News a month"}),
    telemetry=Telemetry(counters={"news.briefs": (0, 10000)}),
    prompts=(Prompt("news", "News brief", "Writes a topic's brief from its observations since "
                    "the last brief and two dated live searches, citing each item.",
                    "each topic News is on for, at its hour",
                    {"today": ("today's date", False),
                     "topic_name": ("the topic's name", True),
                     "topic_description": ("the topic's description", False),
                     "max_items": ("items at most", False),
                     "period_start": ("the first day the brief covers", False),
                     "previous_date": ("the previous brief's date", False),
                     "previous": ("the previous brief's headlines and sources", False),
                     "since": ("when the window starts", False),
                     "observations": ("the observations, numbered, one per line", True),
                     "search_block": ("the live search results, dated and numbered, or the "
                                      "sentence that no search ran", False)}),
             Prompt("news_article", "News article", "Writes the article for the brief item with "
                    "the most behind it: from its observations, the pages behind them, the "
                    "library's earlier lines, the previous briefs and two live searches, every "
                    "paragraph, figure, date and relation cited.",
                    "after each brief, for the item that earns one; Deep dive now",
                    {"topic_name": ("the topic's name", True),
                     "topic_description": ("the topic's description", False),
                     "item_headline": ("the item's headline", True),
                     "item_body": ("the item's two sentences", False),
                     "item_why": ("why the item matters", False),
                     "today": ("today's date", False),
                     "period_start": ("the first day the brief covers", False),
                     "evidence": ("the item's observations, labelled", True),
                     "pages": ("the pages behind them, labelled", False),
                     "earlier": ("the library's earlier lines on the story", False),
                     "briefs": ("the previous briefs' items", False),
                     "search_block": ("the live search results, or the sentence that none ran",
                                      False)})),
    evals=("news.scorecard",),
    docs=Docs(page="docs/news.md",
              glossary={"Brief": "A short dated summary of what happened around a topic, every "
                                 "item cited.",
                        "Article": "News's longer look at the day's main item: what happened, "
                                   "why it matters, what came before, who is involved and what "
                                   "to watch, every claim cited and checked."},
              words={"news.toggle": "News for this topic"}),
    grades={"news_item": (("off_topic", "off topic"), ("repeat", "said before"),
                          ("not_in_source", "not what the source says"),
                          ("too_long", "too long")),
            "news_article": (("off_topic", "off topic"), ("repeat", "said before"),
                             ("not_in_source", "not what the source says"),
                             ("too_long", "too long"), ("wrong_figure", "wrong figure"))},
    cli=cli.add,
)
