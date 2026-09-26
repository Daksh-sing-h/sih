"""Audio utilities shared by the server, signals and scripts."""
from __future__ import annotations

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

SR = 16_000


def load_wav(path: str, sr: int = SR) -> np.ndarray:
    """Load any soundfile-readable audio as mono float32 at `sr`."""
    data, file_sr = sf.read(path, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    return resample(mono, file_sr, sr)


def resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out:
        return x.astype(np.float32, copy=False)
    g = np.gcd(sr_in, sr_out)
    return resample_poly(x, sr_out // g, sr_in // g).astype(np.float32)


def pcm16_to_float(buf: bytes) -> np.ndarray:
    return np.frombuffer(buf, dtype="<i2").astype(np.float32) / 32768.0


def float_to_pcm16(x: np.ndarray) -> bytes:
    return (np.clip(x, -1.0, 1.0) * 32767).astype("<i2").tobytes()


def rms_db(x: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(x**2)) + 1e-9))


# ------------------------------------------------------------------ phone sim
def mulaw_roundtrip(x: np.ndarray, mu: int = 255) -> np.ndarray:
    """G.711 μ-law encode + decode (8-bit companding), as on a PSTN line."""
    x = np.clip(x, -1.0, 1.0)
    y = np.sign(x) * np.log1p(mu * np.abs(x)) / np.log1p(mu)
    q = np.round((y + 1) / 2 * mu) / mu * 2 - 1          # 8-bit quantisation
    return (np.sign(q) * ((1 + mu) ** np.abs(q) - 1) / mu).astype(np.float32)


def phone_channel(x: np.ndarray, sr: int = SR, rng: np.random.Generator | None = None,
                  noise_snr_db: float | None = 25.0, packet_loss: float = 0.0) -> np.ndarray:
    """Simulate a narrowband phone call: 8 kHz, μ-law, optional noise and packet loss."""
    rng = rng or np.random.default_rng()
    y = resample(x, sr, 8_000)
    y = mulaw_roundtrip(y)
    if packet_loss > 0:                                   # drop 20 ms frames
        frame = 160
        for s in range(0, len(y) - frame, frame):
            if rng.random() < packet_loss:
                y[s:s + frame] = 0.0
    y = resample(y, 8_000, sr)
    if noise_snr_db is not None:
        p_sig = np.mean(y**2) + 1e-12
        p_noise = p_sig / (10 ** (noise_snr_db / 10))
        y = y + rng.normal(0, np.sqrt(p_noise), len(y)).astype(np.float32)
    return np.clip(y, -1, 1).astype(np.float32)


def windows(x: np.ndarray, win_s: float = 3.0, hop_s: float = 1.5, sr: int = SR):
    """Yield fixed-length windows (zero-padded tail) over a clip."""
    win, hop = int(win_s * sr), int(hop_s * sr)
    if len(x) <= win:
        yield np.pad(x, (0, win - len(x)))
        return
    for s in range(0, len(x) - win + 1, hop):
        yield x[s:s + win]
