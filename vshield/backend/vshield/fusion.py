"""Risk fusion (deck: R = w1*A + w2*S + w3*B + w4*C), plus the rules and bands.

Linear fusion keeps every point of R explainable: each signal's contribution is
shown as its own bar. Linear alone can't express "clone *and* a fraud request is
far worse than either", so a few escalation rules lift R, and the lift is shown
as a separate, labelled contribution.

Unavailable signals (e.g. S before anyone is enrolled) are dropped and the
remaining weights renormalised, so R stays on a 0-100 scale.
"""
from __future__ import annotations

from .config import CFG

ACTIONS = {
    "low": "No warning signs so far: continue",
    "medium": "Verify the request on an independent channel before acting",
    "high": "Challenge: ask the caller to repeat a random phrase",
    "critical": "Hold the transaction: call back on the registered number or require MFA",
}


def band_for(r: float, bands=CFG.bands) -> str:
    for upper, name in bands:
        if r < upper:
            return name
    return bands[-1][1]


def fuse(signals: dict[str, float | None], weights: dict[str, float] | None = None,
         events: dict | None = None) -> dict:
    weights = weights or CFG.weights
    events = events or {}
    avail = {k: v for k, v in signals.items() if v is not None}
    wsum = sum(weights[k] for k in avail) or 1.0
    contrib = {k: 100.0 * weights[k] * v / wsum for k, v in avail.items()}
    base = sum(contrib.values())

    A, S, B, C = (signals.get(k) or 0.0 for k in "ASBC")
    voice_anomaly = max(A, B, S if signals.get("S") is not None else 0.0)
    floor, rules = 0.0, []
    if C >= 0.7 and voice_anomaly >= 0.5:
        floor = max(floor, 85.0)
        rules.append("High-risk request from an anomalous voice")
    elif C >= 0.7:
        floor = max(floor, 40.0)
        rules.append("High-risk request: always verify on an independent channel")
    if A >= 0.85:
        floor = max(floor, 65.0)
        rules.append("Strong synthetic-speech evidence")
    elif A >= 0.7 and signals.get("S") is not None and S >= 0.7:
        floor = max(floor, 65.0)
        rules.append("Synthetic-sounding voice that doesn't match the enrolled speaker")
    if B >= 0.85:
        floor = max(floor, 65.0)
        rules.append("Challenge answered too slowly for a live human")
    stages = events.get("stages") or []
    if "ask" not in stages and len(stages) >= 3:
        floor = max(floor, 60.0)
        rules.append("Scam script in progress (" + " → ".join(stages) + "): challenge the caller before they ask")
    elif "ask" not in stages and len(stages) == 2:
        floor = max(floor, 35.0)
        rules.append("Conversation is heading into scam territory (" + " → ".join(stages) + ")")
    if events.get("challenge_failed"):
        floor = max(floor, 80.0 if C >= 0.5 else 70.0)
        rules.append("Challenge phrase was not repeated back")

    r = max(base, floor)
    if r > base:
        contrib["rules"] = r - base
    band = band_for(r)
    return {
        "R": round(r, 1),
        "band": band,
        "action": ACTIONS[band],
        "contributions": {k: round(v, 1) for k, v in contrib.items()},
        "rules": rules,
    }
