"""Feature-only audit log (deck: "no raw audio, feature-only logs").

Each line holds scores, band, rule names and flag *categories*. Never audio,
never transcript text, never embeddings.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .config import CFG

ALLOWED = {"t", "session", "R", "band", "signals", "rules", "flags", "proc_ms", "event", "latency_s"}


class PrivacyLog:
    def __init__(self, session_id: str, log_dir: Path = CFG.log_dir):
        log_dir.mkdir(parents=True, exist_ok=True)
        self.path = log_dir / f"{time.strftime('%Y%m%d-%H%M%S')}_{session_id}.jsonl"
        self.session_id = session_id

    def write(self, **fields):
        row = {k: v for k, v in fields.items() if k in ALLOWED}
        row.setdefault("session", self.session_id)
        with self.path.open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
