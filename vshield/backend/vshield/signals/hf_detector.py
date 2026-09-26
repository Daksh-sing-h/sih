"""Wrapper around a Hugging Face audio-classification anti-spoofing model."""
from __future__ import annotations

import threading

import numpy as np
import torch
from transformers import AutoFeatureExtractor, AutoModelForAudioClassification

FAKE_LABELS = {"fake", "spoof", "synthetic", "deepfake"}


class HFDetector:
    """Returns P(fake) for a 16 kHz mono window."""

    def __init__(self, model_id: str, device: str = "cpu"):
        self.model_id = model_id
        self.device = device
        self.fe = AutoFeatureExtractor.from_pretrained(model_id)
        self.model = AutoModelForAudioClassification.from_pretrained(model_id).to(device).eval()
        labels = {int(k): v.lower() for k, v in self.model.config.id2label.items()}
        fake = [i for i, name in labels.items() if name in FAKE_LABELS]
        if len(fake) != 1:
            raise ValueError(f"{model_id}: can't find the fake class in {labels}")
        self.fake_idx = fake[0]
        self._lock = threading.Lock()  # MPS isn't safe for concurrent use across threads

    @torch.inference_mode()
    def fake_prob(self, x: np.ndarray, sr: int = 16_000) -> float:
        inputs = self.fe(x, sampling_rate=sr, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with self._lock:
            logits = self.model(**inputs).logits[0]
            return float(torch.softmax(logits, dim=-1)[self.fake_idx])
