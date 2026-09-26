"""FastAPI app: enrollment + config REST endpoints and the live-call WebSocket.

Run:  uvicorn vshield.server:app --port 8000
WebSocket protocol (/ws/call?caller_id=...&enrollment=...):
  client → server  binary: 16 kHz mono int16 little-endian PCM, any chunk size
                   text:   {"type": "challenge"} | {"type": "stop"}
  server → client  {"type": "ready" | "score" | "transcript" | "challenge" |
                    "challenge_result" | "ended" | "error", ...}
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
from contextlib import asynccontextmanager

import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .audio import SR, pcm16_to_float, resample
from .config import CFG, DATA, ROOT
from . import rooms
from .engine import Engine, _safe_name
from .session import CallSession
from .signals.context import load_crm

log = logging.getLogger("vshield")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ENGINE: Engine | None = None
DEMO_DIR = DATA / "demo"
FRONTEND_DIST = ROOT.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global ENGINE
    log.info("Loading models (detector, ECAPA, Whisper-%s)…", CFG.asr_model)
    ENGINE = await asyncio.to_thread(Engine, CFG)
    log.info("Models ready in %.1fs", ENGINE.load_s)
    yield


app = FastAPI(title="V-Shield", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _engine() -> Engine:
    if ENGINE is None:
        raise HTTPException(503, "Models are still loading")
    return ENGINE


def _decode_audio(body: bytes) -> np.ndarray:
    """Accept a WAV/FLAC/OGG file or raw 16 kHz int16 PCM."""
    if body[:4] in (b"RIFF", b"fLaC", b"OggS"):
        data, sr = sf.read(io.BytesIO(body), dtype="float32", always_2d=True)
        return resample(data.mean(axis=1), sr, SR)
    return pcm16_to_float(body)


# ------------------------------------------------------------------ REST
@app.get("/api/health")
def health():
    return {"ready": ENGINE is not None,
            "models": {"detector": CFG.detector_model, "speaker": CFG.speaker_model,
                       "asr": f"faster-whisper-{CFG.asr_model}"},
            "load_s": round(ENGINE.load_s, 1) if ENGINE else None}


@app.get("/api/config")
def config():
    crm = load_crm()
    callers = [{"id": k, "name": v["name"], "registered": v.get("registered", False),
                "enrollment": v.get("enrollment")} for k, v in crm.get("callers", {}).items()]
    return {"callers": callers, "enrollments": _engine().list_enrollments(),
            "weights": CFG.weights, "bands": CFG.bands,
            "window_s": CFG.window_s, "hop_s": CFG.hop_s}


@app.post("/api/enroll")
async def enroll(request: Request, name: str, id: str = ""):
    audio = _decode_audio(await request.body())
    if len(audio) < 4 * SR:
        raise HTTPException(400, "Enrollment audio is too short: record at least 10 seconds")
    try:
        return await asyncio.to_thread(_engine().enroll, name, audio, id or None)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/enrollments/{enroll_id}")
def delete_enrollment(enroll_id: str):
    p = CFG.enroll_dir / f"{_safe_name(enroll_id)}.json"
    if not p.exists():
        raise HTTPException(404, "No such enrollment")
    p.unlink()
    return {"deleted": enroll_id}


@app.get("/api/demo")
def demo_clips():
    meta_path = DEMO_DIR / "scenes.json"
    return json.loads(meta_path.read_text()) if meta_path.exists() else {"clips": []}


# ------------------------------------------------------------------ WebSocket
@app.websocket("/ws/room/{room_id}")
async def room_signaling(ws: WebSocket, room_id: str, name: str = "", caller_id: str = ""):
    await rooms.handle(ws, room_id, name, caller_id)


@app.websocket("/ws/call")
async def call(ws: WebSocket, caller_id: str = "", enrollment: str = "", room: str = "", target: str = ""):
    """Analyse one audio stream. In a two-person call, `room` + `target` identify the
    person being analysed so challenge prompts can be pushed to their screen."""
    await ws.accept()
    if ENGINE is None:
        await ws.send_json({"type": "error", "message": "Models are still loading"})
        await ws.close()
        return
    lock = asyncio.Lock()

    async def send(msg: dict):
        async with lock:
            await ws.send_json(msg)

    if not enrollment:  # verify the voice against the identity the caller ID claims
        enrollment = load_crm().get("callers", {}).get(caller_id, {}).get("enrollment", "")

    on_challenge = None
    if room and target:
        async def on_challenge(phrase: str):
            await rooms.send_to(room.upper(), target, {"type": "challenge_prompt", "phrase": phrase})

    session = CallSession(ENGINE, send, caller_id=caller_id, enrollment=enrollment, on_challenge=on_challenge)
    await send({"type": "ready", "session": session.id, "enrolled": session.enr["name"] if session.enr else None,
                "caller": session.ctx.score()["caller"]})
    log.info("call %s started (caller=%s, enrollment=%s)", session.id, caller_id or "-", enrollment or "-")
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes"):
                await session.on_audio(msg["bytes"])
            elif msg.get("text"):
                cmd = json.loads(msg["text"])
                if cmd.get("type") == "challenge":
                    await session.issue_challenge()
                elif cmd.get("type") == "stop":
                    await session.close()
                    await send({"type": "ended", "session": session.id})
                    break
    except WebSocketDisconnect:
        pass
    finally:
        log.info("call %s ended", session.id)


if DEMO_DIR.exists():
    app.mount("/demo", StaticFiles(directory=DEMO_DIR), name="demo")
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
