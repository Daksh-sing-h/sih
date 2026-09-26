import { useEffect, useState, type RefObject } from "react";
import type { AudioEngine } from "../audio";
import type { AppConfig, DemoClip } from "../types";
import type { CallStatus } from "../useCall";

export const UNKNOWN_CALLER = "+91-77777-12345";

export function CallControls({
  config,
  status,
  level,
  engine,
  onStart,
  onStop,
  onEnroll,
}: {
  config: AppConfig | null;
  status: CallStatus;
  level: number;
  engine: RefObject<AudioEngine | null>;
  onStart: (callerId: string, enrollment: string) => void;
  onStop: () => void;
  onEnroll: () => void;
}) {
  const [caller, setCaller] = useState("+91-98100-00001");
  const [enrollment, setEnrollment] = useState("");
  const [clips, setClips] = useState<DemoClip[]>([]);
  const [mic, setMic] = useState(false);
  const [playing, setPlaying] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const live = status === "live";
  const busy = status === "connecting" || status === "ending";

  useEffect(() => {
    fetch("/api/demo").then((r) => r.json()).then((d) => setClips(d.clips ?? [])).catch(() => {});
  }, []);

  useEffect(() => {
    if (!enrollment && config?.enrollments.length) setEnrollment(config.enrollments[0].id);
  }, [config, enrollment]);

  useEffect(() => {
    if (!live) {
      setMic(false);
      setPlaying(null);
    }
  }, [live]);

  const toggleMic = async () => {
    const e = engine.current;
    if (!e) return;
    setErr(null);
    try {
      if (mic) e.stopMic();
      else await e.startMic();
      setMic(!mic);
    } catch (x) {
      setErr(`Microphone unavailable: ${(x as Error).message}`);
    }
  };

  const play = async (label: string, data: Promise<ArrayBuffer>) => {
    const e = engine.current;
    if (!e) return;
    setErr(null);
    try {
      setPlaying(label);
      await e.play(await data, () => setPlaying((p) => (p === label ? null : p)));
    } catch (x) {
      setPlaying(null);
      setErr(`Couldn't play clip: ${(x as Error).message}`);
    }
  };

  return (
    <div className="controls">
      <section className="card">
        <h3>Call setup</h3>
        <label>
          Incoming caller ID
          <select value={caller} onChange={(e) => setCaller(e.target.value)} disabled={live || busy}>
            {config?.callers.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} · {c.id}
              </option>
            ))}
            <option value={UNKNOWN_CALLER}>Unknown number · {UNKNOWN_CALLER}</option>
          </select>
        </label>
        <label>
          Genuine voice to verify against
          <select value={enrollment} onChange={(e) => setEnrollment(e.target.value)} disabled={live || busy}>
            <option value="">None (no voiceprint)</option>
            {config?.enrollments.map((e) => (
              <option key={e.id} value={e.id}>
                {e.name}
              </option>
            ))}
          </select>
        </label>
        <div className="row">
          {live || busy ? (
            <button className="btn danger" onClick={onStop} disabled={busy}>
              {status === "ending" ? "Ending…" : "End call"}
            </button>
          ) : (
            <button className="btn primary" onClick={() => onStart(caller, enrollment)}>
              Start call
            </button>
          )}
          <button className="btn ghost" onClick={onEnroll} disabled={live || busy}>
            Enroll a voice
          </button>
        </div>
      </section>

      <section className="card">
        <h3>Caller audio</h3>
        <div className="row mic-row">
          <button className={`btn ${mic ? "rec" : ""}`} onClick={toggleMic} disabled={!live}>
            {mic ? "● Mic live" : "Use microphone"}
          </button>
          <div className="meter" aria-label="Input level">
            <div style={{ width: `${Math.min(100, Math.sqrt(level) * 220)}%` }} />
          </div>
        </div>
        <p className="muted small">The mic mutes while a clip plays. Use headphones so the speakers don't feed back.</p>
        <div className="clips">
          {clips.map((c) => (
            <button key={c.file} className={`clip ${c.kind} ${playing === c.label ? "playing" : ""}`} disabled={!live}
                    onClick={() => play(c.label, fetch(`/demo/${c.file}`).then((r) => r.arrayBuffer()))}
                    aria-label={`Play into call: ${c.label}`} title={c.note}>
              <span className="clip-kind">{c.kind}</span>
              <span>{playing === c.label ? "▶ " : ""}{c.label}</span>
            </button>
          ))}
          <label className={`clip upload ${live ? "" : "disabled"}`}>
            <span className="clip-kind">file</span>
            <span>Play your own clip…</span>
            <input type="file" accept="audio/*" disabled={!live}
                   onChange={(e) => {
                     const f = e.target.files?.[0];
                     if (f) void play(f.name, f.arrayBuffer());
                     e.target.value = "";
                   }} />
          </label>
        </div>
        {playing && (
          <button className="btn ghost small" onClick={() => { engine.current?.stopClip(); setPlaying(null); }}>
            Stop clip
          </button>
        )}
        {err && <p className="error small">{err}</p>}
      </section>
    </div>
  );
}
