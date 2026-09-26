"""Signal B — speech behaviour: pitch, voice quality, pauses, and challenge-response latency.

Voice features are compared with the enrolled speaker's own baseline (z-scores).
Response latency is the strongest behavioural cue: a real person repeats a
random challenge phrase in about a second, while an attacker who has to type it
into a cloning tool takes several.

The weights here are hand-set priors; refit them once you have labelled calls.
"""
from __future__ import annotations

import math

import numpy as np
import parselmouth
from parselmouth.praat import call

from ..config import CFG

FEATURES = ("f0_mean_st", "f0_sd_st", "jitter", "shimmer", "hnr")


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _num(v) -> float | None:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def voice_features(window: np.ndarray, sr: int = 16_000) -> dict:
    snd = parselmouth.Sound(window.astype(np.float64), sampling_frequency=sr)
    pitch = snd.to_pitch(time_step=0.01, pitch_floor=75, pitch_ceiling=500)
    f0 = pitch.selected_array["frequency"]
    f0 = f0[f0 > 0]
    feats = {k: None for k in FEATURES}
    if len(f0) >= 10:
        st = 12 * np.log2(f0 / 100.0)                       # semitones re 100 Hz
        feats["f0_mean_st"] = float(np.mean(st))
        feats["f0_sd_st"] = float(np.std(st))
        pp = call(snd, "To PointProcess (periodic, cc)", 75, 500)
        feats["jitter"] = _num(call(pp, "Get jitter (local)", 0, 0, 0.0001, 0.02, 1.3))
        feats["shimmer"] = _num(call([snd, pp], "Get shimmer (local)", 0, 0, 0.0001, 0.02, 1.3, 1.6))
        feats["hnr"] = _num(call(snd.to_harmonicity_cc(), "Get mean", 0, 0))
    return feats


class Behaviour:
    def __init__(self, cfg=CFG):
        self.slow_s = cfg.challenge_slow_s

    @staticmethod
    def baseline(windows: list[np.ndarray]) -> dict:
        rows = [voice_features(w) for w in windows]
        out = {}
        for k in FEATURES:
            vals = [r[k] for r in rows if r[k] is not None]
            if len(vals) >= 3:
                out[k] = {"mu": float(np.mean(vals)), "sd": float(np.std(vals))}
        return out

    # minimum spreads so a quiet enrollment doesn't make everything look anomalous
    MIN_SD = {"f0_mean_st": 1.5, "f0_sd_st": 0.8, "jitter": 0.004, "shimmer": 0.02, "hnr": 2.0}

    def score(self, window: np.ndarray, baseline: dict | None, pauses: list[float]) -> dict:
        """Voice-feature anomaly vs the enrolled baseline (per window)."""
        feats = voice_features(window)
        zs = {}
        if baseline:
            for k, stats in baseline.items():
                v = feats.get(k)
                if v is not None:
                    zs[k] = abs(v - stats["mu"]) / max(stats["sd"], self.MIN_SD[k])
        # combine the two most anomalous features (robust to one noisy feature)
        top = sorted(zs.values(), reverse=True)[:2]
        z_comb = float(np.mean(top)) if top else 0.0
        b_voice = _sigmoid(1.5 * (z_comb - 2.5)) if top else 0.0
        return {"b_voice": b_voice, "z": {k: round(v, 2) for k, v in zs.items()}, "pauses": len(pauses)}

    def latency_score(self, latency_s: float) -> float:
        """Challenge-response delay → anomaly (0.5 at `challenge_slow_s`)."""
        return _sigmoid(2.5 * (latency_s - self.slow_s))

    @staticmethod
    def combine(b_voice: float | None, b_latency: float | None) -> float | None:
        if b_voice is None and b_latency is None:
            return None
        v = 0.8 * (b_voice or 0.0)
        return v if b_latency is None else max(v, b_latency)
