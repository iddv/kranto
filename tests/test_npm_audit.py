"""CI's audit of the page's lockfile (``scripts/ci/npm_audit.py``): every advisory at high or
above fails, as ``npm audit --audit-level=high`` does, but for the named, dated exceptions."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("npm_audit", ROOT / "scripts/ci/npm_audit.py")
npm_audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(npm_audit)

TODAY = dt.date(2026, 11, 17)


def _adv(gid: str, name: str, severity: str) -> dict:
    return {"source": 1, "name": name, "title": f"{name} is weak", "severity": severity,
            "range": "<=1.0.0", "url": f"https://github.com/advisories/{gid}"}


def _report(*advs: dict) -> dict:
    vulns = {a["name"]: {"name": a["name"], "severity": a["severity"], "via": [a]} for a in advs}
    if advs:   # a package flagged only through another one
        vulns["tool"] = {"name": "tool", "severity": advs[0]["severity"],
                         "via": [advs[0]["name"]]}
    return {"auditReportVersion": 2, "vulnerabilities": vulns}


ALLOW = [{"id": "GHSA-aaaa-bbbb-cccc", "package": "globby", "why": "build tools only",
          "until": "2026-12-31"}]


def test_an_excused_advisory_passes_and_says_so():
    bad, said = npm_audit.judge(_report(_adv("GHSA-aaaa-bbbb-cccc", "globby", "high")), ALLOW,
                                "high", TODAY)
    assert bad == [] and "excused until 2026-12-31" in said[0]


def test_any_other_high_or_critical_advisory_fails_and_a_moderate_one_does_not():
    report = _report(_adv("GHSA-aaaa-bbbb-cccc", "globby", "high"),
                     _adv("GHSA-dddd-eeee-ffff", "parser", "critical"),
                     _adv("GHSA-gggg-hhhh-iiii", "colors", "moderate"))
    bad, _ = npm_audit.judge(report, ALLOW, "high", TODAY)
    assert len(bad) == 1 and bad[0].startswith("GHSA-dddd-eeee-ffff parser")


def test_an_exception_past_its_day_fails_again():
    bad, _ = npm_audit.judge(_report(_adv("GHSA-aaaa-bbbb-cccc", "globby", "high")), ALLOW,
                             "high", dt.date(2027, 1, 1))
    assert len(bad) == 1 and "look at it again" in bad[0]


def test_an_exception_no_longer_needed_is_named_and_a_clean_report_passes(tmp_path):
    bad, said = npm_audit.judge(_report(), ALLOW, "high", TODAY)
    assert bad == [] and "no longer reported" in said[0]
    (tmp_path / "r.json").write_text(json.dumps(_report()))
    assert npm_audit.main(["--report", str(tmp_path / "r.json"), "--today", "2026-11-17"]) == 0
    (tmp_path / "e.json").write_text(json.dumps({"error": {"code": "ENOLOCK"}}))
    assert npm_audit.main(["--report", str(tmp_path / "e.json")]) == 2


def test_every_exception_says_what_why_and_until_when():
    allow = json.loads((ROOT / "scripts/ci/npm_audit_allow.json").read_text())["exceptions"]
    for ex in allow:
        assert ex["id"].startswith("GHSA-") and ex["package"] and len(ex["why"]) > 40
        dt.date.fromisoformat(ex["until"])
