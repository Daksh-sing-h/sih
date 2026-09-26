"""Signal A — voice authenticity (synthetic-speech / clone artefacts).

Measured on our eval set (3 s windows, 30 real LibriSpeech clips vs 30 macOS-TTS
clips; see scripts/eval_detector.py):

  model                                   real flagged      fake flagged     ms/win
                                          clean / phone     clean / phone
  mo-thecreator (wav2vec2-base)           19% / 0%          100% / 17%        73
  Gustking (wav2vec2-XLS-R large)  ← used 27% / 16%         100% / 98%       207

Single windows are noisy (a quarter of genuine windows get flagged), so A is
based on the detector probability *averaged over recent speech windows*
(the session keeps that running mean), then thresholded. Enrollment records
how "fake" the genuine speaker naturally looks on their own mic; a high
baseline raises the threshold to cut false alarms, within bounds.

Cascade: the deck's "cheap filter first" only helps if the cheap model is
reliable in the direction it filters. The wav2vec2-base model misses 83% of
phone-line fakes, so it must NOT be used to skip the heavy model. Plug a
properly trained cheap model (scripts/train_lcnn.py) into `self.cheap`.
"""
from __future__ import annotations

import math

import numpy as np

from ..config import CFG
from .hf_detector import HFDetector


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


class Authenticity:
    SLOPE = 10.0
    THR_DEFAULT = 0.50
    THR_MARGIN = 0.20          # threshold sits this far above the enrolled baseline…
    THR_MAX = 0.75             # …but never so high that clones slip under it

    def __init__(self, cfg=CFG):
        self.heavy = HFDetector(cfg.detector_model, device=cfg.detector_device)
        self.cheap = None

    def window_prob(self, window: np.ndarray) -> dict:
        """Per-window P(fake). Aggregation over time happens in the session."""
        if self.cheap is not None:
            p = self.cheap.fake_prob(window)
            if p > 0.95:        # only short-circuit when the cheap model is sure it's fake
                return {"p": p, "stage": "cheap"}
        return {"p": self.heavy.fake_prob(window), "stage": "heavy"}

    def baseline(self, windows: list[np.ndarray]) -> dict:
        ps = np.array([self.heavy.fake_prob(w) for w in windows])
        return {"mean_p": float(ps.mean()), "flag_rate": float((ps > 0.5).mean()), "n": len(ps)}

    def threshold(self, baseline: dict | None) -> float:
        if not baseline or baseline.get("n", 0) < 3 or "mean_p" not in baseline:
            return self.THR_DEFAULT
        return float(np.clip(baseline["mean_p"] + self.THR_MARGIN, self.THR_DEFAULT, self.THR_MAX))

    def score(self, mean_p: float, baseline: dict | None) -> dict:
        thr = self.threshold(baseline)
        return {"A": _sigmoid(self.SLOPE * (mean_p - thr)), "mean_p": mean_p, "threshold": thr,
                "mode": "enrolled" if thr != self.THR_DEFAULT or baseline else "default"}
