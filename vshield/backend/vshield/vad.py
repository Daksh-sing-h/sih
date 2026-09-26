"""Voice-activity detection (Silero VAD): gates scoring and cuts utterances for ASR."""
from __future__ import annotations

from collections import deque

import numpy as np
import torch
from silero_vad import load_silero_vad

FRAME = 512  # Silero expects 512-sample chunks at 16 kHz (32 ms)
THRESHOLD = 0.5


@torch.inference_mode()
def speech_mask(x: np.ndarray, sr: int = 16_000) -> np.ndarray:
    """Offline per-frame speech flags for a whole clip (used at enrollment)."""
    model = load_silero_vad()
    n = len(x) // FRAME
    frames = torch.from_numpy(x[: n * FRAME].astype(np.float32)).view(n, FRAME)
    return np.array([float(model(f, sr)) >= THRESHOLD for f in frames], dtype=bool)


class StreamingVAD:
    """Per-call incremental VAD. Owns its own (stateful) Silero instance.

    Tracks speech onsets / utterance ends and keeps a short history of
    per-frame flags so windows can be gated without re-running the model.
    """

    def __init__(self, sr: int = 16_000, end_silence_s: float = 0.6, history_s: float = 30.0):
        self.model = load_silero_vad()
        self.sr = sr
        self.frame_s = FRAME / sr
        self.end_frames = int(end_silence_s / self.frame_s)
        self.history = deque(maxlen=int(history_s / self.frame_s))  # (t_start, is_speech)
        self._carry = np.zeros(0, dtype=np.float32)
        self.in_speech = False
        self.silence_run = 0
        self.t = 0.0

    @torch.inference_mode()
    def push(self, x: np.ndarray) -> list[tuple[str, float]]:
        """Feed samples; returns events [('onset', t) | ('end', t)] in stream seconds."""
        buf = np.concatenate([self._carry, x])
        n = len(buf) // FRAME
        self._carry = buf[n * FRAME:]
        events = []
        for i in range(n):
            f = torch.from_numpy(buf[i * FRAME:(i + 1) * FRAME])
            is_speech = float(self.model(f, self.sr)) >= THRESHOLD
            self.history.append((self.t, is_speech))
            if is_speech:
                if not self.in_speech:
                    self.in_speech = True
                    events.append(("onset", self.t))
                self.silence_run = 0
            elif self.in_speech:
                self.silence_run += 1
                if self.silence_run >= self.end_frames:
                    self.in_speech = False
                    events.append(("end", self.t))
            self.t += self.frame_s
        return events

    def speech_fraction(self, t0: float, t1: float) -> float:
        flags = [s for t, s in self.history if t0 <= t < t1]
        return float(np.mean(flags)) if flags else 0.0

    def pauses(self, t0: float, t1: float, min_pause_s: float = 0.25) -> list[float]:
        """Lengths of silent gaps between speech inside [t0, t1)."""
        flags = [s for t, s in self.history if t0 <= t < t1]
        gaps, run, seen_speech = [], 0, False
        for s in flags:
            if s:
                if seen_speech and run * self.frame_s >= min_pause_s:
                    gaps.append(run * self.frame_s)
                run, seen_speech = 0, True
            elif seen_speech:
                run += 1
        return gaps
