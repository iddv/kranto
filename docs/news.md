# News

A short, professional brief per topic: what happened since the last brief, three to seven
items, each one sentence or two with why it matters, and **every item cited** to an
observation Kranto kept or to a dated live search result. Nothing in a brief comes from
the model's memory: an item whose citations name nothing in the material is dropped by code
before you see it.

## Turning it on

News is **on for a topic you make**, at `news.hour` (07:00, your machine's time) and
`news.cadence` (daily), until you set the topic's own. Topics made before this release keep what
they had: off unless you turned it on.

**The first brief** is written as soon as the topic's first read ends, whatever the hour, from
what that read kept: about ten minutes after you choose Watch these on a new topic (Watch these
starts the first read). It is written once a topic; a failed one is tried again once. On the
brief, "From the first read. Tomorrow's covers a day." The topic's page shows how far its first
hour is: Sources, First read, First brief, First ideas, each with its time
(`GET /api/topics/{id}/start`).

- **On the page:** News › Topics, the topic's row, its switch. One click turns it off or on;
  on, the brief is written daily at 07:00 from then on. The row's Brief now writes one at once.
- **On the command line** (the watcher's own commands, run as in
  [watcher.md](watcher.md#the-watcher-alone)): `python -m kranto.cli news on Robotics` (or
  `--cadence weekdays|weekly`, `--hour 6`); `python -m kranto.cli news run Robotics` writes one
  now; `python -m kranto.cli news off Robotics`.

`news.enabled: false` in `kranto.yaml` turns the whole feature off (no job runs, nothing shows).

## What a brief is made of

1. **The topic's observations** kept since its last brief (at most `news.max_observations`,
   40, by signal), each with its date, source and link. The window is the topic's: if a day's
   brief failed, the next one covers both days.
2. **Two live searches**, dated, from the last week: the topic's name with "news this week"
   (the web and Hacker News), and the name with the window's three most frequent names. With
   no search backend, or `search.callers.news: off`, the brief says "no live search".
3. **The previous brief's items**, so the brief says what is new and leaves out what it said
   already.

Both blocks of material are fenced as data: an instruction planted in a source ("buy ZQXT
now") is text to the model, never an order, and the checks below run whatever it writes.

## The checks, in code

| Check | What happens |
|---|---|
| citations | a cite that names nothing in the material is removed; an item left citing nothing is dropped |
| dates | an item is dated by its newest cited line; older than 3 days, it is shown last, under Earlier |
| length | an item over two sentences or 60 words is asked once to be shorter, then cut at the sentence |
| names | a person named by the model but not by a cited line becomes "a person"; email addresses and phone numbers are scrubbed |
| links | a link that is not a cited line's is removed |
| repeats | an item about what the previous brief said is dropped unless it says what is new |
| count | at most 7 items (`news.max_items`); none left is a quiet brief: "nothing new worth your time since …" |

Each brief keeps what the checks did (`python -m kranto.cli news show ID --json`, `checks`).

## Cost

One call a topic a day on the reason model (`news.model: reason`; `judge` is the cheaper one,
about twelve times cheaper, and leans more on search results than on your observations).
Measured on a copy of live: 4 to 10 cents a brief on an API key, nothing
billed on a Claude plan. Each brief shows its cost; Settings › Spend counts News under
`news_brief`; `news.monthly_usd` caps it (no cap by default).

## Articles

After each brief, the item with the most behind it earns a **full article**: a
deep dive written once, never edited, with a headline, a standfirst, What happened (its
numbers as figures), Why it matters here, What came before, Who is involved, What to watch
next, readable sources and a figure the page draws from the article's own data.

**Which item.** Code, no model: an item that rests on at least one observation (an item from
search results alone has no page Kranto may read), scored by its signal, +0.05 for each cited
line beyond the first, +0.10 when it continues a story of the last seven days' briefs (a name
in an earlier headline, or an observation an earlier item cited). The top
`news.articles_per_day` (1; 0 to 3) per topic, scored at least `news.article_min` (0.15, by
hand). Ties go to the earlier item. Only for topics News is on for.

**What it reads**, every line labelled and dated, fenced as data:

1. the item's observations in full;
2. **the pages behind them**, fetched now through `ctx.fetch`, which reads only the URLs those
   observations name (never a URL the model wrote): public addresses, https, 20 s, Kranto's own
   main-text extraction, scrubbed, cut (`news.depth`: `light` reads none, `standard` up to 4
   pages of 6,000 characters, `deep` 6 of 12,000). A page read in the last 7 days is reused.
   An X, Bluesky or LinkedIn post is not fetched (a script draws it): the observation's own text
   stands for it;
3. the library's earlier lines on the story (the topic's last 60 days, by the headline's words);
4. the previous briefs' items (14 days), so What came before says what the briefs already said;
5. two live searches (the topic and the headline's names on the web, 4 weeks; the names on
   Hacker News).

`news.sources` turns blocks 2 to 5 off one by one (all on by default).

**The checks**, in code, before anything is stored: a cite naming nothing in the material is
removed and a paragraph, figure, timeline point, entity or relation left citing nothing is
dropped; a figure's digits must appear in a cited line ("six" is dropped, "1,800" kept against
"1,800 episodes"); a date must be a cited line's own or written in one (a date the source announces
ahead counts); an entity's name must be in its cited lines and a relation must join two kept entities;
a person the cited lines do not name in a role
becomes "a person"; no URL or address stays in the text (Sources carries the links). Under 120
checked words or no What happened: the article is **quiet** and the item stays a plain item.
`python -m kranto.cli news show ID --article --json` shows what the checks did (`checks`).

