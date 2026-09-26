# V-Shield prototype

**SIH 2026 · SIH26104 · Team NoNsEnSe.** A real-time voice-impersonation and fraud-risk firewall for calls.

Two people talk on a real voice call in the browser. On each side, V-Shield listens to what you hear from the *other* person: it scores their voice every 0.5 s on four independent signals, tracks whether the conversation is following the scam script (hook → pressure → isolation → ask), and tells you what to do: continue, verify, challenge, or hold the transaction. Everything runs on one laptop with no cloud calls.

```
browser mic / clip ──► WebSocket (16 kHz PCM) ──► FastAPI call session
                                                    ├─ A  authenticity   wav2vec2-XLS-R deepfake detector (Apple GPU)
                                                    ├─ S  speaker        ECAPA-TDNN voiceprint vs. enrolled voice
                                                    ├─ B  behaviour      pitch/voice quality (Praat) + challenge latency
                                                    └─ C  context        Whisper (local) → rules + caller record  [async lane]
                                                  fusion: R = 0.40A + 0.20S + 0.15B + 0.25C + escalation rules
                                                  bands: 0–30 low · 30–60 medium · 60–80 high · 80–100 critical
```

## Two-person call (the main demo)

```
 caller's browser ──── WebRTC peer-to-peer voice (Opus) ────► receiver's browser
   (mic, or a clone clip                                          │  plays the call audio
    sent into the call)                                           └─► streams what it HEARS to /ws/call
        ▲                                                              → V-Shield scores the caller
        └─── challenge phrase pushed to the caller's screen ◄──── /ws/room (signaling only; no audio)
```

- **Home page** (`/`): *Start a call* makes a room link; the other person opens it and joins.
- **Before joining**, each person picks their name and the **caller ID the other side sees**. Pick "Rajesh Mehta (CEO)" to play a scammer spoofing the CEO's number: V-Shield then checks the voice against the CEO's enrolled voiceprint.
- **On the call**, each side sees V-Shield for the *other* person: gauge, what to do, the **scam-script tracker**, the four signals, what they said (risky phrases highlighted), and the risk timeline.
- **Challenge the caller** pops a random phrase up on *their* screen; V-Shield times the reply and checks the words.
- **Send audio into the call** plays a clip (e.g. the cloned CEO) instead of your mic, the way an attacker feeds a clone into a real call.
- **Enroll this caller's voice** records 15 s of a trusted caller *from the call itself*, so later calls are checked on the same channel.

**One laptop:** `./run.sh`, open `http://127.0.0.1:8000` in two browser windows, start a call in one and paste the link into the other. Use headphones.

**Two laptops on the same Wi-Fi:** `./run.sh --lan` prints `https://<ip>:8443`. Open it on both laptops and click *Advanced → Proceed* past the self-signed-certificate warning (browsers only allow the microphone on localhost or HTTPS). No login, so only use it on a network you trust. macOS may ask to allow incoming connections for Python.

### Call demo script

| # | Caller does | Receiver sees |
|---|---|---|
| 1 | Joins as *Rajesh Mehta (CEO)* and talks normally (the real volunteer, enrolled) | "No warning signs so far", green |
| 2 | Sends **Cloned CEO · ₹25 lakh transfer** | Speaker check fooled, transcript lights up, tracker hits *Ask* → **critical: hold the transaction** |
| 3 | Rejoins as *Unknown number*, sends **"digital arrest" scam script** | Tracker climbs **before** the money request: *heading into scam territory* → *scam script in progress* → *scam request made* |
| 4 | Receiver presses **Challenge the caller**; caller answers with the pre-recorded reply | Phrase pops up on the caller's screen → "too slow" + "✗ phrase not repeated" |

## Lab (single stream)

`/?lab` is the original one-person dashboard: play clips or use the mic into a monitored "call", enroll voices, and test without a second person.

## Quick start

Needs Python 3.11 (`uv`), Node 20+ and about 3 GB of disk for models. Built and tested on an Apple-silicon Mac (16 GB). It also runs on Windows or Linux on CPU, just slower.

Step-by-step instructions for Mac, Linux and Windows, plus troubleshooting: **[HOW_TO_RUN.txt](HOW_TO_RUN.txt)**. Python dependencies: **[requirements.txt](requirements.txt)**.

```bash
# one-time setup
cd vshield/backend && python3.11 -m venv .venv && .venv/bin/pip install -r ../requirements.txt
.venv/bin/python scripts/setup_demo.py      # downloads the test voice, enrolls the demo "CEO" (+ ~2 GB of models)
cd ../frontend && npm install && npm run build

# run
cd .. && ./run.sh            # → http://127.0.0.1:8000
```

The demo "CEO" is a public-domain LibriSpeech speaker (`hf-internal-testing/librispeech_asr_dummy`), standing in until you enroll your own volunteer with **Enroll a voice**.

