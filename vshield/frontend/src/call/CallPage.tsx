import { useEffect, useRef, useState } from "react";
import { encodeWav } from "../audio";
import { Brand } from "../components/Brand";
import { ChallengePanel } from "../components/ChallengePanel";
import { Gauge } from "../components/Gauge";
import { ScamStages } from "../components/ScamStages";
import { SignalPanel } from "../components/SignalPanel";
import { Timeline } from "../components/Timeline";
import { Transcript } from "../components/Transcript";
import { hasEvidence, type AppConfig, type DemoClip } from "../types";
import { useCall } from "../useCall";
import { useRoom } from "./useRoom";

const UNKNOWN = "+91-77777-12345";
const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-|-$/g, "") || "caller";
const fmtTime = (ms: number) => {
  const s = Math.floor(ms / 1000);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
};

type CrmCaller = AppConfig["callers"][number] & { enrollment?: string };

export function CallPage({ roomId }: { roomId: string }) {
  const room = useRoom(roomId);
  const shield = useCall();
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [clips, setClips] = useState<DemoClip[]>([]);
  const [name, setName] = useState(() => localStorage.getItem("vshield-name") ?? "");
  const [callerId, setCallerId] = useState("");
  const [muted, setMuted] = useState(false);
  const [playing, setPlaying] = useState<string | null>(null);
  const [outLevel, setOutLevel] = useState(0);
  const [now, setNow] = useState(Date.now());
  const [enroll, setEnroll] = useState<{ busy: boolean; msg: string | null }>({ busy: false, msg: null });
  const [copied, setCopied] = useState(false);
  const audioEl = useRef<HTMLAudioElement>(null);
  const shieldFor = useRef<string | null>(null);

  const { status, peer, remoteStream, prompt, me } = room.state;
  const inCall = !["idle", "joining", "left", "error"].includes(status);
  const shareUrl = `${location.origin}/?room=${roomId}`;
  const crm = (config?.callers ?? []) as CrmCaller[];
  const peerCrm = crm.find((c) => c.id === peer?.caller_id);

  useEffect(() => {
    fetch("/api/config").then((r) => (r.ok ? r.json() : null)).then((c) => c && setConfig(c)).catch(() => {});
    fetch("/api/demo").then((r) => r.json()).then((d) => setClips(d.clips ?? [])).catch(() => {});
  }, []);

  // play the other person's voice (Chrome also needs this for Web Audio to receive a remote stream)
  useEffect(() => {
    const el = audioEl.current;
    if (!el) return;
    el.srcObject = remoteStream;
    if (remoteStream) void el.play().catch(() => {});
  }, [remoteStream, status]);

  // start V-Shield on the other person's audio; stop when they leave
  const { start: startShield, stop: stopShield } = shield;
  const peerId = peer?.id;
  const peerCaller = peer?.caller_id ?? "";
  useEffect(() => {
    if (remoteStream && peerId && shieldFor.current !== peerId) {
      shieldFor.current = peerId;
      void startShield(peerCaller, "", { stream: remoteStream, room: roomId, target: peerId });
    }
    if (!remoteStream && shieldFor.current) {
      shieldFor.current = null;
      stopShield();
    }
  }, [remoteStream, peerId, peerCaller, roomId, startShield, stopShield]);

  // outgoing level meter + call timer
  useEffect(() => {
    if (!inCall) return;
    const id = window.setInterval(() => {
      setOutLevel(room.out.current?.level() ?? 0);
      setNow(Date.now());
    }, 100);
    return () => window.clearInterval(id);
  }, [inCall, room.out]);

  // the challenge prompt on *this* screen disappears after a while
  useEffect(() => {
    if (!prompt) return;
    const id = window.setTimeout(room.dismissPrompt, 20000);
    return () => window.clearTimeout(id);
  }, [prompt, room.dismissPrompt]);

  const join = () => {
    localStorage.setItem("vshield-name", name);
    void room.join(name || "Guest", callerId);
  };

  const hangUp = async () => {
    shieldFor.current = null;
    shield.stop();
    await room.leave();
  };

  const sendClip = async (label: string, data: Promise<ArrayBuffer>) => {
    const o = room.out.current;
    if (!o) return;
    setPlaying(label);
    try {
      await o.playClip(await data, () => setPlaying((p) => (p === label ? null : p)));
    } catch {
      setPlaying(null);
    }
  };

  const enrollCaller = async () => {
    if (!peer) return;
    setEnroll({ busy: true, msg: "Listening to the caller for 15 s… ask them to keep talking." });
    const chunks = await shield.record(15);
    const displayName = peerCrm?.name ?? peer.name;
    const q = new URLSearchParams({ name: displayName, id: peerCrm?.enrollment ?? slug(peer.name) });
    const r = await fetch(`/api/enroll?${q}`, { method: "POST", body: encodeWav(chunks) });
    const d = await r.json();
    setEnroll({
      busy: false,
      msg: r.ok
        ? `Enrolled ${displayName}'s voice from this call (${d.windows} windows). It's used from the next call.`
        : d.detail ?? "Enrollment failed",
    });
  };

  // ---------------------------------------------------------------- before joining
  if (!inCall) {
    return (
      <div className="app call-app">
        <header><Brand sub={`Protected call · room ${roomId}`} /></header>
        <div className="join-card card">
          <h2>{status === "left" ? "You left the call" : "Join the call"}</h2>
          {room.state.error && <p className="error">{room.state.error}</p>}
          <label>
            Your name
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Anjali (Accounts)" />
          </label>
          <label>
            Caller ID the other person sees
            <select value={callerId} onChange={(e) => setCallerId(e.target.value)}>
              <option value="">None (just my name)</option>
              {crm.map((c) => (
                <option key={c.id} value={c.id}>{c.name} · {c.id}</option>
              ))}
              <option value={UNKNOWN}>Unknown number · {UNKNOWN}</option>
            </select>
          </label>
          <p className="muted small">
            Playing the caller (or the scammer)? Pick the caller ID to show. Caller IDs are easy to spoof, which is
            why V-Shield checks the voice against the identity it claims.
          </p>
          <div className="row">
            <button className="btn primary" onClick={join} disabled={status === "joining"}>
              {status === "joining" ? "Joining…" : status === "left" ? "Rejoin call" : "Join call"}
            </button>
            <a className="btn ghost" href="/">Home</a>
          </div>
          <p className="muted small">Use headphones if both people are in the same room.</p>
        </div>
      </div>
    );
  }

  // ---------------------------------------------------------------- in the call
  // before the other person has said anything, show "listening", not a verdict
  const latest = hasEvidence(shield.state.latest) ? shield.state.latest : null;
  const band = latest?.band ?? null;
  const stages = latest?.details.C?.stages ?? [];
  const lastChallenge = shield.state.challenges.at(-1);
  const peerLabel = peer ? peerCrm?.name ?? (peer.caller_id === UNKNOWN ? `Unknown · ${UNKNOWN}` : peer.name) : null;

  return (
    <div className={`app call-app band-bg-${band ?? "none"}`}>
      <audio ref={audioEl} autoPlay />
      <header>
        <Brand sub={`Protected call · room ${roomId}`} />
        <div className="header-right">
          <span className={`pill status ${status === "connected" ? "live" : ""}`}>
            {status === "connected" && <span className="live-dot" />}
            {status === "connected" ? `On call · ${fmtTime(now - (room.state.connectedAt ?? now))}`
              : status === "waiting" ? "Waiting for the other person" : "Connecting…"}
          </span>
          {me && <span className="pill">You: {me.name}</span>}
        </div>
      </header>

      <main className="call-main">
        <aside className="controls">
          <section className="card peer-card">
            <h3>Other person</h3>
            {peer ? (
              <>
                <div className="peer">
                  <div className="avatar">{(peerLabel ?? "?").slice(0, 1).toUpperCase()}</div>
                  <div>
                    <div className="peer-name">{peerLabel}</div>
                    <div className="muted small">
                      {peer.caller_id ? `Caller ID shown: ${peer.caller_id}` : "No caller ID"} · says they're “{peer.name}”
                    </div>
                  </div>
                </div>
                {peerCrm?.enrollment ? (
                  <p className="small muted">Voice checked against the enrolled voiceprint for {peerCrm.name}.</p>
                ) : (
                  <p className="small muted">No enrolled voiceprint for this caller ID, so there's no speaker check.</p>
                )}
              </>
            ) : (
              <div className="waiting">
                <p>Send this link to the other person:</p>
                <div className="share">
                  <code>{shareUrl}</code>
                  <button className="btn small" onClick={() => {
                    void navigator.clipboard?.writeText(shareUrl).then(() => setCopied(true));
                  }}>{copied ? "Copied" : "Copy"}</button>
                </div>
                <p className="muted small">Room code <strong>{roomId}</strong></p>
              </div>
            )}
          </section>

          <section className="card">
            <h3>Your audio</h3>
            <div className="row mic-row">
              <button className={`btn ${muted ? "rec" : ""}`} disabled={!room.out.current?.hasMic}
                      onClick={() => { room.out.current?.setMuted(!muted); setMuted(!muted); }}>
                {muted ? "Unmute" : "Mute"}
              </button>
              <div className="meter" aria-label="Your outgoing level">
                <div style={{ width: `${Math.min(100, Math.sqrt(outLevel) * 220)}%` }} />
              </div>
              <button className="btn danger" onClick={hangUp}>Hang up</button>
            </div>
            {room.state.micError && (
              <p className="error small">No microphone ({room.state.micError}). You can still send clips below.</p>
            )}
          </section>

          <section className="card">
            <h3>Send audio into the call</h3>
            <p className="muted small">
              For the demo: play a cloned voice instead of speaking, the way an attacker feeds a clone into a real call.
            </p>
            <div className="clips">
              {clips.map((c) => (
                <button key={c.file} className={`clip ${c.kind} ${playing === c.label ? "playing" : ""}`}
                        disabled={!peer} aria-label={`Send into call: ${c.label}`} title={c.note}
                        onClick={() => sendClip(c.label, fetch(`/demo/${c.file}`).then((r) => r.arrayBuffer()))}>
                  <span className="clip-kind">{c.kind}</span>
                  <span>{playing === c.label ? "▶ " : ""}{c.label}</span>
                </button>
              ))}
              <label className={`clip upload ${peer ? "" : "disabled"}`}>
                <span className="clip-kind">file</span>
                <span>Send your own clip…</span>
                <input type="file" accept="audio/*" disabled={!peer} onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void sendClip(f.name, f.arrayBuffer());
                  e.target.value = "";
                }} />
              </label>
            </div>
            {playing && (
              <button className="btn ghost small" onClick={() => { room.out.current?.stopClip(); setPlaying(null); }}>
                Stop sending clip
              </button>
            )}
          </section>
        </aside>

        <section className="center">
          <div className="shield-title">
            <h2>V-Shield is checking {peer ? peerLabel : "the other person"}</h2>
            <span className="muted small">It analyses what you hear from them. Nothing is recorded.</span>
          </div>
          <div className="card risk-card">
            <Gauge value={latest?.R ?? null} band={band} live={!!peer} />
            <div className={`action band-${band ?? "none"}`}>
              <span className="action-label">What to do</span>
              <strong>{latest?.action ?? (peer ? "Listening to the other person…" : "Waiting for the other person to join")}</strong>
            </div>
          </div>
          <div className="card">
            <ScamStages reached={stages} />
          </div>
          <div className="card">
            <div className="card-head">
              <h3>Risk signals</h3>
              <span className="muted small">about the other person's voice and words</span>
            </div>
            <SignalPanel latest={latest} />
          </div>
        </section>

        <section className="right">
          <div className="card">
            <ChallengePanel challenge={lastChallenge} now={shield.state.streamT} live={shield.state.status === "live"}
                            suggested={band === "high" || band === "critical"} onIssue={shield.challenge} pushed />
          </div>
          <div className="card transcript-card">
            <div className="card-head">
              <h3>What they said</h3>
              <span className="muted small">risky phrases highlighted</span>
            </div>
            <Transcript items={shield.state.transcripts} live={!!peer} />
          </div>
          {peer && (
            <div className="card">
              <h3>Trust this caller?</h3>
              <p className="muted small">
                On a call you've verified another way, enroll {peerCrm?.name ?? peer.name}'s voice from the call audio itself,
                so future calls are checked on the same channel.
              </p>
              <button className="btn ghost" onClick={enrollCaller} disabled={enroll.busy || shield.state.status !== "live"}>
                {enroll.busy ? "Recording 15 s…" : "Enroll this caller's voice"}
              </button>
              {enroll.msg && <p className="small muted">{enroll.msg}</p>}
            </div>
          )}
        </section>
      </main>

      <footer className="card">
        <div className="card-head">
          <h3>Risk over the call</h3>
          <div className="stats">
            <span>update <strong>{latest?.proc_ms != null ? `${latest.proc_ms.toFixed(0)} ms` : "–"}</strong></span>
            <span>p95 <strong>{latest?.proc_ms_p95 != null ? `${latest.proc_ms_p95.toFixed(0)} ms` : "–"}</strong></span>
            <span className="muted">logs: scores &amp; flags only</span>
          </div>
        </div>
        <Timeline scores={shield.state.scores} transcripts={shield.state.transcripts}
                  challenges={shield.state.challenges} now={shield.state.streamT} />
      </footer>

      {prompt && (
        <div className="modal-backdrop">
          <div className="modal prompt-modal" role="alertdialog" aria-label="Voice verification">
            <span className="action-label">V-Shield verification</span>
            <h2>Please read this aloud now</h2>
            <div className="phrase big">“{prompt.phrase}”</div>
            <p className="muted small">The other person asked V-Shield to check that they're talking to a live person.</p>
            <div className="row end">
              <button className="btn primary" onClick={room.dismissPrompt}>Done</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
