"""The floor's never-list: words that read like a model wherever they appear in a post.

Each entry is ``(pattern, plain word, source, strength)``. ``pattern`` is a regular expression
over one word (its forms included), matched whole-word and case-blind. ``source`` credits where
the word comes from (NOTICE): ``humanizer`` (Humanizer's SKILL.md),
``slop-forensics`` (its general and essays lists; fiction words and names are left out) or
``kranto`` (hype words,). ``strength``: ``strong`` words are flagged at every
strictness; ``weak`` ones (with honest literal uses: a robust test, a mountain landscape) only
when the checker is strict.
"""

from __future__ import annotations

FLOOR_WORDS: tuple[tuple[str, str, str, str], ...] = (
    # Humanizer (overused AI words), (sales language)
    (r"delv(?:e|es|ed|ing)", "look at, read", "humanizer", "strong"),
    (r"tapestr(?:y|ies)", "mix", "humanizer", "strong"),
    (r"testament", "sign, proof", "humanizer", "strong"),
    (r"pivotal", "important, or say why", "humanizer", "strong"),
    (r"crucial(?:ly)?", "important, or say why", "humanizer", "strong"),
    (r"underscor(?:e|es|ed|ing)", "show", "humanizer", "strong"),
    (r"showcas(?:e|es|ed|ing)", "show", "humanizer", "strong"),
    (r"intricac(?:y|ies)|intricate(?:ly)?", "detail, complex", "humanizer", "strong"),
    (r"meticulous(?:ly)?", "careful", "humanizer", "strong"),
    (r"vibrant", "lively, or cut", "humanizer", "strong"),
    (r"bolster(?:s|ed|ing)?", "support", "humanizer", "strong"),
    (r"garner(?:s|ed|ing)?", "get, win", "humanizer", "strong"),
    (r"interplay", "how they affect each other", "humanizer", "strong"),
    (r"nestled", "in, at", "humanizer", "strong"),
    (r"breathtaking", "say what it looks like", "humanizer", "strong"),
    (r"groundbreaking", "new, first", "humanizer", "strong"),
    (r"renowned", "known, or say for what", "humanizer", "strong"),
    (r"enduring", "lasting, or cut", "humanizer", "weak"),
    (r"robust(?:ly)?", "strong, reliable", "humanizer", "weak"),
    (r"landscape", "field, market", "humanizer", "weak"),
    (r"enhanc(?:e|es|ed|ing|ement)", "improve", "humanizer", "weak"),
    (r"profound(?:ly)?", "deep, or say how", "humanizer", "weak"),
    (r"additionally", "also", "humanizer", "strong"),
    # slop-forensics (general and essays lists)
    (r"multifaceted", "say which sides", "slop-forensics", "strong"),
    (r"seamless(?:ly)?", "smooth, or cut", "slop-forensics", "strong"),
    (r"holistic(?:ally)?", "whole", "slop-forensics", "strong"),
    (r"paradigms?", "model, way", "slop-forensics", "strong"),
    (r"transformative", "say what changed", "slop-forensics", "strong"),
    (r"unwavering", "steady", "slop-forensics", "strong"),
    (r"bustling", "busy", "slop-forensics", "strong"),
    (r"resonat(?:e|es|ed|ing)", "land with, matter to", "slop-forensics", "strong"),
    (r"leverag(?:e|es|ed|ing)", "use", "slop-forensics", "strong"),
    (r"fost(?:er|ers|ered|ering)", "help, build", "slop-forensics", "strong"),
    (r"streamlin(?:e|es|ed|ing)", "simplify", "slop-forensics", "strong"),
    (r"actionable", "useful, practical", "slop-forensics", "strong"),
    (r"indelible", "lasting", "slop-forensics", "strong"),
    (r"underpin(?:s|ned|ning)?", "support, sit under", "slop-forensics", "strong"),
    (r"moreover", "also, or cut", "slop-forensics", "strong"),
    (r"furthermore", "also, or cut", "slop-forensics", "strong"),
    (r"nuanced", "say what the nuance is", "slop-forensics", "weak"),
    (r"navigat(?:e|es|ed|ing)", "deal with, find a way through", "slop-forensics", "weak"),
    (r"amplif(?:y|ies|ied|ying)", "increase, spread", "slop-forensics", "weak"),
    (r"insights?", "finding, what it shows", "slop-forensics", "weak"),
    (r"elevat(?:e|es|ed|ing)", "raise, improve", "slop-forensics", "weak"),
    (r"ever-evolving|evolving landscape", "changing", "slop-forensics", "strong"),
    # Kranto: hype and launch words (help makes writers sound more positive)
    (r"game[- ]?chang(?:er|ers|ing)", "say what changed", "kranto", "strong"),
    (r"revolutioni[sz](?:e|es|ed|ing)", "change", "kranto", "strong"),
    (r"unleash(?:es|ed|ing)?", "release, let", "kranto", "strong"),
    (r"unlock(?:s|ed|ing)?", "allow, open", "kranto", "weak"),
    (r"empower(?:s|ed|ing|ment)?", "let, help", "kranto", "strong"),
    (r"harness(?:es|ed|ing)?", "use", "kranto", "weak"),
    (r"cutting[- ]edge", "new, latest", "kranto", "strong"),
    (r"synerg(?:y|ies|istic)", "say how they work together", "kranto", "strong"),
    (r"realms?", "field, area", "kranto", "strong"),
    (r"mind[- ]blowing", "say what surprised", "kranto", "strong"),
    (r"thrilled", "glad, or cut", "kranto", "strong"),
    (r"must[- ]read", "worth reading, or cut", "kranto", "strong"),
    (r"journey", "path, or say what happened", "kranto", "weak"),
)

# phrases that read like a model (Humanizer): (pattern, rule, plain fix)
FLOOR_PHRASES: tuple[tuple[str, str, str], ...] = (
    (r"at its core", "saying", "say the specific claim"),
    (r"the real question is", "saying", "ask the question directly"),
    (r"what (?:really|truly) matters(?: is)?", "saying", "say what matters, plainly"),
    (r"the heart of the matter", "saying", "say the specific claim"),
    (r"stands? as a (?:testament|reminder)", "saying", "say what it shows"),
    (r"plays? a (?:key|crucial|pivotal|vital) role", "saying", "say what it does"),
    (r"(?:serves|stands|functions) as (?:a|an|the)", "plain_verbs", "use is, are or has"),
    (r"(?:experts|observers|analysts|critics) (?:say|argue|note|believe|suggest)",
     "authority", "name who said it, or cut"),
    (r"industry reports (?:say|suggest|show)", "authority", "name the report, or cut"),
    (r"i hope this helps", "chat", "cut it"),
    (r"great question", "chat", "cut it"),
    (r"(?:excited|thrilled|delighted|proud) to (?:share|announce|introduce)", "hype",
     "say what it is"),
    (r"(?:huge|big|exciting) news", "hype", "say the news"),
    (r"(?:(?:well )?worth (?:a look|watching|keeping an eye on|a read)|(?:it )?remains to be "
     r"seen|one to watch|watch this space)", "stock", "end on the last concrete fact"),
    (r"i'?m not saying", "arguing", "make the claim itself"),
    (r"don'?t get me wrong", "arguing", "make the claim itself"),
)
