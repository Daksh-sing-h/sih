"""One live call: streaming buffer, speech gating, scoring hops, ASR lane, challenges."""
from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from typing import Awaitable, Callable

import numpy as np

from .audio import SR, pcm16_to_float
from .config import CFG
from .engine import Engine
from .fusion import fuse
from .policy import MATCH_OK, challenge_phrase, phrase_match
from .privacy_log import PrivacyLog
from .signals.context import ContextState
from .vad import StreamingVAD

Send = Callable[[dict], Awaitable[None]]


class RingBuffer:
    """Keeps the last `seconds` of audio, addressable by absolute sample index."""

    def __init__(self, seconds: float = 30.0):
        self.size = int(seconds * SR)
        self.buf = np.zeros(self.size, dtype=np.float32)
        self.total = 0

    def push(self, x: np.ndarray):
        step = self.size // 2
        for s in range(0, len(x), step):
            self._push(x[s:s + step])

    def _push(self, x: np.ndarray):
        n = len(x)
        i = self.total % self.size
        first = min(n, self.size - i)
        self.buf[i:i + first] = x[:first]
        self.buf[:n - first] = x[first:]
        self.total += n

    def get(self, start: int, end: int) -> np.ndarray:
        start = max(start, self.total - self.size, 0)
        end = min(end, self.total)
        if end <= start:
            return np.zeros(0, dtype=np.float32)
        idx = np.arange(start, end) % self.size
        return self.buf[idx]