**Before every demo** (with the server running): `.venv/bin/python scripts/check_scenes.py` plays all scenes through the live server and should print `8/8 scenes as expected`. Unit tests: `.venv/bin/python -m pytest tests -q`.

## Lab demo script (deck: "Genuine CEO vs. cloned CEO vs. clone + fraud request")

Use headphones: the laptop speakers must not feed clips back into the mic.

| # | Do this | What judges see |
|---|---|---|
| 0 | **Enroll a voice** → the volunteer "CEO" reads anything for 15 s | "Enrolled from N speech windows". No audio is stored. |
| 1 | Start call (caller: CEO's registered number, verify against: CEO) → volunteer speaks normally on the mic | Stays **green** (R ≈ 5–15) |
| 2 | Play the CEO's **clone** asking something routine | **S says "that's the CEO"** (cosine ≈ 0.6–0.7): the clone fools the speaker check. A rises → **medium**. Say it on stage: this is why one detector never decides alone. Then **issue a challenge** (scene 5). |
| 3 | Play the clone asking for **₹25 lakh, don't call back** (English or Hindi) | Risky words light up in the transcript → **CRITICAL: hold the transaction** |
| 4 | Volunteer (real voice) makes the same request | Context is high, the voice is clean → **medium: verify on another channel**. No hard block. |
| 5 | On a clone call, press **Issue challenge**. A teammate types the phrase into the cloning tool and plays the result. | "Answered after 4 s: too slow" and/or "✗ phrase not repeated" → escalates |

Turn **Wi-Fi off** before the demo. Everything runs on-device, which proves the deck's "edge inference" claim.

## How it works

| Signal | Model / method | What it catches | Time per 3 s window* |
|---|---|---|---|
| **A** authenticity | `Gustking/wav2vec2-large-xlsr-deepfake-audio-classification`, probability averaged over recent speech, threshold raised if the enrolled voice naturally scores high | synthesis artefacts | 81 ms (Apple GPU) |
| **S** speaker | SpeechBrain ECAPA-TDNN, cosine to enrolled voiceprint | a different human, cheap clones | 24 ms |
| **B** behaviour | Praat pitch / jitter / shimmer / HNR z-scores vs. enrollment, plus challenge response latency | unnatural delivery, slow typed-in replies | 15 ms |
| **C** context | faster-whisper `base` in **translate** mode (Hindi → English) + rules for amount, transfer, urgency, secrecy, call-back avoidance, credentials, new beneficiary, gift cards/crypto, threats ("digital arrest", CBI, account blocked), remote-access apps (AnyDesk), prize/refund lures, KYC, "don't hang up", plus the CRM caller record | the *request*, even if the voice sounds perfect | ~1 s per sentence, async |

\* Measured on an M-series MacBook. The full update takes **~160 ms median, ~230 ms p95 while Whisper runs**, against the deck's "<0.5 s" claim.

**Scam-script tracker:** the context flags map to the four stages of a phone scam: *hook* (claims authority, KYC, prize), *pressure* (urgency, threats), *isolation* (secrecy, don't call back / hang up), *ask* (money, OTP, new account, AnyDesk). Two stages before any ask → medium ("heading into scam territory"); three → high ("challenge them before they ask").

Escalation rules (each is shown on screen when it fires):
- risky request + any anomalous voice signal → **≥ 85 critical**
- risky request alone → **≥ 40 medium** (verify, don't block)
- strong synthetic evidence, synthetic + speaker mismatch, a slow challenge answer, or a wrong challenge phrase → **≥ 65–80**

Privacy: `data/logs/*.jsonl` holds scores, bands and flag *names* only. Transcripts stay in memory for the dashboard. Enrollment stores a 192-number voiceprint plus feature statistics, never audio.

### Code map
```
backend/vshield/
  server.py        REST (/api/enroll, /api/config, /api/demo) + WebSockets /ws/call (analysis) and /ws/room (calls)
  rooms.py         two-person call rooms: WebRTC signaling relay + challenge-prompt push
  session.py       one call: ring buffer, speech gating, 0.5 s hops (skip, never queue), ASR lane, challenges
  engine.py        loads models once, builds enrollments
  fusion.py        weights, rules, bands, actions
  policy.py        random challenge phrases + fuzzy phrase matching
  signals/         authenticity · speaker · behaviour · context (+ hf_detector wrapper)
  config.py        every tunable, overridable by env var
backend/scripts/   enroll · stream_call (CLI caller) · check_scenes · eval_detector · make_clone · fit_fusion
backend/tests/     fast unit tests (rules, fusion, challenge matching, buffer)
frontend/src/      React: Home · call/ (CallPage, useRoom = WebRTC) · App (lab) · components/ (gauge, signals,
                   scam tracker, transcript, challenge, timeline) · audio.ts (analysis engine + outgoing mixer)
```

## Measured results

**Detector choice** (`scripts/eval_detector.py`; 3 s windows; 30 real LibriSpeech clips vs. 30 macOS-TTS clips):

| model | genuine flagged (clean / phone) | fakes caught (clean / phone) | ms/window |
|---|---|---|---|
| MelodyMachine/Deepfake-audio-detection-V2 | worse than chance (AUC 0.15) | | 65 |
| MattyB95/AST-ASVspoof5 | calls everything fake | | 528 |
| mo-thecreator/Deepfake-audio-detection | 19% / 0% | 100% / **17%** | 73 |
| **Gustking wav2vec2-XLS-R (used)** | 27% / 16% | 100% / **98%** | 207 CPU · 81 GPU |

"Phone" = resampled to 8 kHz + G.711 μ-law + noise (`vshield/audio.py: phone_channel`).

**End-to-end scenes** (`scripts/check_scenes.py`, real-time streaming through the live server, CEO enrolled):

| scene | peak R | band | update p95 |
|---|---|---|---|
| 1 genuine CEO, routine | 6.5 | low | 224 ms |
| 2 synthetic voice, routine request | 65 | high | 228 ms |
| 3 synthetic voice, ₹25 lakh (English) | 85 | critical | 224 ms |
| 3h synthetic voice, ₹25 lakh (Hindi speech) | 85 | critical | 236 ms |
| 5 genuine voice answers a challenge | answered in 1.4 s (fast) | | 230 ms |
| 6 attacker: slow, pre-recorded reply | 70 | high: 4.0 s, "✗ phrase not repeated" | 210 ms |

**Real voice clones** (F5-TTS clones of the enrolled CEO voice, `scripts/make_clone.py`), the most realistic attack tested:

| clone says | speaker check | detector A | peak R |
|---|---|---|---|
| routine request #1 | **fooled** (cosine 0.53–0.68) | 0.44 | 23 · low ❌ |
| routine request #2 | **fooled** (cosine 0.58–0.68) | 0.78 | 37 · medium |
| "₹25 lakh, new vendor, don't call back" | fooled (cosine 0.52–0.71) | 0.78 | **85 · critical** ✅ |

The speaker check can't stop a good clone, and the detector only half-separates this speaker's real voice (P(fake) ≈ 0.67) from its clone (≈ 0.8). A fraud request from a clone is caught; **a clone making small talk can pass.** The challenge-response is the defence for that case today. Fine-tuning the detector on your volunteer's clones is the fix.

## Known limitations (be ready for these questions)

1. **A good clone making a routine request can score low/medium** (see the clone table above). The fix is the #1 ML task: record your volunteers (genuine) and their F5-TTS clones, add phone-channel augmentation (`vshield/audio.py`), and fine-tune the XLS-R detector on them.
2. **The detector false-alarms on some genuine voices.** One set of the test speaker's clips pushed A to 0.6 and R to **34 (medium)**. Fusion kept it out of "high". The same fine-tuning fixes both 1 and 2. Then re-fit fusion weights with `scripts/fit_fusion.py`.
3. **Whisper translation can drop words.** Long segments lost the "₹25 lakh" clause in testing. Utterances are cut at 0.4 s pauses / 6 s max to prevent this. A proper Indic ASR + intent model is the real fix.
4. **B and the fusion weights are hand-set priors.** Record labelled calls (genuine/clone × routine/fraud) and fit them.
5. **The call demo is browser-to-browser (WebRTC), not the phone network.** Rooms live in server memory (a restart drops calls) and there's no login.
6. **Not integrated with real telephony yet.** Android doesn't let third-party apps read call audio, so the production path is server-side: bank IVR, call-centre SIP, VoIP. Twilio Media Streams is the quickest real-phone stretch goal.

## Slide claims vs. this prototype

| Deck says | Status |
|---|---|
| 4 signals fused live, explainable score 0–100 | ✅ built, contributions shown per signal |
| 3-second windows, **<0.5 s** risk update | ✅ measured ~230 ms p95 under load |
| Context catches "₹25 lakh, don't call back" | ✅ English, Hinglish, Devanagari, Hindi speech |
| Challenge phrase / MFA instead of hard block | ✅ challenge with latency + phrase check; MFA/call-back is an on-screen recommendation |
| Feature-only logs, no raw audio | ✅ |
| Edge inference | ✅ runs offline after the first model download |
| **"Cheap artefact filter first, heavy models only on flagged windows"** | ⚠️ **Not built on purpose.** The cheap model misses 83% of phone-line fakes, so skipping the heavy model on "looks real" windows would let clones through. Reword to "heavy detector on every speech window, <0.5 s" or train a reliable cheap model first. |
| **">95% spoof accuracy on ASVspoof"** | ⚠️ Not measured here. Cite the paper's number as a *published benchmark*, or run `eval_detector.py` on ASVspoof 2019 LA. |
| Indic-language models | ⚠️ Partial: Hindi works through Whisper translation. No Indic fine-tuning yet. |
| VoIP · mobile · Teams | ⚠️ Browser/VoIP only in the prototype |
| REST / gRPC SDK, SIEM webhooks | ⚠️ REST + WebSocket exist; gRPC/SIEM not built |