**The figure** is always one the page draws: the story's timeline with 3 or more points, else the numbers, else the relationship map, else the
evidence timeline (the cited lines' own dates and today), which cannot fail. Never a picture
from a model.

**Pictures from sources** (`news.lead_image`, on): the page's own preview image (its `og:image`)
as the outlet offers it for sharing, shown on the article credited to the outlet and linked to
the original, loaded from the outlet by your browser, never stored or re-served by Kranto, and
never copied into anything Kranto publishes (the newsletter, example.com, a cub that posts). Off:
no picture, the drawn figure only.

**When.** The hourly `news.brief` job writes the day's article after the brief; a failed one is
tried again at the next hour, at most twice a day. Brief now writes the brief and then its
article. **Deep dive now** on any item with an observation writes one now (it asks first: it
reads the pages and calls the model once). `python -m kranto.cli news article BRIEF ITEM` does the same from the
command line; `--dry-run` prints the material and the prompt and calls nothing.

**Cost.** One call on `news.model` (reason by default): measured 7 to 10 cents an article on
Sonnet 5.5 through an API key, nothing billed on a Claude plan. Counted on
Settings › Spend under News (`news_article`). `news.monthly_usd` caps briefs and articles
together, and articles pause at 80% of it so the briefs keep the rest.

## Grading

Each item takes ▲ or ▼ with a reason (off topic, said before, not what the source says, too
long), recorded in the same grades table as everything else (target `news_item`). An article
takes its own (target `news_article`, the article's id) with one more reason, wrong figure.

An item can also become an idea: **New idea from this…** (Kranto UI) opens New idea
filled with the item's words and the observations it rests on; the loop keeps the idea with
its source `brief` and the ref `brief:<brief id>:<item>`, so the same item is one idea, and
the brief's sheet lists the ideas made from it.

## The eval

`python -m kranto.cli news eval` scores recent briefs, free: citation validity, the mix of observation and
search citations, repeats, words per item, sentences per body, headline length, hype words, and
whether any item obeyed a planted instruction. the two model judges wait for a frozen
set of 30 briefs. `python -m kranto.cli news eval --articles` scores the articles the same way, free: the
citations the checks removed and the paragraphs they dropped, the figures kept against those
dropped, words and sections, your lines (observations, pages, briefs) against search results, the
figures drawn, and whether any article carries a trade instruction, an address or a planted line.

## Settings

`news:` in `kranto.yaml`: `enabled` (true), `hour` (7), `cadence` (daily), `model` (reason),
`max_items` (7), `max_words` (60), `max_age_days` (3), `max_observations` (40), `monthly_usd`
(null, briefs and articles together); for articles `articles_per_day` (1), `depth`
(standard), `sources` (pages, search, library, briefs), `lead_image` (true) and, by hand,
`article_min` (0.15). A topic's own on/off, cadence and hour live with the topic (the page's
row, or `python -m kranto.cli news on`).

## Not in this release

Delivery of briefs through your notify targets and the `/news.xml` feed.
