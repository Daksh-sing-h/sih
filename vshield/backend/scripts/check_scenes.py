"""End-to-end demo check: streams each scene through the running server in real time
and asserts the risk band. Run before every demo (≈2 min).

  uvicorn vshield.server:app --port 8000        # in another terminal
  python scripts/check_scenes.py                # needs the 'ceo' enrollment (see README)
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from stream_call import stream, summary  # noqa: E402

CEO = "+91-98100-00001"
D = os.path.join(os.path.dirname(__file__), "..", "data", "demo")

# (name, files, kwargs, allowed peak bands, expected phrase-match verdict or None, expect a fast answer)
SCENES = [
    ("1  genuine CEO, routine", ["ceo_genuine_1.wav"], {}, {"low"}, None, None),
    ("2  synthetic voice, routine request", ["synthetic_routine.wav"], {}, {"high"}, None, None),
    # real clone of the enrolled CEO: the speaker check is fooled; the detector alone gets
    # it only to low/medium. Report-only (bands=None) so a future improvement shows up.
    ("2c CLONED CEO, routine request", ["clone_ceo_routine.wav"], {}, None, None, None),
    ("3c CLONED CEO, ₹25 lakh", ["clone_ceo_fraud.wav"], {}, {"critical"}, None, None),
    ("3  synthetic voice, ₹25 lakh (English)", ["synthetic_fraud_en.wav"], {}, {"critical"}, None, None),
    ("3h synthetic voice, ₹25 lakh (Hindi)", ["synthetic_fraud_hi.wav"], {}, {"critical"}, None, None),
    # a recording can't repeat a random phrase, so this only checks timing: a genuine voice
    # answers fast. (Wrong words still escalate, as they should; live, the person says it.)
    ("5  genuine voice answers fast", ["ceo_genuine_1.wav", "ceo_genuine_2.wav"],
     {"challenge_before": 2, "answer_delay": 0.8}, {"low", "medium", "high"}, None, True),
    ("6  attacker: slow, pre-recorded reply", ["synthetic_routine.wav", "prerecorded_reply.wav"],
     {"challenge_before": 2, "answer_delay": 4.0}, {"high", "critical"}, False, False),
]


async def main() -> int:
    failures = 0
    print(f"{'scene':<42} {'peak':>14} {'p95':>7}  result")
    for name, files, kw, bands, want_verdict, want_fast in SCENES:
        msgs = await stream([os.path.join(D, f) for f in files], caller=CEO, enrollment="ceo",
                            verbose=False, **kw)
        s = summary(msgs)
        verdicts = [m for m in msgs if m["type"] == "challenge_verdict"]
        answers = [m for m in msgs if m["type"] == "challenge_result"]
        ok = bands is None or s["peak_band"] in bands
        if want_verdict is not None:
            ok = ok and bool(verdicts) and verdicts[-1]["matched"] is want_verdict
        if want_fast is not None:
            ok = ok and bool(answers) and (not answers[-1]["slow"]) is want_fast
        failures += not ok
        extra = f" · answered in {answers[-1]['latency_s']}s" if answers else ""
        extra += f" · heard “{verdicts[-1]['heard'][:40]}”" if verdicts else ""
        print(f"{name:<42} {s['peak_R']:>5} {s['peak_band']:<8} {s['p95_ms']:>5.0f}ms  "
              f"{'info' if bands is None else 'PASS' if ok else 'FAIL (expected ' + '/'.join(sorted(bands)) + ')'}{extra}")
    print(f"\n{len(SCENES) - failures}/{len(SCENES)} scenes as expected")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
