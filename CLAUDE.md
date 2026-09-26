# V-Shield (SIH26104 prototype) — working notes

Team NoNsEnSe's SIH 2026 prototype: real-time voice-clone / fraud-risk scoring for calls.
User-facing docs, demo script and measured results are in README.md. This file holds
the non-obvious lessons from the build.

## Run / test
- `./run.sh` → http://127.0.0.1:8000 (FastAPI serves `frontend/dist`; rebuild with `npm run build` after UI changes and restart the server, since the static mount is set up at import time).
- `backend/.venv/bin/python -m pytest backend/tests -q`: fast unit tests (rules, fusion, challenge, buffer).
- `backend/.venv/bin/python backend/scripts/check_scenes.py`: end-to-end, needs the server running and the `ceo` enrollment. Expect 8/8 (scene 2c is info-only).
- Frontend dev with hot reload: `cd frontend && npx vite` (proxies /api, /ws, /demo to :8000).

## Decisions backed by measurements (don't undo without re-measuring)
- **Detector = Gustking XLS-R**, not mo-thecreator: the base model catches only 17% of phone-line fakes (vs. 98%). Both give ~binary per-window outputs, so A uses a *running mean of P(fake)* over speech windows, not per-window z-scores (logit σ≈7.9 made z-scores useless).
- **No "cheap-first" cascade**: the cheap model can't safely skip the heavy one (it misses phone fakes). `Authenticity.cheap` only short-circuits on confident-fake.
- **Whisper `base`, not `small`**: small starves the scoring loop (p50 >500 ms while transcribing) and garbled Hindi (C=0.40); base in **translate** mode gave clean English (C=0.85) in ~1 s.
- **ECAPA + detector on MPS, torch 2 threads, Whisper 2 threads**: that keeps updates ~230 ms p95 during ASR. The detector has a lock because MPS isn't thread-safe.
- **Utterance cut at 0.4 s pause / 6 s max**: longer segments made Whisper-translate drop the ₹-amount clause.
- **Only score windows ≥50% speech, and weight smoothing by speech fraction**: short, mostly-silent windows made the detector read clones as real.
- Challenge latency feeds B at emit time (not per window), because a short reply may never fill a scoreable window.

- **Real-clone result (F5-TTS clone of the enrolled speaker):** ECAPA is fooled (cos 0.52–0.71), A reaches 0.44–0.78, so routine clone calls land low/medium and only clone + fraud request goes critical. Improving A on clones (fine-tuning) is the top ML priority; check_scenes reports scene 2c as info-only so progress shows.

## Two-person call architecture
- `/?room=CODE` → `frontend/src/call/CallPage.tsx`. `useRoom` does WebRTC: whoever is already in the room makes the offer when someone joins; ICE candidates are queued until the remote description is set; on `peer_left` the RTCPeerConnection is rebuilt so a rejoin works.
- Audio is peer-to-peer. `vshield/rooms.py` only relays offer/answer/ICE and pushes `challenge_prompt`. Rooms are in memory: a server restart drops every call.
- Each browser analyses the audio it *receives* (`useCall.start(..., {stream: remoteStream, room, target})`). The server resolves the enrollment from the claimed caller ID via `crm.json` → `enrollment`.
- Outgoing audio is an `OutgoingAudio` graph (mic with echo cancellation + clip injection → MediaStreamDestination), so clips can be "sent into the call" and it works without a mic.
- The remote stream is also attached to an `<audio>` element: that's needed to hear it, and Chrome won't feed remote WebRTC audio into Web Audio otherwise.
- Mic and AudioWorklet need a secure context: localhost or HTTPS. For two laptops use `./run.sh --lan` (self-signed cert for the Wi-Fi IP, port 8443). The Claude browser pane blocks mic access, so test calls there with clips.
- `hasEvidence()` in `types.ts`: don't show a verdict until a speech window is scored or something risky is *said* (an unknown caller ID alone isn't evidence).

## Gotchas
- React effects must not use expression bodies that return values: `scrollIntoView()` now returns a Promise in Chromium, and React called it as cleanup → blank page (`destroy_ is not a function`).
- The AudioContext is created at 16 kHz inside the Start-call click (autoplay policy). The worklet keeps emitting silence so the stream stays continuous, which challenge timing depends on.
- LibriSpeech test speaker 1272 looks "fake" to the detector (mean P≈0.67). Its enrollment threshold caps at 0.75; one clip set still false-alarms to R≈34 (medium).
- In zsh, `${PIPESTATUS[0]}` is empty; use `$?` or `$pipestatus`.
- F5-TTS lives in `tools/.venv-clone` (separate environment, conflicting pins). XTTS-v2 (needed for Hindi clones) requires the user to accept the Coqui CPML licence themselves.