class CallSession:
    PRE_ROLL_S = 0.2

    def __init__(self, engine: Engine, send: Send, caller_id: str = "", enrollment: str = "",
                 on_challenge: Callable[[str], Awaitable[None]] | None = None):
        self.engine, self.send, self.cfg = engine, send, engine.cfg
        self.id = uuid.uuid4().hex[:8]
        self.ring = RingBuffer()
        self.vad = StreamingVAD(end_silence_s=self.cfg.utt_end_silence_s)
        self.ctx = ContextState(caller_id=caller_id)
        self.enr = engine.load_enrollment(enrollment)
        self.log = PrivacyLog(self.id)
        self.win = int(self.cfg.window_s * SR)
        self.hop = int(self.cfg.hop_s * SR)
        self.next_hop = self.win
        self.busy = False
        self.skipped = 0
        self.proc_ms: deque[float] = deque(maxlen=100)
        self.ema: dict[str, float] = {}
        self.ema_p: float | None = None
        self.details: dict = {}
        self.utt_start: float | None = None
        self.asr_tasks: set[asyncio.Task] = set()
        self.challenge: dict | None = None
        self.last_score: dict | None = None
        self._last_t = 0.0
        self.on_challenge = on_challenge  # e.g. push the phrase to the caller's screen

    @property
    def now(self) -> float:
        return self.ring.total / SR

    # ------------------------------------------------------------ audio in
    async def on_audio(self, pcm: bytes):
        x = pcm16_to_float(pcm)
        if len(x) == 0:
            return
        self.ring.push(x)
        for kind, t in self.vad.push(x):
            if kind == "onset":
                self.utt_start = t
                await self._maybe_challenge_answered(t)
            elif kind == "end" and self.utt_start is not None:
                self._submit_asr(self.utt_start, t)
                self.utt_start = None
        if self.utt_start is not None and self.now - self.utt_start > self.cfg.utt_max_s:
            self._submit_asr(self.utt_start, self.now)
            self.utt_start = self.now

        if self.ring.total >= self.next_hop:
            # catch up to the latest hop; never queue stale windows
            hops_due = (self.ring.total - self.next_hop) // self.hop + 1
            end = self.next_hop + (hops_due - 1) * self.hop
            self.next_hop = end + self.hop
            if self.busy:
                self.skipped += hops_due
            else:
                self.skipped += hops_due - 1
                self.busy = True
                asyncio.create_task(self._score(end))

    # ------------------------------------------------------------ scoring
    async def _score(self, end: int):
        try:
            t1 = end / SR
            t0 = t1 - self.cfg.window_s
            speech_frac = self.vad.speech_fraction(t0, t1)
            if speech_frac >= self.cfg.min_speech_frac:
                window = self.ring.get(end - self.win, end)
                pauses = self.vad.pauses(t0, t1)
                started = time.perf_counter()
                res = await asyncio.get_running_loop().run_in_executor(
                    self.engine.pool, self._score_audio, window, pauses)
                self.proc_ms.append((time.perf_counter() - started) * 1000)
                # windows with more speech carry more weight (a half-silent window says little)
                w = min(1.0, speech_frac)
                # A: average the raw detector probability over recent speech, then threshold
                p = res["A"]["p"]
                a_ = self.cfg.a_ema_alpha * w
                self.ema_p = p if self.ema_p is None else a_ * p + (1 - a_) * self.ema_p
                a_score = self.engine.auth.score(self.ema_p, (self.enr or {}).get("detector_baseline"))
                self.ema["A"] = a_score["A"]
                self.details["A"] = {**a_score, "p_window": p, "stage": res["A"]["stage"]}
                for key, val in (("S", res["S"]["S"]), ("B_voice", res["B"]["b_voice"])):
                    if val is None:
                        continue
                    a = self.cfg.ema_alpha * w
                    self.ema[key] = val if key not in self.ema else a * val + (1 - a) * self.ema[key]
                self.details["S"] = res["S"]
                self.details["B"] = res["B"]
                await self._emit(t1, speech=True)
            else:
                await self._emit(t1, speech=False)
        finally:
            self.busy = False

    def _score_audio(self, window: np.ndarray, pauses: list[float]) -> dict:
        enr = self.enr or {}
        return {
            "A": self.engine.auth.window_prob(window),
            "S": self.engine.speaker.score(window, enr.get("voiceprint")),
            "B": self.engine.behaviour.score(window, enr.get("behaviour_baseline"), pauses),
        }

    async def _emit(self, t: float, speech: bool, reason: str = "audio"):
        t = self._last_t = max(t, self._last_t)   # context updates can race audio scores
        c = self.ctx.score()
        latency = self.challenge.get("latency_s") if self.challenge else None
        b_latency = None if latency is None else self.engine.behaviour.latency_score(latency)
        signals = {
            "A": self.ema.get("A"),
            "S": self.ema.get("S") if self.enr else None,
            "B": self.engine.behaviour.combine(self.ema.get("B_voice"), b_latency),
            "C": c["C"],
        }
        if "B" in self.details or b_latency is not None:
            self.details["B"] = {**self.details.get("B", {}), "b_latency": b_latency,
                                 "b_voice": self.ema.get("B_voice")}
        ch = self.challenge or {}
        fused = fuse(signals, events={"challenge_failed": ch.get("match") is not None and ch["match"] < MATCH_OK,
                                      "stages": c["stages"]})
        pm = list(self.proc_ms)
        msg = {
            "type": "score", "t": round(t, 2), "speech": speech, "reason": reason,
            **fused,
            "signals": {k: (None if v is None else round(v, 3)) for k, v in signals.items()},
            "details": {**{k: _round(v) for k, v in self.details.items()}, "C": c},
            "proc_ms": round(pm[-1], 1) if pm else None,
            "proc_ms_p95": round(float(np.percentile(pm, 95)), 1) if pm else None,
            "skipped": self.skipped,
            "enrolled": self.enr["name"] if self.enr else None,
        }
        self.last_score = msg
        await self.send(msg)
        self.log.write(t=msg["t"], R=msg["R"], band=msg["band"], signals=msg["signals"],
                       rules=msg["rules"], flags=sorted(c["terms"]), proc_ms=msg["proc_ms"])

    # ------------------------------------------------------------ ASR lane
    def _submit_asr(self, t0: float, t1: float):
        s0 = int(max(0.0, t0 - self.PRE_ROLL_S) * SR)
        audio = self.ring.get(s0, int(t1 * SR))
        if len(audio) < int(0.4 * SR) or self.engine.asr is None:
            return
        task = asyncio.create_task(self._asr(audio, t0, t1))
        self.asr_tasks.add(task)
        task.add_done_callback(self.asr_tasks.discard)

    async def _asr(self, audio: np.ndarray, t0: float, t1: float):
        loop = asyncio.get_running_loop()
        started = time.perf_counter()
        text, lang = await loop.run_in_executor(self.engine.asr_pool, self.engine.asr.transcribe, audio)
        if not text:
            return
        res = self.ctx.add_utterance(text)
        await self.send({
            "type": "transcript", "t0": round(t0, 2), "t1": round(t1, 2), "text": text,
            "lang": lang, "spans": res["spans"],
            "asr_ms": round((time.perf_counter() - started) * 1000),
        })
        ch = self.challenge
        if ch and "match" not in ch and ch["latency_s"] is not None and t0 >= ch["issued_at"] - 0.2:
            ch["match"] = phrase_match(ch["phrase"], text)
            await self.send({"type": "challenge_verdict", "matched": ch["match"] >= MATCH_OK,
                             "match": round(ch["match"], 2), "heard": text})
            self.log.write(event="challenge_verdict", t=round(t0, 2))
        await self._emit(self.now, speech=False, reason="context")

    # ------------------------------------------------------------ challenges
    async def issue_challenge(self):
        self.challenge = {"phrase": challenge_phrase(), "issued_at": self.now, "latency_s": None}
        await self.send({"type": "challenge", "phrase": self.challenge["phrase"],
                         "issued_at": round(self.now, 2), "pushed": self.on_challenge is not None})
        if self.on_challenge is not None:
            await self.on_challenge(self.challenge["phrase"])
        self.log.write(event="challenge_issued", t=round(self.now, 2))

    async def _maybe_challenge_answered(self, onset: float):
        ch = self.challenge
        if ch and ch["latency_s"] is None and onset >= ch["issued_at"]:
            ch["latency_s"] = round(onset - ch["issued_at"], 2)
            await self.send({"type": "challenge_result", "latency_s": ch["latency_s"],
                             "slow": ch["latency_s"] > self.cfg.challenge_slow_s})
            await self._emit(onset, speech=True, reason="challenge")
            self.log.write(event="challenge_answered", latency_s=ch["latency_s"], t=round(onset, 2))

    # ------------------------------------------------------------ teardown
    async def close(self):
        if self.utt_start is not None:
            self._submit_asr(self.utt_start, self.now)
        if self.asr_tasks:
            await asyncio.wait(list(self.asr_tasks), timeout=15)
        await self._emit(self.now, speech=False, reason="final")


def _round(d):
    if isinstance(d, dict):
        return {k: _round(v) for k, v in d.items()}
    if isinstance(d, float):
        return round(d, 3)
    return d
