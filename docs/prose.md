# How Kranto writes your posts: the prose engine

Every post Kranto drafts (a blog post, a newsletter's opening, a Mastodon post, and each site
SOCIAL adds) is written through one engine, `kranto.prose`. It puts your voice and Kranto's rules
into the prompt, checks the draft for the shapes that make machine-written text tiring to read,
and rewrites only the lines that need it. It writes for readers. It does not try to get past AI
detectors, and nothing here claims it does.

## What shapes a post

| Part | What it is | Where it lives |
|---|---|---|
| **The floor** | Kranto's rules against the common tells, each written as what to do, with the shape to avoid as its example | shipped: `src/kranto/prose/guides/floor.md` (always used) |
| **Plain words** | Orwell, Zinsser, GOV.UK and plainlanguage.gov, paraphrased | shipped: `guides/plain.md` |
| **A site's template** | what a blog post, a Mastodon post, a LinkedIn post… looks like; every number can be changed | shipped: `guides/sites/<site>.md`; your `<home>/prose/guides/sites/<site>.md` replaces it |
| **Your voice card** | how you write, in plain words, at most about 250 words. Your old tone setting (`blog.tone`, `toot.tone`, `newsletter.intro`) became its first line, once | `<home>/prose/voice.md` |
| **Your samples** | things you wrote; the 3 closest to each post (by embedding) go in as examples | `<home>/prose/samples/<id>.md` (a first line `site: mastodon` is optional) |
| **Your lists** | **never** (words, or `/regular expressions/`), **keep** (your phrases the checker leaves alone), **always** (a sign-off) | `<home>/prose/never.txt`, `keep.txt`, `always.txt`: one a line, `#` a comment |
| **Switches** | length (short, medium, long), register (casual, neutral, formal), opinions (only mine, or suggest one marked for you), emoji (never, sparingly), hashtags (never, the site's), links (in the post, or in the first reply), reading level (a grade, 8), salt (plain, wry or salty; plain by default) and more salt on thin items (on: a thin item, with few facts or about a product note or a small tool, goes one step saltier) | the `settings` row `prose.profile` |
| **The checker** | strictness (off, light, strict) and the rules you turned off | `prose.profile` |
| **Guides per site** | which guides each site's writer follows (the floor always) | `prose.profile` |
| **Disclosure** | per site, off by default; a ready line: "Drafted with Kranto from my notes; edited and sent by me." | `prose.profile` |
| **Your angle** | one sentence on Write a post: why this interests you. Type your own, or pick one of the three Kranto proposes: where it leads (in five or ten years), a bet (a number or a name, and why) and a scene (the item in one real situation). Each goes past the item's own claim. It drives the post: its first sentence, its stance, what it leaves out | sent with the write (`angle`; `take` is its old name) |
| **The writer's model** | per writer (blog, toot, newsletter, social), apart from the models that watch your sources; unset, the reason tier's model writes. A writer may also be on OpenAI's own API with a key you paste (How you write's **Save and test**, or `kranto provider openai --key-stdin`; kept as `OPENAI_API_KEY` in the home's `.env`, never shown again); it is never the watcher's. Chosen on How you write's **Who writes**. No default is chosen | `prose.profile` (`writers`) |

You, or your own Claude Code, may edit the files under `<home>/prose/` by hand; kranto reads them
fresh for every post.

**A post makes a claim.** Its first sentence is a claim, a prediction or a question a reader
cares about; the sources back it and tell the story. It names a source once and trusts the reader
with what is missing, carries one caveat at most, and has no fixed sections: the angle chooses
the shape. A blog post is short, 120 to 200 words unless your length switch says otherwise, and never padded. With no
angle, the writer writes a plain summary and the draft says it has none.

**It goes past the item** (round 3, from the owner's second blind read). The item is the
evidence; the post argues what it means: where it leads, what else must be true for it and how
likely that is. The speculation is yours and said so ("I think", "my bet"), never stated as a
fact; every fact still comes from the sources. A post from an idea card is about what the card's
evidence means for the reader's world; the idea itself, a tool someone could build, is
background. Kranto checks each proposed angle with a rule before showing it (no model call): it
refuses an experience, a stock prediction ("within a year, more X will Y"), a tool as where it
leads, a bet with no number or name, and an angle that only restates the item; a refused one is
asked for once more, and a stock one that comes back is left out.

**Salt** is how much wit and bite a post carries: plain, wry (understatement) or salty (a jab at
the thing: the product, the claim, the hype). Salt is aimed at things, never at a person or a
group, never a slur, and a salty post names no private person: the checker flags a name or a
handle the material doesn't have (`salt.person`).

**Never invented.** A stance is fine when your angle carries it ("My bet: …"); an experience is
not, whatever the angle ("I tried it", "at my company"). A post says "I" or "we" for anything
else only when your angle or your samples back it. The checker flags a first-person sentence
nothing of yours backs (`voice.invented_i`), and the writer cuts one that is left.

## The pipeline

1. **compose** builds the messages: the writer's task, the floor, the chosen guides, your voice
   card, the switches in words, the always and never lists, the site's limits and features (from
   the caller), the angle's rule and (for a blog post) this post's shape, picked per post so two
   posts don't share an outline; then the 3 closest samples inside `<example>` fences, then the
   material: your angle first, the card's or item's facts and quotes with their source numbers,
   fenced as data.
2. The writer makes its one model call.
3. **check** runs locally, with no model call: the same text always gives the same flags.
4. **revise** rewrites only the flagged spans, in at most two rounds of one call each. Every
   byte outside the spans is the draft's own, whatever the model answers. A replacement that adds
   an address the text did not hold, is far longer than the span, or says again what another
   sentence says, is refused. A first sentence with no claim is rewritten from your angle.
5. Code, not a model, then cuts an invented first-person sentence and tidies what a cut leaves
   (a doubled word, a repeated sentence, a stray space).
6. What remains is kept on the draft, and said.

### What the checker looks for

| Rule | The shape |
|---|---|
| `words.floor` | a word that reads like a model (delve, tapestry, pivotal, seamless, game-changer…; `src/kranto/prose/words.py` credits each to Humanizer, slop-forensics or Kranto). *Weak* words with honest literal uses (robust, landscape, navigate) only when strict |
| `words.never` | your never-list |
| `phrase.*` | a deep-sounding saying, an unnamed authority, a chatbot leftover, hype, a stock hook ("worth watching", "remains to be seen"), arguing with no one, "serves as" |
| `shape.not_x_but_y` | "It's not X, it's Y", "not just X but Y", the same split over two sentences |
| `shape.closer` | "Let that sink in", a last one-line paragraph that points back ("That changes everything."), a row of fragments |
| `shape.runup` | "Here's the thing:", "Let's dive in", "The result? …" |
| `shape.tricolon` | lists of three, again and again (two in a short piece) |
| `shape.ing_tail` | a trailing ", highlighting…", ", underscoring…" that adds weight |
| `shape.moral` | "Ultimately, it's a reminder that…", "The future looks bright" |
| `rhythm.dashes` | dashes as the default joint, above your own samples' rate (light: three or more, over one in 100 words) |
| `rhythm.paragraphs`, `rhythm.sentences` | paragraphs or sentences all the same length |
| `rhythm.openings` | three sentences in a row that open on the same word ("It… It… It…") |
| `rhythm.voice` | sentences much longer or shorter than your samples' |
| `reading.level` | well above your reading level |
| `site.length`, `site.links`, `site.hashtags`, `site.emoji` | the site's limits and your switches |
| `voice.invented_i` | speaks for you without your words, or tells an experience you never wrote |
| `claim.announced` | announces its structure or counts its points ("Three things point in this direction.", "First, … Second, …") |
| `claim.caveats` | catalogues what is unknown ("the sources give no details", "the honest reading", "worth keeping in mind"), always; or a second caveat ("self-reported" twice) |
| `claim.no_hook` | the first sentence makes no claim, asks nothing and risks nothing (it reports the news' subject and verb) |
| `claim.sections` | three or more sections of near-equal length |
| `claim.skeleton` | the "What happened / Why it matters" headings |
| `claim.restates` | nothing in the post but facts: no stance, prediction, question or reader in it |
| `salt.person` | a person's name or a handle the post's material does not name (checked when the material is given) |

The `claim.*` rules come from the owner's blind read of round 1; each has a
fixture made from the posts he read. `claim.no_hook`, `claim.sections`, `claim.skeleton` and
`claim.restates` apply to a post (a site or a kind given), not to a newsletter's opening or a
weekly intro.

Nothing inside a URL, code, quotation marks, or a phrase on your keep-list is flagged. Three
paragraphs of public-domain prose (Jerome, Thoreau, Twain) are in the tests as a fixture that
must stay unflagged at both strictness levels.

## The HTTP API (for PR 2: Settings › Posting › Voice, the draft's flags and Fix, Welcome)

| Method and path | Body | Answer |
|---|---|---|
| `GET /api/prose` | | `voice`, `switches`, `switch_choices`, `switch_words`, `strictness`, `rules` (`[{id, group, words, fix, on}]`), `guides` (`[{name, title, from: kranto or yours, always}]`), `sites` (`[{site, guides, default, limits, disclosure}]`), `writers` (`{blog: blog, newsletter: newsletter, toot: mastodon}`), `writer_models` (writer → `{provider, model}`, or null: the reason tier's), `writer_providers`, `writer_key` (`{set}`: never the key), `disclosure_line`, `disclosure_default` (a short post's line where none is set), `take`, `never`, `keep`, `always`, `samples` (`[{id, site, words, start}]`), `rhythm` (`{mean, sd, dashes_per_100}` or null), `proposals` (open), `migrated`, `home` |
| `POST /api/prose/check` (verb `prose.check`, read) | `{text, site?, kind?, take?, limits?, strictness?}` | `{score, verdict, flags, counts, grade, words, strictness, site, kind}`; each flag `{start, end, text, rule, words, fix, group, strength, scope}`: `start`/`end` are character offsets for the underline; `scope: text` is about the whole piece (no underline) |
| `POST /api/prose/revise` (no verb: nothing is stored) | `{text, flags?, site?, kind?, take?, limits?}` | `{text, flags, score, verdict, rounds, changed: [{start, end, before, after}], say}`: the draft's **Fix**; the page saves the text through the draft's edit |
| `POST /api/prose/writer-key` (verb `prose.writer_key`, credential, the page only) | `{key}` | `{ok, detail, set, say}`: tested with `GET /v1/models` (nothing spent) and kept only when it works; never the key, which no log holds |
| `POST /api/prose/voice` (verb `prose.voice`, reversible) | any of `voice`, `switches`, `strictness`, `rules_off`, `guides` (site → names, or null), `disclosure` (site → line, `""` off), `take`, `writer_model` (writer → `{provider, model}`, or null; the route only, from How you write: the verb's fields leave it out), `never_add`/`never_remove`, `keep_add`/`keep_remove`, `always_add`/`always_remove`, `samples_add` (`[{text, site}]`), `samples_remove` (ids) | `{ok, changed, say}`; a 400 says what is wrong |
| `POST /api/prose/voice/draft` (no verb: nothing is stored) | `{samples?: [text]}` (else your saved samples) | `{voice, say}`: one model call drafts a voice card for you to read and edit; save it with `prose.voice` |
| `POST /api/prose/learn` (verb `prose.learn`, reversible) | `{draft, sent}` | `{proposals, say}`: proposals from what you changed (kept open) |
| | `{proposal, answer: yes or no}` | `{ok, say, proposal, answer}`: a yes applies it; a no is remembered |
| `POST /api/post/angles` (no verb: nothing is stored) | `{about: card:<n> or brief:<id>:<item>, as?: blog or toot}` | `{about, as, angles: [{kind: end, bet or scene, text, words, retried?, close?}], model, say}`: Write a post's angle step, one model call (two when the rule refuses a proposal) under the writer's own model; two or three angles; 409 with no model key ("type your own sentence"), 400 for `week` |

**Write a post's angle step:** the person reads an item or a card, chooses Write a post, and sees
one box ("Why does this interest you? One sentence.") with the three proposals beside it (from
`POST /api/post/angles`) to pick or edit; a picked one is theirs. Write sends `post.write {about,
as, angle}`; Skip sends no angle and gets a plain summary, said as such. It is one more read and
no new page.

**Welcome's "How you write"** (one screen, skippable): paste 3 to 5 things you wrote →
`prose.voice {samples_add}`; the four switches → `prose.voice {switches}`; the preview sentence →
`POST /api/prose/voice/draft` then a Write a post of your choice. Skipped, the profile is the
floor plus plain words.

**On a draft:** `POST /api/prose/check {text, site, take}` gives the underlines and the line
"Reads natural" or "2 things read like AI: fix them"; Fix is `POST /api/prose/revise` with the
same body (and the flags, to fix only some). On the page: a draft's page shows the underlines
and that line under its words; Edit opens the editor (title and words, or one box a part with
its count), the same underlines under the box as you type, and **Fix them** puts `revise`'s text
in the box. Fix is an edit like any other: nothing is kept until you choose Save, which is
`post.edit` (`POST /api/post/d/<id>/edit`, [features.md](features.md)).

**Learning from edits:** the draft editor calls `POST /api/prose/learn {draft, sent}` when you
save an edited draft (`draft` is the original, `sent` your words); Post shows each proposal ("Kranto noticed you cut
'game-changer'. Never use it?") with Yes (`{proposal, answer: "yes"}`) and No.

## For a writer: in-process and in a cub

In Kranto's own code:

```python
from kranto import prose
p = prose.load(cfg, store)
messages = prose.compose({"angle": angle, "title": title, "facts": facts, "format": "..."},
                         "linkedin", p, task="Write one LinkedIn post.", kind="short",
                         limits={"max_chars": 3000}, features="Link card: …", embedder=rt.embedder)
out = prose.check(text, "linkedin", p, kind="short", take=angle)
fixed = prose.revise(text, out["flags"], p, complete=my_call, site="linkedin", take=angle)
three = prose.angles({"title": title, "facts": facts}, p, complete=my_call, site="linkedin")
```

(`check` and `revise` still name the person's words `take`: pass the angle there.)

In a cub (the SDK's `ctx.prose`, granted with the model; `bears-cub-sdk` 1.4.0):

```python
composed = ctx.prose.compose({"angle": angle, "title": title, "facts": facts},
                             site="mastodon", kind="short", task="Write one Mastodon post.",
                             limits={"max_chars": 480})
reply = ctx.model.complete(purpose="toot_caption", tier="reason", messages=composed["messages"])
sources = f"{title}\n{facts}"     # what it was written from: salt.person flags anyone else
got = ctx.prose.check(text, site="mastodon", kind="short", take=angle, sources=sources)
if got["flags"]:
    text = ctx.prose.revise(text, got["flags"], purpose="toot_caption", tier="reason",
                            site="mastodon", kind="short", take=angle, sources=sources)["text"]
```

`compose` also answers `angle` (the one used, or null for a plain summary), `take` (whether the
owner wants to be asked) and `disclosure` (the site's line, or null). `revise` spends under the
cub's own purpose, tier, hourly window and cap. When the owner set a model for Kranto's own blog,
toot or newsletter writer, that writer's model calls (its writing and its revise) go to it,
through the same metered client. The methods are in [cub-protocol.md](cub-protocol.md).

**For SOCIAL's site variants**: "before writing" is `compose(material,
site=<site>, kind=short|thread|long|note, language=, limits=<the registry's limits>,
features=<the site's playbook and advanced-feature rules>)`; the playbook comes after the
profile in the system message and wins only on what the site can carry. "After writing" is
`check(text, site=, kind=, limits=)` then, when it flags spans, `revise(...)`; a draft that still
breaks a rule keeps its `flags` for the page.

## Credits

The floor and the checker's shapes are adapted from [Humanizer](https://github.com/blader/humanizer)
(MIT), several words from [slop-forensics](https://github.com/sam-paech/slop-forensics) (MIT), and
both rest on Wikipedia's [Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing).
See `NOTICE`.

## The eval

`features/post/evals/` holds 20 brief items and idea cards, each written by the old writers and
by the new, as recorded answers. `pytest tests/test_prose_eval.py` replays them in CI with no
model: the checker's scores, the rhythm against a voice card, and the share of invented
first-person claims (which must be 0). `python -m kranto.features.post.evals.live` runs it
live by hand, under a cost cap, and adds a blind pairwise judgement.

**Round 2**: `recorded2.json` holds ten items (the five the owner read, and
five more), each written once from each of three proposed angles, with the rubric judge's marks;
`tests/test_prose_round2.py` replays it. The tools, for a bake-off across models:

- `python -m kranto.features.post.evals export --items <ids> --out DIR [--sites blog,toot]
  [--angles FILE]`: for each item and site (and angle), the composed messages as JSON and one
  plain-text prompt any model's command line can take; `index.json` lists them;
- `python -m kranto.features.post.evals read --drafts DIR --out read.html --key key.md`:
  the blind page from `DIR/<writer>/<name>.md`, unlabeled, in a random order per post, with
  A / B / C / None, a comment box, Copy my answers, light and dark; the key in its own file;
- `python -m kranto.features.post.evals round2 --home <scratch home> --out DIR --budget 3`:
  the live run itself, by hand.

The judge's rubric (`rubric.py`) is the owner's eight rules. It is a smoke test only: the owner's
own read decides (P-12).
