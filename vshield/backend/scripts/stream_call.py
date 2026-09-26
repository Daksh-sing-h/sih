"""Stream WAV files into a live V-Shield call and print the risk timeline.

A real call is a continuous stream, so silence is sent between clips (this also
makes challenge-response latency measurable).

Examples:
  python scripts/stream_call.py --caller +91-98100-00001 --enrollment ceo genuine1.wav genuine2.wav
  python scripts/stream_call.py --enrollment ceo clone.wav --challenge-before 2 --answer-delay 4 reply.wav
  python scripts/stream_call.py --json out.json ...        # save every server message
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from urllib.parse import urlencode

import numpy as np
import websockets

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from vshield.audio import SR, float_to_pcm16, load_wav  # noqa: E402

CHUNK_S = 0.1
BAND_ICON = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}


def fmt(msg: dict) -> str | None:
    t = msg["type"]
    if t == "score":
        s = msg["signals"]
        sig = " ".join(f"{k}={'  – ' if v is None else f'{v:.2f}'}" for k, v in s.items())
        rules = f"  ⚑ {'; '.join(msg['rules'])}" if msg["rules"] else ""
        pm = f"{msg['proc_ms']:.0f}ms" if msg["proc_ms"] else "  –  "
        tag = "" if msg["reason"] == "audio" else f" [{msg['reason']}]"
        return (f"t={msg['t']:6.1f}s {BAND_ICON[msg['band']]} R={msg['R']:5.1f} {msg['band']:<8} "
                f"{sig}  {pm}{'' if msg['speech'] else ' (no speech)'}{tag}{rules}")
    if t == "transcript":
        return f"          📝 [{msg['lang']}] {msg['text']}   ({msg['asr_ms']} ms)"
    if t == "challenge":
        return f"          ❓ CHALLENGE: “{msg['phrase']}”"
    if t == "challenge_result":
        return f"          ⏱  answered after {msg['latency_s']} s{'  (SLOW)' if msg['slow'] else ''}"
    if t in ("ready", "ended", "error"):
        return f"--- {t}: {json.dumps({k: v for k, v in msg.items() if k != 'type'})}"
    return None


async def stream(files: list[str], server: str = "ws://127.0.0.1:8000", caller: str = "",
                 enrollment: str = "", gap: float = 1.0, challenge_before: int = 0,
                 answer_delay: float = 0.8, speed: float = 1.0, verbose: bool = True,
                 quiet: bool = False) -> list[dict]:
    """Stream clips into one call; returns every server message."""
    q = urlencode({"caller_id": caller, "enrollment": enrollment})
    messages = []
    async with websockets.connect(f"{server}/ws/call?{q}", max_size=None) as ws:
        async def reader():
            async for raw in ws:
                msg = json.loads(raw)
                messages.append(msg)
                line = fmt(msg)
                if verbose and line and not (quiet and msg["type"] == "score" and msg["reason"] == "audio"
                                             and not msg["rules"]):
                    print(line, flush=True)
                if msg["type"] in ("ended", "error"):
                    return

        read_task = asyncio.create_task(reader())
        await asyncio.sleep(0.3)
        chunk = int(CHUNK_S * SR)
        pace = CHUNK_S / speed

        async def send_audio(x: np.ndarray):
            for i in range(0, len(x), chunk):
                await ws.send(float_to_pcm16(x[i:i + chunk]))
                await asyncio.sleep(pace)

        silence = lambda s: np.zeros(int(s * SR), dtype=np.float32)  # noqa: E731
        await send_audio(silence(0.5))
        for i, path in enumerate(files, start=1):
            if challenge_before == i:
                await ws.send(json.dumps({"type": "challenge"}))
                await send_audio(silence(answer_delay))
            if verbose:
                print(f"▶ {os.path.basename(path)}", flush=True)
            await send_audio(load_wav(path))
            await send_audio(silence(gap))
        await ws.send(json.dumps({"type": "stop"}))
        await asyncio.wait_for(read_task, timeout=60)
    return messages


def summary(messages: list[dict]) -> dict:
    scores = [m for m in messages if m["type"] == "score"]
    pms = [m["proc_ms"] for m in scores if m.get("proc_ms")]
    peak = max(scores, key=lambda m: m["R"]) if scores else None
    return {
        "peak_R": peak["R"] if peak else None, "peak_band": peak["band"] if peak else None,
        "final_R": scores[-1]["R"] if scores else None, "final_band": scores[-1]["band"] if scores else None,
        "p50_ms": float(np.median(pms)) if pms else None, "p95_ms": float(np.percentile(pms, 95)) if pms else None,
        "skipped": scores[-1]["skipped"] if scores else None,
    }


async def run(args):
    messages = await stream(args.files, args.server, args.caller, args.enrollment, args.gap,
                            args.challenge_before, args.answer_delay, args.speed, quiet=args.quiet)
    if args.json:
        json.dump(messages, open(args.json, "w"), indent=1, ensure_ascii=False)
    s = summary(messages)
    if s["peak_R"] is not None:
        print(f"\nPeak R={s['peak_R']} ({s['peak_band']}) · final R={s['final_R']} ({s['final_band']}) · "
              f"proc p50={s['p50_ms']:.0f}ms p95={s['p95_ms']:.0f}ms · skipped hops={s['skipped']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--server", default="ws://127.0.0.1:8000")
    ap.add_argument("--caller", default="")
    ap.add_argument("--enrollment", default="")
    ap.add_argument("--gap", type=float, default=1.0, help="silence between clips (s)")
    ap.add_argument("--challenge-before", type=int, default=0, help="issue a challenge before clip N (1-based)")
    ap.add_argument("--answer-delay", type=float, default=0.8, help="silence between challenge and that clip")
    ap.add_argument("--speed", type=float, default=1.0, help=">1 streams faster than real time")
    ap.add_argument("--quiet", action="store_true", help="only print transcripts, rules and events")
    ap.add_argument("--json", help="save all server messages to this file")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
