"""Loads every model once and exposes enrollment. Shared by all calls."""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import torch

from .audio import SR
from .config import CFG
from .signals.authenticity import Authenticity
from .signals.behaviour import Behaviour
from .signals.context import ASR
from .signals.speaker import Speaker
from .vad import FRAME, speech_mask

MIN_ENROLL_WINDOWS = 3


def _safe_name(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", name.strip().lower()).strip("-") or "speaker"


class Engine:
    def __init__(self, cfg=CFG, load_asr: bool = True):
        torch.set_num_threads(cfg.torch_threads)
        self.cfg = cfg
        t = time.perf_counter()
        self.auth = Authenticity(cfg)
        self.speaker = Speaker(cfg)
        self.behaviour = Behaviour(cfg)
        self.asr = ASR(cfg) if load_asr else None
        self.load_s = time.perf_counter() - t
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="score")
        self.asr_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="asr")
        cfg.enroll_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ enrollment
    def speech_windows(self, audio: np.ndarray, win_s: float = 3.0, hop_s: float = 1.0,
                       min_frac: float = 0.5) -> list[np.ndarray]:
        mask = speech_mask(audio)
        win, hop, out = int(win_s * SR), int(hop_s * SR), []
        for s in range(0, max(1, len(audio) - win + 1), hop):
            f0, f1 = s // FRAME, (s + win) // FRAME
            if f1 <= len(mask) and mask[f0:f1].mean() >= min_frac:
                out.append(audio[s:s + win])
        return out

    def enroll(self, name: str, audio: np.ndarray, enroll_id: str | None = None) -> dict:
        ws = self.speech_windows(audio)
        if len(ws) < MIN_ENROLL_WINDOWS:
            raise ValueError(f"Need at least ~6 s of clear speech to enroll (got {len(ws)} usable windows)")
        rec = {
            "name": name,
            "id": _safe_name(enroll_id or name),
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "windows": len(ws),
            "voiceprint": self.speaker.voiceprint(ws).round(6).tolist(),
            "detector_baseline": self.auth.baseline(ws),
            "behaviour_baseline": Behaviour.baseline(ws),
        }
        (self.cfg.enroll_dir / f"{rec['id']}.json").write_text(json.dumps(rec))
        return self.summary(rec)

    @staticmethod
    def summary(rec: dict) -> dict:
        return {k: rec[k] for k in ("name", "id", "created", "windows", "detector_baseline")}

    def load_enrollment(self, enroll_id: str | None) -> dict | None:
        if not enroll_id:
            return None
        p = self.cfg.enroll_dir / f"{_safe_name(enroll_id)}.json"
        if not p.exists():
            return None
        rec = json.loads(p.read_text())
        rec["voiceprint"] = np.array(rec["voiceprint"], dtype=np.float32)
        return rec

    def list_enrollments(self) -> list[dict]:
        out = []
        for p in sorted(self.cfg.enroll_dir.glob("*.json")):
            try:
                out.append(self.summary(json.loads(p.read_text())))
            except (json.JSONDecodeError, KeyError):
                continue
        return out
