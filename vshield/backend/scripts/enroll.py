"""Enroll a genuine voice from one or more audio files (≥10 s of speech in total).

  python scripts/enroll.py "Rajesh Mehta (CEO)" --id ceo me1.wav me2.wav
"""
from __future__ import annotations

import argparse
import io
import os
import sys

import numpy as np
import requests
import soundfile as sf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from vshield.audio import SR, load_wav  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--id", help="enrollment id (defaults to a slug of the name)")
    ap.add_argument("--server", default="http://127.0.0.1:8000")
    args = ap.parse_args()

    gap = np.zeros(int(0.3 * SR), dtype=np.float32)
    audio = np.concatenate([np.concatenate([load_wav(f), gap]) for f in args.files])
    buf = io.BytesIO()
    sf.write(buf, audio, SR, format="WAV", subtype="PCM_16")
    r = requests.post(f"{args.server}/api/enroll", params={"name": args.name, "id": args.id or ""},
                      data=buf.getvalue(), timeout=300)
    print(r.status_code, r.json())


if __name__ == "__main__":
    main()
