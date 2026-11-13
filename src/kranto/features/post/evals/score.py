"""The scorecard of a recording, with no model call.

For each site and writer: the checker's mean score, flags per post and the share of posts with
none (the checker runs at ``strict`` on the eval's profile, so the old writer is judged by the
same rules as the new); the rhythm against the eval's voice card (sentence length's mean and
spread, as the distance from the card's 14 and 7 words); the share of posts with a first-person
claim that neither the item's take nor a sample backs (P-5); and the blind pairwise judgement
(new against old: wins, losses, ties).
"""

from __future__ import annotations

import math
from statistics import mean

from ....prose import check, invented_first_person
from ....prose.checker import sentence_lengths
from ....prose.reviser import enforce_voice
from . import writers

CARD_MEAN, CARD_SD = 14.0, 7.0
SITE = {"blog": "blog", "toot": "mastodon"}


def rhythm(text: str) -> dict[str, float] | None:
    ls = sentence_lengths(text)
    if len(ls) < 2:
        return None
    m = sum(ls) / len(ls)
    sd = math.sqrt(sum((x - m) ** 2 for x in ls) / len(ls))
    return {"mean": round(m, 1), "sd": round(sd, 1),
            "off": round(abs(m - CARD_MEAN) / CARD_MEAN + abs(sd - CARD_SD) / CARD_SD, 2)}


def post(text: str, site: str, item: dict) -> dict:
    p = writers.profile()
    take = writers.take_of(item) or ""
    limits = {"max_chars": writers.ROOM, "unit": "characters"} if site == "toot" else None
    got = check(text, SITE[site], p, take=take, strictness="strict", limits=limits)
    invented = invented_first_person(text, [take, *(s.text for s in p.samples)])
    return {"score": got["score"], "flags": len(got["flags"]),
            "rules": sorted({f["rule"] for f in got["flags"]}), "rhythm": rhythm(text),
            "invented": [text[s:e].strip() for s, e in invented]}


def scorecard(recording: dict) -> dict:
    items = {it["id"]: it for it in writers.items()}
    out: dict = {"sites": {}, "n": 0}
    for site in writers.SITES:
        rows: dict[str, list[dict]] = {"old": [], "new": []}
        for iid, runs in recording["runs"].items():
            if iid not in items or site not in runs:
                continue
            for w in ("old", "new"):
                text = runs[site][w]["text"]
                raw = post(text, site, items[iid])
                if w == "new":
                    # the new pipeline's last step is code, not a model: replayed here on the
                    # recorded answer, as ``kranto eval replay`` replays recorded replies
                    final, _ = enforce_voice(text, writers.profile(),
                                             writers.take_of(items[iid]) or "")
                    if final != text:
                        raw = {**post(final, site, items[iid]),
                               "invented_raw": raw["invented"]}
                rows[w].append(raw)
        card: dict = {}
        for w, rs in rows.items():
            if not rs:
                continue
            offs = [r["rhythm"]["off"] for r in rs if r["rhythm"]]
            card[w] = {"posts": len(rs), "score": round(mean(r["score"] for r in rs), 1),
                       "flags_per_post": round(mean(r["flags"] for r in rs), 2),
                       "clean_share": round(sum(1 for r in rs if not r["flags"]) / len(rs), 2),
                       "rhythm_off": round(mean(offs), 2) if offs else None,
                       "invented_share": round(sum(1 for r in rs if r["invented"]) / len(rs),
                                               2),
                       "invented": [i for r in rs for i in r["invented"]],
                       "invented_share_raw": round(sum(
                           1 for r in rs if r.get("invented_raw", r["invented"])) / len(rs), 2),
                       "invented_raw": [i for r in rs for i in r.get("invented_raw", [])],
                       "rules": _top(rs)}
        judged = [j for iid, j in (recording.get("judge") or {}).items()
                  if site in j and iid in items]
        if judged:
            card["pairwise"] = _pairwise(judged, site)
            # the old writer had no take to work from: the fair comparison is the items
            # without one (the take is the new writer's input, not its prose)
            plain = [j for iid, j in (recording.get("judge") or {}).items()
                     if site in j and iid in items and not writers.take_of(items[iid])]
            card["pairwise_without_take"] = _pairwise(plain, site)
        # recordings whose new prompt is no longer what compose builds (a guide changed since):
        # said, not failed; a live run brings them up to date
        card["stale_prompts"] = sum(
            1 for iid, runs in recording["runs"].items() if iid in items and site in runs
            and runs[site]["new"].get("sha") != writers.sha(writers.prompt("new", site,
                                                                           items[iid])))
        out["sites"][site] = card
        out["n"] = max(out["n"], len(rows["new"]))
    return out


def _pairwise(judged: list[dict], site: str) -> dict[str, int]:
    wins = sum(1 for j in judged if j[site]["winner"] == "new")
    losses = sum(1 for j in judged if j[site]["winner"] == "old")
    return {"judged": len(judged), "new_wins": wins, "old_wins": losses,
            "ties": len(judged) - wins - losses}


def _top(rs: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in rs:
        for rule in r["rules"]:
            counts[rule] = counts.get(rule, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1])[:8])
