"""One-time demo setup on a fresh machine.

Downloads a public-domain LibriSpeech speaker (73 short clips, ~10 MB) into
data/eval/real/ and enrolls it as the demo "CEO" voice (id "ceo"), which the demo
clips and scripts/check_scenes.py expect. No server needed.

  cd backend
  .venv/bin/python scripts/setup_demo.py            # Windows: .venv\\Scripts\\python scripts\\setup_demo.py
  .venv/bin/python scripts/setup_demo.py --force    # re-enroll even if 'ceo' exists

Replace this stand-in with your own volunteer via "Enroll a voice" in the Lab page.
"""
from __future__ import annotations

import io
import json
import os
import sys

import numpy as np
import pandas as pd
import soundfile as sf
from huggingface_hub import hf_hub_download

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from vshield.audio import SR, load_wav  # noqa: E402
from vshield.config import CFG, DATA  # noqa: E402

REPO = "hf-internal-testing/librispeech_asr_dummy"
ENROLL_CLIPS = range(6)  # ls_000..ls_005 → enrollment; the demo "genuine" clips use other ones


def download(out_dir) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    if len(list(out_dir.glob("ls_*.wav"))) >= 73:
        print(f"test voice already downloaded ({out_dir})")
        return 73
    path = hf_hub_download(REPO, "clean/validation-00000-of-00001.parquet", repo_type="dataset")
    meta = []
    for i, row in pd.read_parquet(path).iterrows():
        audio, sr = sf.read(io.BytesIO(row["audio"]["bytes"]), dtype="float32")
        f = out_dir / f"ls_{i:03d}.wav"
        sf.write(f, audio, sr)
        meta.append({"file": str(f.relative_to(DATA.parent)), "text": row["text"].lower(), "sr": sr})
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=1))
    print(f"downloaded {len(meta)} clips of LibriSpeech speaker 1272 → {out_dir}")
    return len(meta)


def main():
    real = DATA / "eval" / "real"
    download(real)
    target = CFG.enroll_dir / "ceo.json"
    if target.exists() and "--force" not in sys.argv:
        print("demo CEO voice already enrolled (use --force to redo)")
        return
    from vshield.engine import Engine  # loads the models (first run downloads ~2 GB)

    print("loading models and enrolling the demo CEO voice…")
    gap = np.zeros(int(0.3 * SR), dtype=np.float32)
    audio = np.concatenate([np.concatenate([load_wav(str(real / f"ls_{i:03d}.wav")), gap]) for i in ENROLL_CLIPS])
    summary = Engine(load_asr=False).enroll("Rajesh Mehta (CEO)", audio, "ceo")
    print(f"enrolled '{summary['name']}' as id 'ceo' from {summary['windows']} speech windows")


if __name__ == "__main__":
    main()
