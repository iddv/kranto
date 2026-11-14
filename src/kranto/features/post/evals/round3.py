"""Round 3's live run, by hand: never in CI, never by a job.

    python -m kranto.features.post.evals round3 --home <a scratch kranto home> --budget 3 \\
        --out DIR [--items ...] [--salt item:kind,...] [--owner]

For each of round 2's ten items: the proposed angles of the new kinds (where it leads, a bet, a
scene; one call, and one more when the rule refuses a proposal), then one draft per angle
through the writer (compose with the angle, the call, check with the sources, revise of only the
flagged spans, the code's voice rule), each marked by the rubric judge, which now also says
whether the post goes beyond the item and whether its first sentence is about the world. Then,
on the thin items named by ``--salt``, the same angle written twice more: with the salt switch
at salty, and plain with "more salt on thin items" off, so the three read side by side. With
``--owner``: the judge's marks on the drafts of the owner's second read (his picks and the
posts he refused). Last, the export of the ten items' prompts with the run's angles, as round 2
did, so any model can write from the same angles.

Every call goes through the home's metered client; the run stops before the next call once the
cost (or the list-price estimate) reaches the budget. It writes ``DIR/drafts/<writer>/<name>.md``,
``DIR/export/`` and ``DIR/recorded3.json``, which ``tests/test_prose_round3.py`` replays.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from ....prose import angles as propose
from ....prose import check, revise
from ....prose.composer import salt_of, thin
from ....prose.profile import Profile
from ....prose.reviser import enforce_voice, fit, tidy
from . import export, rubric, score, writers
from .live import Budget, Meter
from .round2 import FIVE_MORE, OWNER_FIVE, SHORTEN, post_md

HERE = Path(__file__).parent
MAX_WORDS = 200            # the owner's rule 7: a blog post is 120 to 200 words
# the thin items written salty and plain beside the default (post 8's item, and one more)
SALT = {"card-160": "end", "card-152": "end"}
SALT_KINDS = ("salty", "plain")


def material(item: dict) -> dict:
    return {"title": writers.about(item), "facts": item["facts"]}


def profile_for(salt: str | None) -> Profile:
    """``salty``: the salt switch at salty; ``plain``: plain with "more salt on thin items"
    off; None: the defaults (plain, and one step more on a thin item)."""
    p = writers.profile("salty" if salt == "salty" else None)
    if salt == "plain":
        from dataclasses import replace
        p = replace(p, switches={**p.switches, "salt": "plain", "salt_thin": "off"})
    return p


def write_one(m: Meter, item: dict, site: str, angle: str, salt: str | None = None) -> dict:
    """One draft from one angle: the writer's call, check (with the sources: no person they
    don't name), revise, the voice rule."""
    p = profile_for(salt)
    msgs = writers.prompt("new", site, item, angle=angle, p=p)
    got = m.complete(tier="reason", purpose="prose_eval_write", messages=msgs,
                     schema=writers.schema(site), max_tokens=1100 if site == "blog" else 250)
    answer = got["structured"] or got["text"]
    draft, model = writers.text_of(site, answer), got["model"]
    title = ""
    if site == "blog":
        parsed = answer if isinstance(answer, dict) else rubric.answer({"text": answer})
        title = str(parsed.get("title") or "").strip()
    sname = score.SITE[site]
    kind = "long" if site == "blog" else "short"
    limits = {"max_chars": writers.ROOM, "unit": "characters", "links": 0} \
        if site == "toot" else None
    sources = f"{writers.about(item)}\n{item['facts']}"
    flags = check(draft, sname, p, kind=kind, take=angle, limits=limits,
                  sources=sources)["flags"]

    def complete(messages, schema):
        return m.complete(tier="reason", purpose="prose_eval_revise", messages=messages,
                          schema=schema, max_tokens=1500)
    fixed = revise(draft, flags, p, complete=complete, site=sname, kind=kind, take=angle,
                   limits=limits)
    final = fixed["text"] if site == "blog" else fit(" ".join(fixed["text"].split()),
                                                     writers.ROOM)
    final, _ = enforce_voice(final, p, angle)
    final = tidy(final)
    left = check(final, sname, p, kind=kind, take=angle, limits=limits, sources=sources)
    long = None
    if site == "blog" and len(final.split()) > MAX_WORDS:
        long, final, left = final, *cut(m, final, p, angle, sources, left)
    return {"angle": angle, "title": title, "draft": draft, "text": final, "cut_from": long,
            "salt": salt_of(p, material(item)), "rounds": fixed["rounds"],
            "flags": sorted({f["rule"] for f in left["flags"]}), "score": left["score"],
            "words": len(final.split()), "model": model, "sha": writers.sha(msgs)}


