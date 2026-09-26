"""Evaluate Hugging Face audio-classification deepfake detectors on real vs fake folders.

Usage:
  python scripts/eval_detector.py --real data/eval/real --fake data/eval/fake \
      --models MelodyMachine/Deepfake-audio-detection-V2 [more ...] [--phone]

Reports ROC-AUC, EER, accuracy@0.5 and ms per 3-second window, per model.
Clip score = mean fake-probability over 3 s windows (1.5 s hop).
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
import time

import numpy as np
import torch
from sklearn.metrics import roc_auc_score, roc_curve

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from vshield.audio import load_wav, phone_channel, windows  # noqa: E402
from vshield.signals.hf_detector import HFDetector  # noqa: E402


def eer(labels, scores) -> float:
    fpr, tpr, _ = roc_curve(labels, scores)
    fnr = 1 - tpr
    i = np.nanargmin(np.abs(fnr - fpr))
    return float((fpr[i] + fnr[i]) / 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", required=True)
    ap.add_argument("--fake", required=True)
    ap.add_argument("--models", nargs="+", required=True)
    ap.add_argument("--phone", action="store_true", help="also test through a simulated phone line")
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()

    torch.set_num_threads(max(1, os.cpu_count() // 2))
    files = [(f, 0) for f in sorted(glob.glob(os.path.join(args.real, "*.wav")))] + \
            [(f, 1) for f in sorted(glob.glob(os.path.join(args.fake, "*.wav")))]
    clips = [(load_wav(f), y) for f, y in files]
    conditions = {"clean": lambda x: x}
    if args.phone:
        rng = np.random.default_rng(0)
        conditions["phone"] = lambda x: phone_channel(x, rng=rng)
    print(f"{len(clips)} clips ({sum(1 for _, y in clips if y == 0)} real / "
          f"{sum(1 for _, y in clips if y == 1)} fake)\n")

    for name in args.models:
        det = HFDetector(name, device=args.device)
        for cond, fn in conditions.items():
            labels, scores, times = [], [], []
            for x, y in clips:
                xs = fn(x)
                ps = []
                for w in windows(xs):
                    t = time.perf_counter()
                    ps.append(det.fake_prob(w))
                    times.append(time.perf_counter() - t)
                labels.append(y)
                scores.append(float(np.mean(ps)))
            labels, scores = np.array(labels), np.array(scores)
            acc = float(np.mean((scores >= 0.5) == labels))
            real_mean = scores[labels == 0].mean()
            fake_mean = scores[labels == 1].mean()
            print(f"{name:<62} {cond:<6} AUC={roc_auc_score(labels, scores):.3f} "
                  f"EER={eer(labels, scores):.3f} acc@0.5={acc:.3f} "
                  f"p(fake|real)={real_mean:.2f} p(fake|fake)={fake_mean:.2f} "
                  f"{1000*np.median(times):.0f}ms/win")


if __name__ == "__main__":
    main()
