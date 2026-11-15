"""A run Kranto did not start never answers "done" (the operator's item, from the owner's
console on 0.6.0.dev4, 2026-10-27 18:47 UTC): asked to rerun ingest, ideas, the newsletter and
toot at once, Kranto ran ingest and refused the other three ("A job is already running"), but
the verb's reply said done for all four, because the route answered every press with a
redirect. A caller that asks for JSON (the page's run buttons, the verb door) now hears 202
when it started and 409 with the reason when it did not. No model, no network."""
import threading

from kranto.scheduler import Job, Scheduler
from kranto.store import iso, utcnow
from kranto.web.app import create_app

from .conftest import web_client
from .test_verbs import BASE, bare, bearer, rt  # noqa: F401 - fixture


def settled(sched) -> None:
    """The scheduler's first tick holds its lock a moment at start: wait for it to let go."""
    import time
    for _ in range(100):
        if sched.why_not(sched.jobs[0].kind) is None:
            return
        time.sleep(0.05)


def ran_just_now(store, *kinds: str) -> None:
    """Each kind ran a minute ago: the scheduler's own tick finds nothing due."""
    for k in kinds:
        store.insert("runs", {"run_uuid": f"r-{k}", "kind": k, "status": "ok",
                              "started_at": iso(utcnow()), "finished_at": iso(utcnow()),
                              "summary": "{}"})


def test_the_console_asking_four_runs_hears_one_started_and_three_refused(rt):  # noqa: F811
    gate = threading.Event()
    jobs = [Job("ingest", 3, lambda: gate.wait(5)), Job("ideas", 24, lambda: None),
            Job("newsletter.weekly", 168, lambda: None), Job("toot.weekly", 168, lambda: None)]
    ran_just_now(rt.store, *(j.kind for j in jobs))
    sched = Scheduler(rt.store, jobs)
    app = create_app(rt, sched, port=8765)
    try:
        with bare(app) as web:
            settled(sched)
            said = {k: web.post("/api/verbs/job.run_now", headers=bearer("console"),
                                json={"subject": {"id": k}, "client": "claude"})
                    for k in ("ingest", "ideas", "newsletter.weekly", "toot.weekly")}
        started = said["ingest"].json()
        assert said["ingest"].status_code == 200 and started["ok"], started
        for k in ("ideas", "newsletter.weekly", "toot.weekly"):
            out = said[k].json()
            assert not out.get("ok"), (k, out)
            text = str(out)
            assert "Not started" in text and "Reading your sources is running" in text, (k, text)
            assert "one job at a time" in text
    finally:
        gate.set()
    # the page's own run button: the same answer, in JSON (a fresh Kranto: closing the client
    # above stopped its scheduler, and "Kranto is stopping" is what it would say)
    gate = threading.Event()
    sched = Scheduler(rt.store, jobs[:1] + [Job("ideas", 24, lambda: None)])
    sched.jobs[0] = Job("ingest", 3, lambda: gate.wait(5))
    try:
        with web_client(create_app(rt, sched, port=8765), BASE) as page:
            json_ = {"accept": "application/json"}
            settled(sched)
            first = page.post("/run/ingest", headers=json_)
            assert first.status_code == 202, first.json()
            r = page.post("/run/ideas", headers=json_)
            assert r.status_code == 409 and r.json()["error"].startswith(
                "Not started: Writing idea cards: Reading your sources is running")
            assert page.post("/run/nothing", headers={"accept": "application/json"}) \
                .json()["error"].endswith("Kranto has no job nothing. Ask again when it has ended.")
    finally:
        gate.set()
    # an old form post still follows its redirect
    with web_client(create_app(rt, None, port=8765), BASE) as page:
        r = page.post("/run/ingest", follow_redirects=False)
        assert r.status_code in (302, 303)
        r = page.post("/run/ingest", headers={"accept": "application/json"})
        assert r.status_code == 409 and "scheduler off" in r.json()["error"]


def test_a_run_that_starts_says_so(rt):  # noqa: F811
    ran = threading.Event()
    ran_just_now(rt.store, "ideas")
    sched = Scheduler(rt.store, [Job("ideas", 24, ran.set)])
    with web_client(create_app(rt, sched, port=8765), BASE) as page:
        settled(sched)
        r = page.post("/run/ideas", headers={"accept": "application/json"})
    assert r.status_code == 202 and r.json() == {"ok": True, "started": "ideas",
                                                  "msg": "Started: Writing idea cards. Activity "
                                                         "follows it."}
    assert ran.wait(5)