def cut(m: Meter, text: str, p, angle: str, sources: str, before: dict) -> tuple[str, dict]:
    """A blog draft over ``MAX_WORDS`` cut down by one call; the cut is kept only when it is
    shorter and trips no rule the draft did not."""
    from ....prose.reviser import SHORTEN_SCHEMA, _shortened
    got = m.complete(tier="reason", purpose="prose_eval_revise", max_tokens=900,
                     schema=SHORTEN_SCHEMA, messages=[
                         {"role": "system", "content": SHORTEN.format(
                             n=MAX_WORDS - 10, now=len(text.split()))},
                         {"role": "user", "content": text}])
    new = tidy(_shortened(got))
    if not new or len(new.split()) >= len(text.split()):
        return text, before
    after = check(new, "blog", p, kind="long", take=angle, sources=sources)
    if {f["rule"] for f in after["flags"]} - {f["rule"] for f in before["flags"]}:
        return text, before
    return new, after


def shorten_recorded(m: Meter, out: Path, writer: str, rec: dict) -> None:
    """Every recorded blog draft over ``MAX_WORDS`` through :func:`cut` (one call each)."""
    items = {it["id"]: it for it in writers.items()}
    for iid, row in rec["items"].items():
        if row["site"] != "blog":
            continue
        rows = [(k, d) for k, d in row["drafts"].items()] + \
            [(f"{d.get('kind')}.{s}", d) for s, d in (row.get("salted") or {}).items()]
        for name, d in rows:
            if len(d["text"].split()) <= MAX_WORDS:
                continue
            sources = f"{writers.about(items[iid])}\n{items[iid]['facts']}"
            p = profile_for(d.get("salt_switch"))
            before = check(d["text"], "blog", p, kind="long", take=d["angle"], sources=sources)
            new, after = cut(m, d["text"], p, d["angle"], sources, before)
            if new != d["text"]:
                d["cut_from"], d["text"] = d["text"], new
                d["words"] = len(new.split())
                d["flags"] = sorted({f["rule"] for f in after["flags"]})
                (out / "drafts" / writer / f"{iid}.blog.{name}.md").write_text(
                    post_md("blog", d), encoding="utf-8")
            print(f"{iid} {name}: {len((d.get('cut_from') or d['text']).split())} -> "
                  f"{len(d['text'].split())} words ${m.spent():.3f}", flush=True)


def mark(m: Meter, item: dict, site: str, text: str, angle: str | None) -> dict:
    got = m.complete(tier="judge", purpose="prose_eval_judge", schema=rubric.MARK_SCHEMA,
                     messages=rubric.mark_messages(item, text, angle, site), max_tokens=400)
    return {**rubric.answer(got), "model": got["model"]}


def run(m: Meter, sites_of: dict[str, str], out: Path, writer: str, rec: dict,
        salt: dict[str, str], owner: bool) -> None:
    items = {it["id"]: it for it in writers.items()}
    drafts_dir = out / "drafts" / writer
    drafts_dir.mkdir(parents=True, exist_ok=True)
    for iid, site in sites_of.items():
        item = items[iid]
        row = rec["items"].setdefault(iid, {"site": site, "title": item["title"],
                                            "thin": thin(material(item)), "drafts": {}})
        if not row.get("angles"):
            def complete(messages, schema):
                return m.complete(tier="reason", purpose="prose_eval_angles",
                                  messages=messages, schema=schema, max_tokens=500)
            row["angles"] = propose(material(item), writers.profile(), complete=complete,
                                    site="blog" if site == "blog" else "mastodon")
        for a in row["angles"]:
            if a["kind"] in row["drafts"]:
                continue
            d = write_one(m, item, site, a["text"])
            d["mark"] = mark(m, item, site, d["text"], d["angle"])
            row["drafts"][a["kind"]] = d
            (drafts_dir / f"{iid}.{site}.{a['kind']}.md").write_text(post_md(site, d),
                                                                      encoding="utf-8")
            print(f"{iid} {site} {a['kind']}: {d['words']} words salt={d['salt']} "
                  f"beyond={d['mark'].get('beyond')} flags={d['flags']} ${m.spent():.3f} "
                  f"after {m.calls} calls", flush=True)
    for iid, kind in salt.items():
        row = rec["items"][iid]
        angle = next((a["text"] for a in row["angles"] if a["kind"] == kind), None)
        if angle is None:
            continue
        for s in SALT_KINDS:
            got = row.setdefault("salted", {}).get(s)
            if got:
                continue
            d = write_one(m, items[iid], row["site"], angle, salt=s)
            d["kind"], d["salt_switch"] = kind, s
            d["mark"] = mark(m, items[iid], row["site"], d["text"], angle)
            row["salted"][s] = d
            (drafts_dir / f"{iid}.{row['site']}.{kind}.{s}.md").write_text(
                post_md(row["site"], d), encoding="utf-8")
            print(f"{iid} {kind} {s}: {d['words']} words flags={d['flags']} ${m.spent():.3f}",
                  flush=True)
    if owner and not rec.get("owner_marks"):
        rec["owner_marks"] = owner_marks(m)


