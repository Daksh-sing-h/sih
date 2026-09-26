"""Learn fusion weights from labelled calls instead of the hand-set priors.

Record calls of all four kinds (genuine/clone × routine/fraud request) and list them
in a CSV with columns: file,label,caller  (label 1 = should be flagged, 0 = genuine
& legitimate; caller optional). Then, with the server running:

  python scripts/fit_fusion.py calls.csv --enrollment ceo

Each file is streamed through the live server; the call-level signals (the highest
value each signal reached) feed a logistic regression. The printed weights,
normalised to sum to 1, go into `weights` in vshield/config.py. Aim for 20+ calls
per kind; with fewer, trust the hand-set priors more than the fit.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score

sys.path.insert(0, os.path.dirname(__file__))
from stream_call import stream  # noqa: E402

KEYS = ("A", "S", "B", "C")


async def call_features(path: str, caller: str, enrollment: str) -> list[float]:
    msgs = await stream([path], caller=caller, enrollment=enrollment, verbose=False)
    scores = [m for m in msgs if m["type"] == "score"]
    return [max((m["signals"][k] or 0.0) for m in scores) if scores else 0.0 for k in KEYS]


async def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("--enrollment", default="ceo")
    ap.add_argument("--caller", default="+91-98100-00001")
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.csv)))
    X, y = [], []
    for r in rows:
        feats = await call_features(r["file"], r.get("caller") or args.caller, args.enrollment)
        X.append(feats)
        y.append(int(r["label"]))
        print(f"{r['label']}  " + " ".join(f"{k}={v:.2f}" for k, v in zip(KEYS, feats)) + f"  {os.path.basename(r['file'])}")
    X, y = np.array(X), np.array(y)
    if len(set(y)) < 2:
        sys.exit("need both labels (0 and 1) in the CSV")

    model = LogisticRegression(class_weight="balanced").fit(X, y)
    coef = np.clip(model.coef_[0], 0, None)       # a signal should never *lower* risk
    weights = coef / coef.sum() if coef.sum() > 0 else np.full(4, 0.25)
    folds = min(5, int(np.bincount(y).min()))
    if folds >= 2:
        acc = cross_val_score(LogisticRegression(class_weight="balanced"), X, y, cv=folds).mean()
        print(f"\ncross-validated accuracy: {acc:.2f} ({folds}-fold, {len(y)} calls)")
    print("weights = {" + ", ".join(f'"{k}": {w:.2f}' for k, w in zip(KEYS, weights)) + "}")


if __name__ == "__main__":
    asyncio.run(main())
