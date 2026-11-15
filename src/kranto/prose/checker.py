"""``check``: the local checker. No model call; the same text and
profile give the same flags.

It looks at shapes and rhythm, not only words: the floor's and the person's never-list,
not-X-but-Y, one-line closers, staged run-ups, runs of threes, trailing "-ing" significance,
dash density, uniform paragraphs and sentences, moralising wrap-ups, the site's limits, the
reading level, and a first-person claim the person never made (P-5). Each flag carries a span
(``start``, ``end``: character offsets into the text), its rule, plain words and a plain fix. A
flag of ``scope: text`` is about the whole piece (its rhythm, its length): ``revise`` leaves
those to the person.

Nothing inside a URL, inline code, a code block or quotation marks is flagged, nor anything
inside a phrase on the person's keep-list (the protect seam, as in anti-slop).
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import asdict, dataclass

from .profile import SITE_LIMITS, Profile, default
from .words import FLOOR_PHRASES, FLOOR_WORDS

# rule id -> (group, plain words, the fix). The ids are stable: the page turns them off by id.
RULES: dict[str, tuple[str, str, str]] = {
    "words.floor": ("words", "a word that reads like a model", "use the plain word"),
    "words.never": ("words", "on your never-list", "leave it out or say it another way"),
    "phrase.saying": ("words", "a saying that sounds deep", "say the specific claim"),
    "phrase.authority": ("words", "an unnamed authority", "name who said it, or cut it"),
    "phrase.chat": ("words", "a chatbot's leftover", "cut it"),
    "phrase.hype": ("words", "hype", "say what it is"),
    "phrase.arguing": ("words", "arguing with no one", "make the claim itself"),
    "phrase.plain_verbs": ("words", "a long way round “is”", "use is, are or has"),
    "phrase.stock": ("words", "a stock hook (“worth watching”)", "end on the last concrete fact"),
    "shape.not_x_but_y": ("shape", "“not X, but Y”", "state the point directly"),
    "shape.closer": ("shape", "a one-line closer", "end on the last concrete fact"),
    "shape.runup": ("shape", "a staged run-up", "open with the point itself"),
    "shape.tricolon": ("shape", "lists of three, again and again",
                       "list as many items as there are"),
    "shape.ing_tail": ("shape", "a trailing “-ing” that adds weight",
                       "put the fact in its own sentence, or cut it"),
    "shape.moral": ("shape", "a moral at the end", "let the facts carry it; end on a fact"),
    "rhythm.dashes": ("rhythm", "dashes as the default joint",
                      "use a comma, colon, full stop or brackets"),
    "rhythm.paragraphs": ("rhythm", "paragraphs all the same length",
                          "vary them: merge two, or split one"),
    "rhythm.sentences": ("rhythm", "sentences all the same length",
                         "vary them: a short one after a long one"),
    "rhythm.voice": ("rhythm", "sentences unlike yours", "match your samples' length"),
    "reading.level": ("reading", "harder to read than your level",
                      "shorter sentences and plainer words"),
    "site.length": ("site", "over the site's limit", "shorten it"),
    "site.links": ("site", "more links than the site takes", "keep one link"),
    "site.hashtags": ("site", "more hashtags than you allow", "drop the extra tags"),
    "site.emoji": ("site", "emoji, which you turned off", "drop the emoji"),
    "rhythm.openings": ("rhythm", "sentences in a row that start the same way",
                        "merge two of them, or begin one with its action"),
    "voice.invented_i": ("voice", "speaks for you without your words",
                         "drop the first person: state it as the sources' fact, or cut it"),
    # round 2: what a post is for
    "claim.announced": ("claim", "announces its structure or counts its points",
                        "cut the announcement and make the first point a claim"),
    "claim.caveats": ("claim", "catalogues what is unknown, or stacks caveats",
                      "cut it: name the source once and trust the reader"),
    "claim.no_hook": ("claim", "the first sentence makes no claim, asks nothing, risks nothing",
                      "open on a claim, a prediction or a question the reader cares about"),
    "claim.sections": ("claim", "sections of near-equal length, like a template",
                       "let the angle shape it: merge or cut sections"),
    "claim.skeleton": ("claim", "the “What happened / Why it matters” skeleton",
                       "drop the template headings; let the angle carry the post"),
    "claim.restates": ("claim", "only restates the facts: why should the reader care?",
                       "say what you make of it: a claim, a prediction or a question"),
    # round 3: salt jabs at the thing, never at a person
    "salt.person": ("salt", "names a person the sources don't name",
                    "aim the wit at the thing, not a person: cut the name"),
}
STRONG_WEIGHT, WEAK_WEIGHT, TEXT_WEIGHT, SITE_WEIGHT = 8, 4, 6, 10


@dataclass
class Flag:
    start: int
    end: int
    rule: str
    text: str
    words: str
    fix: str
    group: str
    strength: str = "strong"
    scope: str = "span"

    def view(self) -> dict:
        return asdict(self)


# -- splitting ----------------------------------------------------------------------------------

_SENT = re.compile(r"[^.!?\n]+(?:[.!?]+[\"'”’)\]]*|$)", re.M)
_URL = re.compile(r"https?://\S+|www\.\S+")
_CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
_QUOTE = re.compile(r"\"[^\"\n]{1,400}\"|“[^”\n]{1,400}”")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF]")
_HASHTAG = re.compile(r"(?<![\w#])#[A-Za-z][\w]{1,60}")
_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")


def sentences(text: str) -> list[tuple[int, int]]:
    """Sentence spans (start, end), without the leading blanks; a heading or list line counts
    as its own sentence."""
    raw: list[list[int]] = []
    for m in _SENT.finditer(text):
        s, e = m.start(), m.end()
        while s < e and text[s] in " \t":
            s += 1
        frag = text[s:e].strip()
        if not frag:
            continue
        # "2 a.m.", "e.g.", "U.S.": a full stop after an abbreviation, or one followed by a
        # lower-case word on the same line, does not end the sentence
        if raw and "\n" not in text[raw[-1][1]:s] and (
                _ABBREV.search(text[raw[-1][0]:raw[-1][1]]) or re.match(r"[a-z,;)]", frag)):
            raw[-1][1] = e
            continue
        raw.append([s, e])
    return [(s, e) for s, e in raw if _WORD.search(text[s:e])]


_ABBREV = re.compile(r"(?:\b[A-Za-z]\.|\b(?:e\.g|i\.e|vs|etc|Mr|Mrs|Ms|Dr|St|No|approx)\.)\s*\Z")


def sentence_lengths(text: str) -> list[int]:
    return [len(_WORD.findall(text[s:e])) for s, e in sentences(_prose_only(text))]


def paragraphs(text: str) -> list[tuple[int, int]]:
    """Paragraphs of prose (spans): not headings, list items, code or a line of links."""
    out = []
    for m in re.finditer(r"(?:[^\n]+\n?)+", text):
        block = m.group(0).strip()
        if not block or block.startswith(("#", "- ", "* ", "```", "> ")) or re.match(
                r"\d+\.\s", block) or not _WORD.search(_URL.sub("", block)):
            continue
        out.append((m.start(), m.start() + len(m.group(0).rstrip())))
    return out


def _prose_only(text: str) -> str:
    """The text with code and URLs blanked (offsets kept)."""
    def blank(m: re.Match) -> str:
        return " " * len(m.group(0))
    return _URL.sub(blank, _CODE.sub(blank, text))


def dash_spans(text: str) -> list[tuple[int, int]]:
    """Dashes used as a joint: an em dash, a spaced en dash (an unspaced one is a range:
    9–5, Monday–Friday), a spaced ``--`` or a spaced hyphen."""
    t = _prose_only(text)
    out = [(m.start(), m.end()) for m in re.finditer(r"—| – | -- | - ", t)]
    return sorted(set(out))


def words_in(text: str) -> int:
    return len(_WORD.findall(_prose_only(text)))


# -- the reading level (Flesch-Kincaid grade, with a syllable guess) ---------------------------


def _syllables(word: str) -> int:
    w = word.lower().strip("'’-")
    if len(w) <= 3:
        return 1
    w = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", w)
    w = re.sub(r"^y", "", w)
    return max(1, len(re.findall(r"[aeiouy]{1,2}", w)))


def grade(text: str) -> float | None:
    t = _prose_only(text)
    ws = _WORD.findall(t)
    ss = sentences(t)
    if len(ws) < 30 or not ss:
        return None
    syl = sum(_syllables(w) for w in ws)
    return round(0.39 * len(ws) / len(ss) + 11.8 * syl / len(ws) - 15.59, 1)


# -- the shapes ---------------------------------------------------------------------------------

_I = re.IGNORECASE
_SUBJ = r"(?:it|this|that|he|she|they|which)"
_NEG = r"(?:'s not|’s not| is not| isn't| isn’t|'re not| are not| aren't| aren’t| was not| " \
       r"wasn't| wasn’t)"
_POS = r"(?:'s|’s| is|'re|’re| are| was)"
NOT_X_BUT_Y = (
    # not just / not only / not merely X ... but Y
    re.compile(r"\bnot\s+(?:just|only|merely|simply)\b[^.!?\n]{1,80}?\bbut\b", _I),
    # it's not X, it's Y  /  this isn't about X; it's about Y
    re.compile(rf"\b{_SUBJ}{_NEG}\s+[^.!?\n,;:]{{1,60}}?[,;:]\s*{_SUBJ}{_POS}\b", _I),
    re.compile(rf"\b{_SUBJ}{_NEG}\s+[^.!?\n,;:]{{1,60}}?\s[—–]\s*{_SUBJ}{_POS}\b", _I),
    # the same split across two sentences
    re.compile(rf"\b{_SUBJ}{_NEG}\s+(?:just\s+|only\s+|really\s+)?(?:about\s+)?"
               rf"[^.!?\n]{{1,60}}[.!?]\s+{_SUBJ}{_POS}\s+(?:about\s+)?", _I),
    re.compile(r"\b(?:this|that|it) (?:does not|doesn't|doesn’t) mean\b[^.!?\n]{1,80}[.!?]\s+"
               r"(?:it|this|that) means\b", _I),
    # no X, no Y, just Z
    re.compile(r"\bno\s+\w+(?:\s\w+)?,\s+no\s+\w+(?:\s\w+)?[,.]?\s+(?:just|only)\b", _I),
)
CLOSERS = re.compile(
    r"\b(?:let that sink in|read that again|that'?s the (?:real |whole )?(?:win|point|lesson|"
    r"story|magic)|that changes everything|and that matters|that distinction matters|this "
    r"matters|make no mistake|full stop|period\.$|the rest is history|enough said|mic drop)\b",
    _I | re.M)
RUNUPS = re.compile(
    r"(?:^|(?<=[.!?:]\s)|(?<=\n))(?:but |so |and )?(?:here'?s the (?:thing|deal|kicker|catch|"
    r"twist|truth)|here'?s (?:why|what|how)\b|the thing is|let'?s (?:dive in|dive into|break "
    r"(?:it|this) down|explore|unpack|be honest)|honestly\?|real talk|without further ado|buckle "
    r"up|spoiler alert|plot twist|(?:the|and the|so the|but the) (?:result|answer|catch|kicker|"
    r"twist|takeaway|verdict|upshot|best part|truth|reason)\?)", _I | re.M)
ING_TAIL = re.compile(
    r",\s+(?:highlighting|underscoring|emphasi[sz]ing|reflecting|symboli[sz]ing|showcasing|"
    r"signall?ing|marking (?:a|an|the)|cementing|solidifying|demonstrating|illustrating|paving "
    r"the way|setting the stage|ensuring|fostering|contributing to|underlining|reinforcing|"
    r"positioning (?:it|them|itself)|making it (?:a|an|the) (?:key|vital|crucial|essential|"
    r"pivotal))\b[^.!?\n]*[.!?]?", _I)
MORAL_START = re.compile(
    r"^(?:ultimately|in the end|at the end of the day|in conclusion|in short|in summary|to sum "
    r"up|the lesson|the takeaway|the bottom line|the message is clear|one thing is clear|what "
    r"this (?:shows|means|tells us))\b", _I)
MORAL_ANY = re.compile(
    r"\b(?:(?:it'?s|this is|that'?s|serves as|stands as) a (?:powerful |timely |stark |good |"
    r"humbling )?reminder|remind(?:s|ed)? us (?:that|of|all)|the future (?:looks|is) bright|only "
    r"time will tell|exciting times|as we (?:move|look) (?:forward|ahead)|a step in the right "
    r"direction|the possibilities are endless|we all have a role to play)\b", _I)
_TRIAD = re.compile(r"\b[\w'’-]+(?:\s[\w'’-]+){0,2},\s[\w'’-]+(?:\s[\w'’-]+){0,2},?\s(?:and|or)"
                    r"\s[\w'’-]+(?:\s[\w'’-]+){0,2}\b")
# first person, case-sensitive: "I" is always a capital, and "US" (the country) is not "us"
_FIRST = re.compile(r"\b(?:I|I'm|I’m|I've|I’ve|I'd|I’d|I'll|I’ll|[Mm]e|[Mm]y|[Mm]ine|"
                    r"[Mm]yself)\b|\b(?:[Ww]e|[Ww]e've|[Ww]e’ve|[Oo]ur|us)\b")
_STOP = frozenset((
    "a", "an", "the", "and", "or", "but", "if", "then", "so", "of", "to", "in", "on", "at",
    "by", "for", "with", "from", "as", "is", "are", "was", "were", "be", "been", "being", "it",
    "its", "this", "that", "these", "those", "i", "me", "my", "we", "our", "you", "your", "he",
    "she", "they", "them", "their", "his", "her", "not", "no", "yes", "do", "does", "did",
    "have", "has", "had", "will", "would", "can", "could", "should", "may", "might", "just",
    "very", "really", "also", "about", "into", "over", "than", "more", "most", "some", "any",
    "all", "one", "two", "new", "what", "which", "who", "when", "where", "why", "how", "there",
    "here", "up", "out"))


def _content(text: str) -> set[str]:
    return {w.lower().strip("'’-") for w in _WORD.findall(text)
            if len(w) > 2 and w.lower() not in _STOP}


# an experience: something the person did or lived (P-10: never invented, whatever the angle)
EXPERIENCE = re.compile(
    r"\b(?:I|we)(?:'ve|’ve| have)? (?:tried|tested|used|ran|run|built|shipped|saw|seen|watched|"
    r"worked|spent|bought|installed|switched|deployed|measured|met|visited|talked|spoke|"
    r"learned|been (?:using|running|bitten|burned|testing|building))\b"
    r"|\b(?:at|in) (?:my|our) (?:company|job|work|team|startup|shop|lab|day job|last job)\b"
    r"|\b(?:in|from) my (?:own )?experience\b|\bwhen I (?:worked|was at|ran|built)\b"
    r"|\b(?:my|our) (?:team|company|customers|clients|users|startup)\b")
# a stance in the first person ("My bet:", "I think", "What I'd watch"): the angle's to carry
# (P-10), so allowed when the piece has an angle; never an experience
STANCE_FIRST = re.compile(
    r"\b(?:I think|I bet|I'd bet|I’d bet|my bet|I expect|my guess|I'd guess|I’d guess|"
    r"I'd watch|I’d watch|I suspect|I doubt|I'm betting|I’m betting|I'd argue|I’d argue|"
    r"I believe|I take (?:that|this) as|I read (?:that|this) as|my read|my money|"
    r"I'd like to see|I’d like to see|I'd want|I’d want|how I read|the way I read)\b", _I)


def invented_first_person(text: str, allowed: list[str],
                          lived: str | None = None) -> list[tuple[int, int]]:
    """Sentences that speak as the person (I, my, we…) with nothing behind them in what they
    wrote (their take, their samples): fewer than two of the sentence's content words appear
    there. A sentence that tells an experience ("I tried…", "at my company…") needs more: an
    experience in ``lived`` (the take or angle for this piece; by default the first of
    ``allowed``) that shares two of its content words, since a sample's experience is about
    something else. With an angle, a first-person stance ("My bet:", "I think") is the angle's
    and allowed (P-10). Quoted speech is not theirs to answer for and is skipped."""
    pool: set[str] = set()
    for a in allowed:
        pool |= _content(a or "")
    own = (allowed[0] if allowed else "") if lived is None else lived
    own = own or ""
    own_words = _content(own) if EXPERIENCE.search(own) else set()
    t = _QUOTE.sub(lambda m: " " * len(m.group(0)), _prose_only(text))
    out = []
    for s, e in sentences(t):
        sent = t[s:e]
        if not _FIRST.search(sent):
            continue
        # "I" alone at a sentence's start in a heading list ("I. Intro") is not a claim
        if re.fullmatch(r"\s*I\.\s*", sent):
            continue
        words = _content(sent)
        if EXPERIENCE.search(sent):
            if len(words & own_words) < 2:
                out.append((s, e))
            continue
        if own.strip() and STANCE_FIRST.search(sent):
            continue                      # the angle's stance, said as theirs (P-10)
        if len(words & pool) < 2:
            out.append((s, e))
    return out


# -- check --------------------------------------------------------------------------------------


def _protected(text: str, keep: tuple[str, ...]) -> list[tuple[int, int]]:
    spans = [(m.start(), m.end()) for r in (_URL, _CODE, _QUOTE) for m in r.finditer(text)]
    for k in keep:
        pat = _entry(k)
        if pat is not None:
            spans += [(m.start(), m.end()) for m in pat.finditer(text)]
    return spans


def _entry(entry: str) -> re.Pattern | None:
    """A list entry as a pattern: ``/regex/``, or words matched whole and case-blind."""
    e = entry.strip()
    if not e:
        return None
    if len(e) > 2 and e.startswith("/") and e.endswith("/"):
        try:
            return re.compile(e[1:-1], _I)
        except re.error:
            return None
    return re.compile(r"(?<![\w])" + re.escape(e) + r"(?![\w])", _I)


def _overlaps(a: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    return any(a[0] < e and s < a[1] for s, e in spans)


def _graphemes(text: str) -> int:
    return sum(1 for ch in text if not unicodedata.combining(ch) and ch not in "‍️")


def site_length(text: str, unit: str) -> int:
    if "23" in unit:
        return len(_URL.sub("x" * 23, text))
    if unit == "graphemes":
        return _graphemes(text)
    return len(text)


def check(text: str, site: str | None = None, profile: Profile | None = None, *,
          kind: str | None = None, limits: dict | None = None, take: str | None = None,
          strictness: str | None = None, sources: str | None = None) -> dict:
    """``{score, verdict, flags[], counts, grade}`` for a piece of text.

    ``limits`` overrides the site's (SOCIAL passes its registry's: ``max_chars``, ``unit``,
    ``links``, ``hashtags``, ``max_words``). ``take`` is the person's own line for this piece,
    when given: with it (even empty) a first-person sentence that neither the take nor a sample
    supports is flagged (P-5). ``strictness`` overrides the profile's. ``sources``: the
    material the post was written from; with it, a person's name or a handle the material does
    not have is flagged (``salt.person``: salt jabs at the thing, never at a private person)."""
    p = profile or default()
    level = strictness or p.strictness
    text = text or ""
    lim = {**SITE_LIMITS.get(site or "", {}), **(limits or {})}
    flags: list[Flag] = []
    keep = _protected(text, p.keep)
    off = set(p.rules_off)

    def add(rule: str, s: int, e: int, *, strength: str = "strong", scope: str = "span",
            fix: str | None = None, words: str | None = None, protect: bool = True) -> None:
        if rule in off:
            return
        if scope == "span" and protect and _overlaps((s, e), keep):
            return
        group, w, f = RULES[rule]
        flags.append(Flag(s, e, rule, text[s:e], words or w, fix or f, group, strength, scope))

    if level != "off":
        _words(text, p, level, add)
        _shapes(text, level, add)
        _rhythm(text, p, level, add)
        _claims(text, kind, site, add)
        g = grade(text)
        target = int(p.switches.get("grade", 8))
        if g is not None and g > target + (2 if level == "strict" else 4):
            add("reading.level", 0, len(text), scope="text",
                words=f"reads at grade {g:g}; your level is {target}")
        if take is not None and p.switches.get("opinions", "mine") == "mine":
            for s, e in invented_first_person(text, [take, *(x.text for x in p.samples)]):
                add("voice.invented_i", s, e, protect=False)
    if sources is not None:
        for s, e in people_not_in(text, sources):
            add("salt.person", s, e, protect=False)
    _site(text, p, lim, add)
    flags.sort(key=lambda f: (f.start, f.end, f.rule))
    flags = _dedupe(flags)
    score = 100
    for f in flags:
        score -= (SITE_WEIGHT if f.group == "site" else TEXT_WEIGHT if f.scope == "text"
                  else STRONG_WEIGHT if f.strength == "strong" else WEAK_WEIGHT)
    n = len([f for f in flags if f.group != "site"])
    over = len(flags) - n
    if not flags:
        verdict = "Reads natural"
    else:
        parts = []
        if n:
            parts.append(f"{n} thing{'s' if n != 1 else ''} read{'' if n != 1 else 's'} like AI")
        if over:
            parts.append(f"{over} break{'' if over != 1 else 's'} the site's limits")
        verdict = "; ".join(parts) + ": fix them"
    counts: dict[str, int] = {}
    for f in flags:
        counts[f.rule] = counts.get(f.rule, 0) + 1
    return {"score": max(0, score), "verdict": verdict, "flags": [f.view() for f in flags],
            "counts": counts, "grade": grade(text), "words": words_in(text),
            "strictness": level, "site": site, "kind": kind}


# a person's name. A capitalised word: "Altman", "Jean-Luc", and an inner capital ("McCarthy",
# "DeVos", "O'Brien"). A name: two or three of them in a row, a middle initial or a lower-case
# particle allowed between ("Dario Amodei", "John Q. Public", "Ian de Villiers", "Ludwig van
# Beethoven"); or one word after a title ("Dr. Patel") or next to a verb of saying ("Altman
# said", "said Altman", "according to Altman"); or a handle ("@name", "@name@server"). The first
# word is not one a sentence or a heading often starts with.
_W = r"[A-Z][a-z'’-]*(?:[A-Z][a-z'’-]+)*(?<=[a-z'’])"
_PARTICLE = r"(?:de|del|della|der|den|di|da|dos|das|du|la|le|van|von|ten|ter|bin|ibn|al)"
_NAME = re.compile(rf"(?<![\w@])(?:{_W}(?:\s(?:[A-Z]\.\s)?(?:{_PARTICLE}\s)?{_W}){{1,2}}"
                   r"|@[A-Za-z0-9_]{2,30}(?:@[\w.-]+)?)(?![\w’'])")
_TITLES = r"(?:Mr|Mrs|Ms|Mx|Dr|Prof|Sir|Dame|Lord|Lady|Rev|Judge|Senator|Rep)"
_SAYING = (r"(?:said|says|told|tells|wrote|writes|argued|argues|claimed|claims|tweeted|posted|"
           r"admitted|insisted|thinks|believes|warned|warns|joked|quipped|added|replied|noted)")
_ONE = re.compile(rf"(?:\b{_TITLES}\.?\s+(?P<a>{_W})(?![\w’'])"
                  rf"|(?<![\w@])(?P<b>{_W})\s+{_SAYING}\b"
                  rf"|\b(?:{_SAYING}|[Aa]ccording\sto|asked|per)\s+(?P<c>{_W})(?![\w’']))")
_NOT_FIRST_WORDS = """The A An This That These Those My Our Your Their His Her Its If When
While What Why How Who Where Which And But Or So Then Now Here There Every Each Some Most Many
Few No Not One Two Three First Next Last In On At For From With Without By Of To As After Before
Since Until Because Although Though Even Still Yet Just Only Also More Less Both Either Neither
I We You They He She It Is Are Was Were Be Do Does Did Has Have Had Can Could Will Would Should
May Might Must Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March
April May June July August September October November December Nobody Everyone Someone Anyone
Everybody Somebody Me Him Us Them"""
_NOT_FIRST = frozenset(_NOT_FIRST_WORDS.split())
# a second word that names a place, a product or an organisation, not a person ("New York",
# "Visual Studio", "Open Source"): a two-word term ending in one is not read as a name
_NOT_LAST_WORDS = """York Jersey Zealand Delhi Orleans Mexico Studio Code Valley Street Labs Lab
Inc Ltd Corp Cloud Bank Times News Post Journal Review University College Institute School
Foundation Act Store Pro Max Ultra Mini Plus Edition Kit Hub Web Search Maps Docs Drive Pay
Source Weekly Daily Group Council Office House Court Party Union States Kingdom Republic City
Island Islands Bay Park Square Center Centre Airlines Motors Systems Software Games Studios"""
_NOT_LAST = frozenset(_NOT_LAST_WORDS.split())


def _capitalised(line: str) -> set[str]:
    return {w.lower() for w in re.findall(_W, line)}


def people_not_in(text: str, sources: str) -> list[tuple[int, int]]:
    """Spans of ``text`` that look like a person's name or a handle and that ``sources`` does
    not contain (case-insensitive): a salty post may name the companies, products and public
    sources its material names, and nobody else. A two-word term whose two words both stand
    capitalised in the material's title (its first line) is the title's, not a person.

    What it still misses (said so in the docs): a name in all capitals or by initials ("DHH",
    "J. K. Rowling"), a one-word name with no title and no verb of saying beside it ("blame
    Altman"), a name that is not capitalised, a person named only by role ("their CEO"). What
    it may still flag: an organisation or product of two capitalised words the material does not
    name and that does not end in a word of ``_NOT_LAST``, and a one-word company next to a verb
    of saying ("Google said") that the sources do not name."""
    have = " ".join(sources.split()).lower()
    title = _capitalised((sources.strip().splitlines() or [""])[0])
    out: list[tuple[int, int]] = []

    def keep(name: str, start: int, end: int) -> None:
        name = re.sub(r"['’]s\Z", "", name)        # "Google DeepMind's": the name, not its 's
        words = name.split()
        if not name.startswith("@") and (words[0] in _NOT_FIRST or words[-1] in _NOT_FIRST):
            return
        if " ".join(words).lower() in have:
            return
        if len(words) == 2 and (words[-1] in _NOT_LAST
                                or all(w.lower() in title for w in words)):
            return
        if any(s < end and start < e for s, e in out):
            return
        out.append((start, end))

    for m in _NAME.finditer(text):
        name, start = m.group(0), m.start()
        words = name.split()
        if len(words) >= 3 and not re.fullmatch(_PARTICLE, words[1]) \
                and (start == 0 or re.search(r"[.!?]\s+\Z", text[:start])):
            # "Somewhere Dario Amodei": a sentence's first word is not part of the name
            start += len(words[0]) + 1
            name = " ".join(words[1:])
        keep(name, start, m.end())
    for m in _ONE.finditer(text):
        g = next(k for k in ("a", "b", "c") if m.group(k))
        s, e = m.start(g), m.end(g)
        if g != "a" and (re.search(r"[A-Z][\w'’-]*\s\Z", text[:s])
                         or re.match(r"\s[A-Z]", text[e:])):
            continue             # one word of a longer capitalised term ("Claude Code said")
        keep(m.group(g), s, e)
    out.sort()
    return out


def _dedupe(flags: list[Flag]) -> list[Flag]:
    """One flag per span and rule; a word flag inside a shape flag's span is kept (it names a
    different fix)."""
    seen, out = set(), []
    for f in flags:
        k = (f.start, f.end, f.rule)
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out


def _words(text: str, p: Profile, level: str, add) -> None:
    t = _prose_only(text)
    for pat, plain, _src, strength in FLOOR_WORDS:
        if strength == "weak" and level != "strict":
            continue
        for m in re.finditer(r"(?<![\w-])(?:" + pat + r")(?![\w-])", t, _I):
            add("words.floor", m.start(), m.end(), strength=strength,
                fix=f"use the plain word: {plain}")
    for entry in p.never:
        rx = _entry(entry)
        if rx is None:
            continue
        for m in rx.finditer(t):
            if m.end() > m.start():
                add("words.never", m.start(), m.end())
    for pat, rule, fix in FLOOR_PHRASES:
        for m in re.finditer(r"\b" + pat + r"\b", t, _I):
            add(f"phrase.{rule}", m.start(), m.end(), fix=fix)


def _shapes(text: str, level: str, add) -> None:
    t = _prose_only(text)
    for rx in NOT_X_BUT_Y:
        for m in rx.finditer(t):
            add("shape.not_x_but_y", m.start(), m.end())
    for m in CLOSERS.finditer(t):
        add("shape.closer", m.start(), m.end())
    for m in RUNUPS.finditer(t):
        add("shape.runup", m.start(), m.end())
    for m in ING_TAIL.finditer(t):
        add("shape.ing_tail", m.start(), m.end())
    for m in MORAL_ANY.finditer(t):
        add("shape.moral", m.start(), m.end())
    paras = paragraphs(t)
    if paras:
        last = paras[-1]
        for s, e in sentences(t[last[0]:last[1]]):
            if MORAL_START.match(t[last[0] + s:last[0] + e]):
                add("shape.moral", last[0] + s, last[0] + e)
    # a one-line closer by its shape: the last paragraph is one short sentence that points
    # back ("That changes everything."), after at least two paragraphs or three sentences
    sents = sentences(t)
    if len(sents) >= 3:
        s, e = sents[-1]
        last_sent = t[s:e].strip()
        nwords = len(_WORD.findall(last_sent))
        alone = not paras or (len(paras) >= 2 and paras[-1][0] <= s and
                              len(sentences(t[paras[-1][0]:paras[-1][1]])) == 1)
        if nwords <= 6 and alone and re.match(r"(?:that|this|and that|which|so|now|it|"
                                              r"and)\b", last_sent, _I):
            add("shape.closer", s, e)
    # a row of fragments: three sentences in a row of at most three words
    run: list[tuple[int, int]] = []
    for s, e in sents:
        if len(_WORD.findall(t[s:e])) <= 3 and not t[s:e].strip().startswith("#"):
            run.append((s, e))
            if len(run) >= 3:
                add("shape.closer", run[0][0], run[-1][1],
                    words="a row of fragments", fix="merge them into one sentence with a claim")
        else:
            run = []
    # lists of three: a run is two in a short piece, or three in any
    triads = [(m.start(), m.end()) for m in _TRIAD.finditer(t)]
    nwords = words_in(text)
    need = 2 if nwords < 400 else 3
    if level == "strict":
        need = 2
    if len(triads) >= need:
        for s, e in triads:
            add("shape.tricolon", s, e)


def _rhythm(text: str, p: Profile, level: str, add) -> None:
    t = _prose_only(text)
    nwords = max(words_in(text), 1)
    r = p.rhythm()
    dashes = dash_spans(text)
    if dashes:
        rate = 100 * len(dashes) / nwords
        own = r["dashes_per_100"] if r else 0.0
        # one dash is weak alone (Humanizer): light flags a text full of them (three or
        # more, over one in a hundred words); strict flags any above the person's own rate
        allowed = max(own * 1.5, 0.0 if level == "strict" else 1.0)
        if rate > allowed and (len(dashes) >= 3 or level == "strict"):
            for s, e in dashes:
                add("rhythm.dashes", s, e, strength="weak" if own else "strong")
    paras = paragraphs(t)
    lens = [len(_WORD.findall(t[s:e])) for s, e in paras]
    if len(lens) >= 4 and min(lens) >= 15:
        cv = _cv(lens)
        if cv < (0.2 if level == "strict" else 0.15):
            add("rhythm.paragraphs", 0, len(text), scope="text",
                words=f"{len(lens)} paragraphs of {min(lens)} to {max(lens)} words")
    # three sentences in a row opening on the same word (Humanizer): "It… It… It…"
    spans = sentences(t)
    firsts = [(_WORD.findall(t[s:e])[:1] or [""])[0].lower() for s, e in spans]
    i = 0
    while i < len(spans):
        j = i
        while j + 1 < len(spans) and firsts[j + 1] and firsts[j + 1] == firsts[i]:
            j += 1
        if firsts[i] and j - i >= 2:
            add("rhythm.openings", spans[i][0], spans[j][1],
                words=f"{j - i + 1} sentences in a row start with “{firsts[i]}”")
        i = j + 1
    sl = [len(_WORD.findall(t[s:e])) for s, e in spans]
    sl = [x for x in sl if x > 0]
    if len(sl) >= 6:
        cv = _cv(sl)
        if cv < (0.25 if level == "strict" else 0.2):
            add("rhythm.sentences", 0, len(text), scope="text",
                words=f"{len(sl)} sentences of {min(sl)} to {max(sl)} words")
        if r and r["mean"] > 0:
            mean = sum(sl) / len(sl)
            hi, lo = (1.4, 0.6) if level == "strict" else (1.6, 0.5)
            if mean > r["mean"] * hi or mean < r["mean"] * lo:
                add("rhythm.voice", 0, len(text), scope="text",
                    words=f"sentences average {mean:.0f} words; yours average {r['mean']:.0f}")


# -- round 2: a post makes a claim (rules 1, 2, 5 and 6) ---------------------

_NUMWORD = r"(?:two|three|four|five|six|seven|\d)"
ANNOUNCED = re.compile(
    # "Three things point in this direction." / "There are four reasons…" / "Here are two…"
    rf"(?:^|(?<=[.!?:]\s)|(?<=\n))(?:(?:there are|here are|i see|i have|we have) )?{_NUMWORD} "
    r"(?:things|reasons|points|lessons|takeaways|signals|questions|facts|trends|ways|details|"
    r"parts|ideas|problems|changes|stand-?outs|observations)\b[^.!?\n]*[.!?:]?"
    # "A few open questions come to mind" / "Let me walk through…" / "In this post…"
    r"|\b(?:a few|several|some) (?:open )?questions (?:come to mind|remain|stand out)[^.!?\n]*"
    r"[.!?:]?|\bin this post,? (?:i|we)(?:'ll| will)\b[^.!?\n]*[.!?]?"
    r"|\blet(?:'s| me| us) (?:walk|go) through\b[^.!?\n]*[.!?]?", _I | re.M)
ORDINAL = re.compile(r"(?:^|(?<=[.!?]\s)|(?<=\n))(?:first(?:ly)?|second(?:ly)?|third(?:ly)?|"
                     r"fourth|finally|lastly)\b,?", _I | re.M)
# what is unknown, catalogued: always a flag (rule 2: "it's implied")
UNKNOWN = re.compile(
    r"\b(?:the (?:sources?|items?|posts?|cards?|reports?|articles?|announcements?|"
    r"write-?ups?) (?:give|gives|offer|offers|provide|provides|has|have) no (?:details?|"
    r"numbers|figures|data)"
    r"|the (?:sources?|items?|posts?|cards?|reports?|articles?|announcements?) (?:does|do|"
    r"did)(?: not|n't|n’t) (?:say|describe|mention|give|explain|specify|answer|detail|"
    r"address)"
    r"|(?:no|few) details beyond|what we (?:don't|don’t|do not) (?:yet )?know"
    r"|a lot is missing|the item is short|the honest reading|worth keeping in mind"
    r"|worth treating as a claim|until a fuller (?:write-?up|account|report)"
    r"|is not (?:yet )?clear from the sources|the sources (?:are|stay) silent)\b", _I)
# a caveat: a flag only when there is more than one in the piece (rule 2: one at most)
HEDGE = re.compile(
    r"\b(?:self-reported|reportedly|unverified|not (?:yet )?independently (?:verified|"
    r"confirmed|tested)|at least as described|as described|take (?:it|this) with a grain|"
    r"(?:a|one) single (?:decision|result|demo|case|study|paper|post) (?:does not|doesn't|"
    r"doesn’t|cannot|can't)|it is (?:too )?early to|it's (?:too )?early to|one caveat|"
    r"a caveat|to be fair|of course,|that said,|if (?:that|this) reading is right|if (?:this|"
    r"that|it) holds(?: up)?)", _I)
SKELETON = re.compile(
    r"^(?:#{1,4}\s*|\*\*)\s*(?:what happened|why (?:it|this) (?:may |might )?matters?|why it "
    r"may matter|the idea|what the sources (?:show|say)|what we (?:don't|don’t|do not) know"
    r"(?: yet)?|open questions|the stated worry|the bottom line|background|key (?:points|"
    r"takeaways)|takeaways?|the details|what stands out|what i'?d watch(?: for)?|the context|"
    r"summary|in short)\b[^\n]*$", _I | re.M)
# what makes a sentence a claim, a question or a stake (rules 1 and 5): a question, the reader
# or the writer in it, a forecast, or a judgement. A fact joined by "but" or "not" is still a
# fact ("It reports 36% success, but pretraining included robot data").
STANCE = re.compile(
    r"\?|\b(?:you|your|you're|you’re|you'll|you’ll|i|i'm|i’m|i'd|i’d|i've|i’ve|my|we|we're|"
    r"we’re|our)\b"
    r"|\b(?:will|would|could|should|might|must|can't|can’t|cannot|won't|won’t|wouldn't|"
    r"wouldn’t|shouldn't|shouldn’t|no one|nobody|never|nothing|none|bet|guess|expect|"
    r"predict|wrong|mistake|problem|risk|cheap|cheaper|costly|expensive|easier|harder|better|"
    r"worse|best|worst|bigger|smaller|more than|less than|finally|first time|end of|real|"
    r"forget|stop|bad|good|threat|bottleneck|overrated|underrated|surprising|matters|bold|"
    r"soon|next|bigger deal|the point)\b", _I)
# a first sentence may also hook by denying what the reader assumes ("China didn't block this
# deal over robots."): a negation counts there, though not for a whole post's stance
DENIAL = re.compile(r"\b(?:not|no longer|isn't|isn’t|aren't|aren’t|wasn't|wasn’t|didn't|"
                    r"didn’t|doesn't|doesn’t|don't|don’t|hasn't|hasn’t)\b", _I)
_HEADING = re.compile(r"^\s*(?:#{1,6}\s|\*\*[^*\n]+\*\*\s*$)")


def _body_sentences(t: str) -> list[tuple[int, int]]:
    """Sentences of prose: not a heading or a bold label line."""
    out = []
    for s, e in sentences(t):
        line_start = t.rfind("\n", 0, s) + 1
        line_end = t.find("\n", s)
        line = t[line_start:line_end if line_end >= 0 else len(t)]
        if _HEADING.match(line):
            continue
        out.append((s, e))
    return out


def _stance(sentence: str) -> bool:
    return bool(STANCE.search(_QUOTE.sub(" ", sentence)))


def _claims(text: str, kind: str | None, site: str | None, add) -> None:
    """The round-2 flags: announced structure and counted lists, catalogued unknowns and
    stacked caveats, a first sentence with no claim, a template's sections and skeleton, and a
    post that only restates its facts. A newsletter's opening, a weekly intro and a text with
    neither a site nor a kind are not posts of their own: they are checked for the first two
    only."""
    t = _prose_only(text)
    for m in ANNOUNCED.finditer(t):
        add("claim.announced", m.start(), m.end())
    ordinals = list(ORDINAL.finditer(t))
    if len(ordinals) >= 2:
        for m in ordinals:
            add("claim.announced", m.start(), m.end(), words="counts its points (“First, …”)")
    sents = sentences(t)
    for m in UNKNOWN.finditer(t):
        # the whole sentence: what it says is missing goes with it (a cut phrase leaves a
        # broken one: "… what the failures look like.")
        s, e = next(((a, b) for a, b in sents if a <= m.start() < b), (m.start(), m.end()))
        add("claim.caveats", s, max(e, m.end()))
    hedges = list(HEDGE.finditer(t))
    if len(hedges) + len(UNKNOWN.findall(t)) >= 2:
        for m in hedges:
            add("claim.caveats", m.start(), m.end(), words="more than one caveat")
    if kind == "intro" or site == "newsletter" or (kind is None and site is None):
        return                      # not a post of its own, or not said to be a post
    skeleton = list(SKELETON.finditer(t))
    if len(skeleton) >= 2 or any(re.search(r"why (?:it|this) (?:may |might )?matters?",
                                           m.group(0), _I) for m in skeleton):
        for m in skeleton:
            add("claim.skeleton", m.start(), m.end())
    body = _body_sentences(t)
    if body:
        s, e = body[0]
        if not _stance(t[s:e]) and not DENIAL.search(_QUOTE.sub(" ", t[s:e])):
            add("claim.no_hook", s, e)
        if not any(_stance(t[a:b]) for a, b in body):
            add("claim.restates", 0, len(text), scope="text")
    sections = _sections(t)
    if len(sections) >= 3 and min(sections) >= 20 and _cv(sections) < 0.3:
        add("claim.sections", 0, len(text), scope="text",
            words=f"{len(sections)} sections of {min(sections)} to {max(sections)} words")


def _sections(t: str) -> list[int]:
    """Words per section, a section running from one heading (``#`` or a bold label line) to
    the next; the text before the first heading counts when it has words."""
    parts = re.split(r"(?m)^\s*(?:#{1,6}\s[^\n]*|\*\*[^*\n]+\*\*\s*)$", t)
    if len(parts) < 3:
        return []
    counts = [len(_WORD.findall(p)) for p in parts]
    return [c for i, c in enumerate(counts) if c or i]


def _cv(xs: list[int]) -> float:
    m = sum(xs) / len(xs)
    if m == 0:
        return 0.0
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs)) / m


def _site(text: str, p: Profile, lim: dict, add) -> None:
    max_chars, unit = lim.get("max_chars"), str(lim.get("unit") or "characters")
    if isinstance(max_chars, int):
        n = site_length(text, unit)
        if n > max_chars:
            add("site.length", 0, len(text), scope="text", protect=False,
                words=f"{n} {unit.split(',')[0]}; the site takes {max_chars}")
    max_words = lim.get("max_words")
    if isinstance(max_words, int):
        n = words_in(text)
        if n > max_words:
            add("site.length", 0, len(text), scope="text", protect=False,
                words=f"{n} words; at most {max_words}")
    links = lim.get("links")
    if isinstance(links, int):
        urls = list(_URL.finditer(text))
        for m in urls[links:]:
            add("site.links", m.start(), m.end(), protect=False)
    tags = list(_HASHTAG.finditer(_CODE.sub(lambda m: " " * len(m.group(0)), text)))
    allowed = 0 if p.switches.get("hashtags") == "never" else lim.get("hashtags")
    if isinstance(allowed, int):
        for m in tags[allowed:]:
            add("site.hashtags", m.start(), m.end(), protect=False)
    if p.switches.get("emoji", "never") == "never":
        for m in _EMOJI.finditer(text):
            add("site.emoji", m.start(), m.end(), protect=False)
