"""Judge `kranto doctor` on a bare machine, for smoke.sh's setup step.

    python3 smoke_doctor.py DOCTOR_LOG EXIT_CODE

A bare machine (a new HOME, no model chosen, no Claude Code, no gh login) may lack only those
pieces. Doctor must say the model is missing, one of two ways: a FAIL on the key (an older
doctor, or a model chosen whose key is unset), or `warn model  none chosen yet` (a fresh
install before Welcome's model step: nothing to fail yet, so doctor may exit 0). Any FAIL
outside the allowed pieces stops the cut, and so does a doctor that passes without saying the
model is missing.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# what a bare machine is allowed to lack: Claude Code, gh's login, the model key
ALLOWED = frozenset({"claude", "gh", "api key", "key", "llm key", "openrouter"})
_FAIL = re.compile(r"^\s*FAIL\s+(\S+(?: \S+)?)\s{2,}", re.M)
_NO_MODEL = re.compile(r"^\s*warn\s+model\s{2,}none chosen", re.M)


def judge(text: str, code: int) -> tuple[bool, str]:
    """(ok, the line to print)."""
    failed = sorted({m.group(1).strip() for m in _FAIL.finditer(text)})
    bad = [f for f in failed if f not in ALLOWED]
    if bad:
        return False, (f"smoke setup: kranto doctor fails on {bad} (allowed on a bare machine: "
                       f"{sorted(ALLOWED)})\n{text}")
    no_model = bool(_NO_MODEL.search(text))
    key_failed = any(f in ALLOWED - {"claude", "gh"} for f in failed)
    if not (no_model or key_failed):
        return False, ("smoke setup: kranto doctor does not say the model is missing on a bare "
                       f"machine (exit {code})\n{text}")
    if code == 0 and failed:
        return False, f"smoke setup: kranto doctor printed FAIL {failed} but exited 0\n{text}"
    why = "warns that no model is chosen" if no_model else f"FAIL only on {failed}"
    return True, f"ok: kranto doctor exits {code}; {why}"


def main(argv: list[str]) -> int:
    text, code = Path(argv[0]).read_text(), int(argv[1])
    ok, line = judge(text, code)
    print(line, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
