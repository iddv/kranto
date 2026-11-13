"""``kranto eval``: build, grow and show a frozen set; replay it (free); pin a baseline; list
the scorecards."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import Refused, home_dir, lock, replay, scorecard, sets


def default_set(home: Path) -> Path | None:
    """The newest set under ``<home>/evals/sets`` (``v1``, ``v2``, ...), or None."""
    d = home_dir(home) / "sets"
    have = sorted((p for p in d.glob("v*") if p.name[1:].isdigit()
                   and (p / "manifest.json").exists()), key=lambda p: int(p.name[1:])) \
        if d.is_dir() else []
    return have[-1] if have else None


def resolve_set(home: Path, value: str | None) -> Path:
    if value:
        p = Path(value).expanduser()
        if p.is_dir():
            return p
        q = home_dir(home) / "sets" / value
        if q.is_dir():
            return q
        raise Refused(f"no eval set {value!r} (a directory, or a version under "
                      f"{home_dir(home) / 'sets'})")
    p = default_set(home)
    if p is None:
        raise Refused("no eval set yet: kranto eval set build --from <backup of kranto.db>")
    return p


def next_version(home: Path) -> Path:
    cur = default_set(home)
    n = int(cur.name[1:]) + 1 if cur else 1
    return home_dir(home) / "sets" / f"v{n}"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kranto eval", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("set", help="the frozen eval set: build one from a backup, grow the "
                                   "next version, show one")
    s.add_argument("action", choices=("build", "grow", "show"))
    s.add_argument("--from", dest="db", help="build/grow: a backup of kranto.db (Kranto "
                                             "backup), or the live file (copied read-only first)")
    s.add_argument("--set", help="grow/show: the set (default: the newest)")
    s.add_argument("--out", help="build/grow: where (default <home>/evals/sets/v<N>)")
    s.add_argument("--screens", type=int, default=60)
    s.add_argument("--judges", type=int, default=40)
    s.add_argument("--since", help="build: only calls made on or after this date")
    s.add_argument("--json", action="store_true")
    r = sub.add_parser("replay", help="the recorded replies through this Kranto: do its "
                                      "verdicts still match? (free: no model, no network)")
    r.add_argument("--set")
    r.add_argument("--json", action="store_true")
    b = sub.add_parser("baseline", help="pin a scorecard as its stage's baseline")
    b.add_argument("scorecard")
    lk = sub.add_parser("lock", help="prompts.lock.json (a checkout's): which shipped prompts "
                                     "changed since their scorecard; set an entry")
    lk.add_argument("action", nargs="?", choices=("check", "set"), default="check")
    lk.add_argument("name", nargs="?")
    lk.add_argument("--scorecard", help="set: the scorecard that evaluated this version")
    lk.add_argument("--skipped", metavar="REASON", help="set: not evaluated, and why")
    lk.add_argument("--file", default=lock.LOCK, help=f"default ./{lock.LOCK}")
    for stage, what in (("watching", "the screen and the judge"),
                        ("ideas", "the card writer, judged by the rubric judge"),
                        ("all", "every stage, in order, until the budget is spent")):
        st = sub.add_parser(stage, help=f"ask the models again on the set: {what} (spends "
                                        "up to --budget; never under CI)")
        st.add_argument("--budget", type=float, required=True, metavar="USD")
        st.add_argument("--set")
        st.add_argument("--split", choices=("dev", "held", "all"), default="all")
        st.add_argument("--n", type=int, help="at most N items a step")
        st.add_argument("--repeat", type=int, default=1, help="ask each item K times (2: the "
                                                              "noise floor)")
        st.add_argument("--provider", help="another of the seam's providers for this run "
                                           "(openrouter, anthropic, openai_compat, claude_code)")
        st.add_argument("--model", help="the judge tier's model for this run")
        st.add_argument("--reason-model", help="the reason tier's model (the card writer)")
        st.add_argument("--judge", default=None, help="ideas: the rubric judge's model "
                                                      "(default claude-opus-5-5)")
        st.add_argument("--judges", help="ideas: the directory holding the judge prompt")
        st.add_argument("--candidate", action="append", default=[], metavar="STEP=FILE",
                        help="also run STEP with this prompt, on the same items")
        st.add_argument("--tag")
    sc = sub.add_parser("scorecards", help="the runs so far, newest first")
    sc.add_argument("-n", type=int, default=10)
    sc.add_argument("--json", action="store_true")
    return p


def main(argv: list[str], home: Path, *, threshold: float | None = None,
         out=print) -> int:
    args =parser().parse_args(argv)
    try:
        if args.cmd == "set":
            return cmd_set(args, home, threshold, out)
        if args.cmd in ("watching", "ideas", "all"):
            return cmd_stage(args, home, out)
        if args.cmd == "replay":
            rep = replay.run(resolve_set(home, args.set))
            out(json.dumps(rep, indent=1) if args.json else replay.words(rep))
            return 1 if rep["changed"] else 0
        if args.cmd == "lock":
            if args.action == "set":
                if not args.name:
                    raise Refused("kranto eval lock set NAME --scorecard FILE | --skipped REASON")
                e = lock.set_entry(Path(args.file), args.name, scorecard=args.scorecard,
                                   skipped=args.skipped)
                out(f"{args.name}: {e['version']}, evaluated {e['evaluated']}")
                return 0
            probs = lock.problems(lock.read(Path(args.file)))
            out("\n".join(probs) if probs else f"{args.file}: every shipped prompt is locked")
            return 1 if probs else 0
        if args.cmd == "baseline":
            card = scorecard.pin(home, args.scorecard)
            out(f"baseline for {card['stage']} on set {card.get('set')} with "
                f"{card.get('model')}: {card['_file']}")
            return 0
        if args.cmd == "scorecards":
            hist = list(reversed(scorecard.history(home)))[:args.n]
            if args.json:
                out(json.dumps(hist, indent=1, default=str))
            for c in [] if args.json else hist:
                head = next((m for m in c["metrics"] if m["kind"] == "rate"), None)
                flags = sorted({m.get("flag") for m in c["metrics"] if m.get("flag")} -
                               {"within noise"})
                out(f"{c['date']}  {c['stage']:11} {c.get('set') or '':4} "
                    f"{c.get('model') or '':22} "
                    + (f"{head['label']} {head['num']}/{head['den']}" if head else "")
                    + f"  ${float(c.get('cost_usd') or 0):.3f}"
                    + (f"  {', '.join(flags)}" if flags else "") + f"  {c['_file']}")
            if not hist and not args.json:
                out("no scorecards yet")
            return 0
    except (Refused, sets.SetError, ValueError) as e:
        print(f"kranto eval: {e}", file=sys.stderr)
        return 2
    return 2


def cmd_set(args, home: Path, threshold: float | None, out) -> int:
    if args.action == "show":
        info = sets.show(resolve_set(home, args.set))
        if args.json:
            out(json.dumps(info, indent=1))
            return 0
        out(f"set {info['version']}, built {info['built_at']} from {info['from']}"
            + (f" (grown from {info['parent']})" if info.get("parent") else ""))
        for step, s in info["steps"].items():
            out(f"  {step:6} {s['n']} items, {s['held']} held, {s['owner_graded']} graded by "
                f"the owner; prompts {', '.join(s['prompt_versions']) or '-'}")
        return 0
    if not args.db:
        raise Refused(f"kranto eval set {args.action}: give --from <backup of kranto.db>")
    dest = Path(args.out).expanduser() if args.out else next_version(home)
    if args.action == "build":
        m = sets.build(Path(args.db), dest, screens=args.screens, judges=args.judges,
                       threshold=threshold if threshold is not None else 0.03,
                       since=args.since)
    else:
        m = sets.grow(resolve_set(home, args.set), Path(args.db), dest, screens=args.screens,
                      judges=args.judges, threshold=threshold)
    if args.json:
        out(json.dumps(m, indent=1))
    else:
        out(f"set {m['version']} written to {dest}: "
            + ", ".join(f"{k} {v['n']} ({v['held']} held, {v['owner_graded']} graded)"
                        for k, v in m.items() if isinstance(v, dict) and "n" in v)
            + f"; secret-shaped strings left: {m['secret_shaped']}")
    return 0


def cmd_stage(args, home: Path, out, *, opened=None) -> int:
    """``kranto eval watching|ideas|all``: through this home's configuration and library (its
    calls recorded there, purpose ``eval_<step>``)."""
    from .. import config as config_mod
    from .. import prompts
    from ..store import Store
    from . import refuse_under_ci, runner
    if opened is None:
        refuse_under_ci()
    cands = {}
    for c in args.candidate:
        step, _, f = c.partition("=")
        if step not in ("screen", "judge", "card") or not f:
            raise Refused(f"--candidate {c!r}: give STEP=FILE, STEP one of screen, judge, card")
        cands[step] = Path(f).expanduser().read_text()
    set_dir = resolve_set(home, args.set)
    if opened is None:
        cfg = config_mod.load(home, dotenv=False)
        store = Store.open(cfg.db_path)
        prompts.configure(home)
    else:
        cfg, store = opened[0], opened[1]
    stages = ("watching", "ideas") if args.cmd == "all" else (args.cmd,)
    left = args.budget
    try:
        for stage in stages:
            steps = runner.STAGES[stage]
            mine = {k: v for k, v in cands.items() if k in steps}
            try:
                cards = runner.run_stage(
                    stage, cfg=cfg, store=store, home=home, set_dir=set_dir, budget=left,
                    split=args.split, n=args.n, repeat=args.repeat, provider=args.provider,
                    model=args.model, reason_model=args.reason_model,
                    judge_model=args.judge or runner.DEFAULT_JUDGE,
                    judges=Path(args.judges) if args.judges else None,
                    candidates=mine or None, tag=args.tag,
                    client_for=(opened[2] if opened and len(opened) > 2 else None))
            except Refused as e:
                if args.cmd != "all":
                    raise
                out(f"{stage}: not run: {e}")
                break
            for card in cards:
                left -= float(card.get("cost_usd") or 0.0)
                out(scorecard.markdown(card))
                out(f"written: {scorecard.root(home) / card['file']}")
    finally:
        if opened is None:
            store.close()
    return 0
