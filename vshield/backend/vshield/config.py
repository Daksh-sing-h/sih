"""All tunables in one place. Override any value with an env var of the same name."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def _env(name: str, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return type(default)(raw) if not isinstance(default, bool) else raw.lower() in ("1", "true", "yes")


@dataclass
class Config:
    # --- streaming ---------------------------------------------------------
    sample_rate: int = 16_000
    window_s: float = _env("WINDOW_S", 3.0)          # analysis window (deck: 3-second windows)
    hop_s: float = _env("HOP_S", 0.5)                # score update cadence (deck: <0.5 s)
    min_speech_frac: float = 0.5                     # only score windows that are mostly speech
    # utterance cutting for ASR: shorter segments keep Whisper's translation faithful
    # (0.6 s / 8 s dropped the ₹25-lakh clause from our Hindi test; 0.4 s / 6 s kept it)
    utt_end_silence_s: float = 0.4
    utt_max_s: float = 6.0

    # --- models ------------------------------------------------------------
    # ECAPA on the Apple GPU keeps the CPU free for Whisper (see README: latency under load)
    device: str = _env("DEVICE", "mps" if torch.backends.mps.is_available() else "cpu")
    # the XLS-R detector is the heaviest model; Apple GPU halves it (81 vs 155 ms, same outputs)
    detector_device: str = _env("DETECTOR_DEVICE", "mps" if torch.backends.mps.is_available() else "cpu")
    detector_model: str = _env("DETECTOR_MODEL", "Gustking/wav2vec2-large-xlsr-deepfake-audio-classification")
    speaker_model: str = _env("SPEAKER_MODEL", "speechbrain/spkrec-ecapa-voxceleb")
    # Whisper-base, not small: small starves the 0.5 s scoring loop on a laptop CPU (p50 >500 ms)
    # and garbled our Hindi test (C=0.40); base translated it cleanly (C=0.85) in ~1 s.
    asr_model: str = _env("ASR_MODEL", "base")       # faster-whisper size: tiny/base/small/medium
    asr_task: str = _env("ASR_TASK", "translate")    # translate → English text for the rules
    asr_language: str = _env("ASR_LANGUAGE", "")     # "" = auto-detect
    asr_threads: int = _env("ASR_THREADS", 2)
    torch_threads: int = _env("TORCH_THREADS", 2)

    # --- fusion (deck: R = w1*A + w2*S + w3*B + w4*C) ----------------------
    weights: dict = field(default_factory=lambda: {"A": 0.40, "S": 0.20, "B": 0.15, "C": 0.25})
    ema_alpha: float = 0.45                          # smoothing of S and B per window
    a_ema_alpha: float = 0.35                        # longer memory for the noisy detector (A)

    # --- bands (deck: 0-30 low, 30-60 medium, 60-80 high, 80-100 critical) -
    bands: tuple = ((30, "low"), (60, "medium"), (80, "high"), (101, "critical"))

    # --- speaker check -----------------------------------------------------
    speaker_same_cos: float = 0.45                   # cosine at which mismatch score = 0.5

    # --- challenge-response ------------------------------------------------
    challenge_slow_s: float = 2.5                    # reply slower than this looks machine-made

    # --- privacy -----------------------------------------------------------
    log_dir: Path = DATA / "logs"                    # feature-only JSONL; never audio or text
    enroll_dir: Path = DATA / "enrollments"          # voiceprint embeddings + baselines only
    crm_path: Path = DATA / "crm.json"


CFG = Config()