def owner_marks(m: Meter) -> list[dict]:
    """The judge's marks on the owner's second read: his pick on the six he picked, and all
    three writers' drafts on the four he refused."""
    read = json.loads((HERE / "owner_read_2.json").read_text(encoding="utf-8"))
    items = {it["id"]: it for it in writers.items()}
    out = []
    for p in read["posts"]:
        who = [p["owner_pick"]] if p["owner_pick"] != "none" else list(p["drafts"])
        for w in who:
            text = p["drafts"][w]
            got = mark(m, items[p["item"]], p["site"], text, p["angle"])
            out.append({"post": p["post"], "name": p["name"], "writer": w,
                        "owner": p["owner_pick"], **{k: got.get(k) for k in (
                            "beyond", "first_world", "first", "ok", "why", "model")}})
            print(f"owner post {p['post']} {w}: beyond={got.get('beyond')} "
                  f"ok={got.get('ok')} ${m.spent():.3f}", flush=True)
    return out


def summary(rec: dict) -> dict:
    drafts = [d for r in rec["items"].values() for d in r["drafts"].values()]
    marks = [d.get("mark") or {} for d in drafts]
    owner = rec.get("owner_marks") or []
    return {"drafts": len(drafts),
            "beyond": sum(1 for x in marks if x.get("beyond")),
            "first_world_on_cards": [
                (iid, k, (d.get("mark") or {}).get("first_world"))
                for iid, r in rec["items"].items() if iid.startswith("card-")
                for k, d in r["drafts"].items()],
            "words": [d.get("words") for d in drafts],
            "owner_picks_beyond": [(o["post"], o["writer"], o["beyond"]) for o in owner
                                   if o["owner"] != "none"],
            "owner_refused_beyond": [(o["post"], o["writer"], o["beyond"]) for o in owner
                                     if o["owner"] == "none"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="evals round3", description=__doc__.split("\n\n")[0])
    ap.add_argument("--home", required=True, help="a scratch kranto home (never live's)")
    ap.add_argument("--budget", type=float, default=3.0)
    ap.add_argument("--out", required=True, help="where the drafts, export and record go")
    ap.add_argument("--writer", default="claude", help="the drafts' folder name")
    ap.add_argument("--items", default="", help="item ids (default: round 2's ten)")
    ap.add_argument("--salt", default=",".join(f"{k}:{v}" for k, v in SALT.items()),
                    help="item:kind pairs written salty and plain too ('' for none)")
    ap.add_argument("--owner", action="store_true",
                    help="mark the drafts of the owner's second read")
    ap.add_argument("--record", default=str(HERE / "recorded3.json"))
    ap.add_argument("--redo", default="", help="item:kind pairs to write again (comma-separated)")
    ap.add_argument("--shorten", action="store_true",
                    help="cut each recorded blog draft over 200 words (one call each)")
    a = ap.parse_args(argv)
    sites_of = {**OWNER_FIVE, **FIVE_MORE}
    if a.items:
        sites_of = {i: sites_of.get(i, "blog") for i in a.items.split(",") if i}
    salt = dict(p.split(":") for p in filter(None, a.salt.split(",")))
    from .... import config as config_mod
    from ....embed import StubEmbedder
    from ....runtime import open_runtime
    cfg = config_mod.load(Path(a.home), dotenv=True)
    rt = open_runtime(cfg, embedder=StubEmbedder())
    m = Meter(rt, a.budget)
    out = Path(a.out)
    rec_path = Path(a.record)
    rec = json.loads(rec_path.read_text(encoding="utf-8")) if rec_path.is_file() else {}
    rec.setdefault("items", {})
    for pair in filter(None, a.redo.split(",")):
        iid, kind = pair.split(":")
        old = rec["items"][iid]["drafts"].pop(kind)
        rec["items"][iid].setdefault("redone", {})[kind] = old["text"]
    stopped = None
    try:
        if a.shorten:
            shorten_recorded(m, out, a.writer, rec)
        else:
            run(m, sites_of, out, a.writer, rec, salt, a.owner)
    except Budget as exc:
        stopped = str(exc)
        print(stopped, flush=True)
    finally:
        before = rec.get("meta", {}).get("runs") or []
        this = {"at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "provider": cfg.llm.provider_name,
                "models": {t: cfg.llm.model_for(t) for t in ("reason", "judge")},
                "calls": m.calls, "cost_usd": round(m.usd, 4), "equiv_usd": round(m.equiv, 4),
                "budget_usd": a.budget, "stopped": stopped}
        runs = [*before, this]
        rec["meta"] = {"runs": runs, "calls": sum(r["calls"] for r in runs),
                       "cost_usd": round(sum(r["cost_usd"] for r in runs), 4),
                       "equiv_usd": round(sum(r["equiv_usd"] for r in runs), 4)}
        rec_path.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n",
                            encoding="utf-8")
        rt.close()
    angles = {iid: {x["kind"]: x["text"] for x in r.get("angles") or []}
              for iid, r in rec["items"].items()}
    export.export(out / "export", list(sites_of), angles=angles, site_of=sites_of)
    print(json.dumps(summary(rec), indent=1))
    return 0 if stopped is None else 2


if __name__ == "__main__":
    sys.exit(main())
