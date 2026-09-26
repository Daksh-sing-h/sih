"""Signal S — speaker identity (ECAPA-TDNN voiceprint vs. the enrolled genuine voice).

S is a *mismatch* score: 0 = sounds like the enrolled person, 1 = a different voice.
Good clones often pass this check (low S). That is expected: S is there to catch
human impersonators and cheap clones, and fusion never lets it clear a call alone.
"""
from __future__ import annotations

import math

import numpy as np
import torch
from speechbrain.inference.speaker import EncoderClassifier

from ..config import CFG, ROOT


class Speaker:
    SLOPE = 10.0

    def __init__(self, cfg=CFG):
        self.same_cos = cfg.speaker_same_cos
        self.enc = EncoderClassifier.from_hparams(
            source=cfg.speaker_model,
            savedir=str(ROOT / "models" / "cache" / cfg.speaker_model.replace("/", "__")),
            run_opts={"device": cfg.device},
        )
        self.enc.eval()

    @torch.inference_mode()
    def embed(self, window: np.ndarray) -> np.ndarray:
        wav = torch.from_numpy(window.astype(np.float32)).unsqueeze(0)
        e = self.enc.encode_batch(wav).squeeze().cpu().numpy()
        return e / (np.linalg.norm(e) + 1e-9)

    def voiceprint(self, windows: list[np.ndarray]) -> np.ndarray:
        e = np.mean([self.embed(w) for w in windows], axis=0)
        return e / (np.linalg.norm(e) + 1e-9)

    def score(self, window: np.ndarray, voiceprint: np.ndarray | None) -> dict:
        if voiceprint is None:
            return {"S": None, "cos": None}
        cos = float(np.dot(self.embed(window), voiceprint))
        s = 1.0 / (1.0 + math.exp(self.SLOPE * (cos - self.same_cos)))
        return {"S": s, "cos": cos}
