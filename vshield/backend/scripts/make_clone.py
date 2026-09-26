"""Clone a (consenting!) speaker's voice with F5-TTS to create realistic attack clips.

Runs in its own environment because F5-TTS pins different library versions:
  cd vshield/tools && uv venv --python 3.11 .venv-clone && uv pip install --python .venv-clone/bin/python f5-tts
  tools/.venv-clone/bin/python backend/scripts/make_clone.py \
      --ref me.wav --ref-text "exact words spoken in me.wav" \
      --text "Transfer twenty five lakh rupees to the new vendor account right now." \
      --out backend/data/demo/clone_fraud.wav

  --ref       5-10 s of clean speech from the person being cloned (longer is clipped)
  --ref-text  exactly what is said in --ref (leave empty to auto-transcribe)
  --text      what the clone should say; repeat --text/--out pairs for several clips

F5-TTS weights are CC-BY-NC 4.0 (fine for a hackathon demo, not for commercial use).
The base model speaks English and Chinese; for Hindi clones see the README.
Only clone voices of people who have agreed to it.
"""
from __future__ import annotations

import argparse
import time


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", required=True)
    ap.add_argument("--ref-text", default="")
    ap.add_argument("--text", action="append", required=True)
    ap.add_argument("--out", action="append", required=True)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    if len(args.text) != len(args.out):
        ap.error("give one --out per --text")

    from f5_tts.api import F5TTS  # heavy import; after arg parsing

    t = time.perf_counter()
    tts = F5TTS()
    print(f"model loaded on {tts.device} in {time.perf_counter() - t:.0f}s")
    for text, out in zip(args.text, args.out):
        t = time.perf_counter()
        _, sr, _ = tts.infer(ref_file=args.ref, ref_text=args.ref_text, gen_text=text,
                             file_wave=out, seed=args.seed, show_info=lambda *a, **k: None)
        print(f"wrote {out} ({sr} Hz) in {time.perf_counter() - t:.0f}s")


if __name__ == "__main__":
    main()
