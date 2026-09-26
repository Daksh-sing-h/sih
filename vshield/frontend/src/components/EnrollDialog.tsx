import { useEffect, useRef, useState } from "react";
import { AudioEngine, encodeWav } from "../audio";

const RECORD_S = 15;

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-|-$/g, "");

export function EnrollDialog({ onClose, onEnrolled }: { onClose: () => void; onEnrolled: () => void }) {
  const [name, setName] = useState("");
  const [id, setId] = useState("");
  const [phase, setPhase] = useState<"idle" | "recording" | "uploading" | "done">("idle");
  const [left, setLeft] = useState(RECORD_S);
  const [level, setLevel] = useState(0);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const engine = useRef<AudioEngine | null>(null);
  const chunks = useRef<ArrayBuffer[]>([]);
  const timer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timer.current) window.clearInterval(timer.current);
      void engine.current?.close();
    },
    [],
  );

  const upload = async (body: Blob) => {
    setPhase("uploading");
    setError(null);
    const q = new URLSearchParams({ name: name.trim(), id: id || slug(name) });
    const r = await fetch(`/api/enroll?${q}`, { method: "POST", body });
    const data = await r.json();
    if (!r.ok) {
      setPhase("idle");
      setError(data.detail ?? "Enrollment failed");
      return;
    }
    setPhase("done");
    setMsg(`Enrolled “${data.name}” from ${data.windows} speech windows.`);
    onEnrolled();
  };

  const record = async () => {
    setError(null);
    chunks.current = [];
    try {
      const eng = await AudioEngine.create((pcm, rms) => {
        chunks.current.push(pcm);
        setLevel(rms);
      });
      engine.current = eng;
      await eng.startMic();
    } catch (e) {
      setError(`Microphone unavailable: ${(e as Error).message}`);
      return;
    }
    setPhase("recording");
    setLeft(RECORD_S);
    const started = performance.now();
    timer.current = window.setInterval(async () => {
      const remaining = RECORD_S - (performance.now() - started) / 1000;
      setLeft(Math.max(0, remaining));
      if (remaining <= 0) {
        window.clearInterval(timer.current!);
        timer.current = null;
        await engine.current?.close();
        engine.current = null;
        await upload(encodeWav(chunks.current));
      }
    }, 100);
  };

  const fromFile = async (files: FileList | null) => {
    if (!files?.length) return;
    // server accepts one WAV/FLAC/OGG; send the first file as-is
    await upload(files[0]);
  };

  const ready = name.trim().length > 0 && phase === "idle";

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Enroll a genuine voice">
        <h2>Enroll a genuine voice</h2>
        <p className="muted">
          Records a voiceprint (192 numbers) plus how this voice normally scores on the detector and pitch features.
          No audio is stored. Get the speaker's consent first.
        </p>
        <label>
          Display name
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Rajesh Mehta (CEO)" disabled={phase !== "idle"} />
        </label>
        <label>
          ID <span className="muted small">(used in API calls)</span>
          <input value={id || slug(name)} onChange={(e) => setId(slug(e.target.value))} placeholder="ceo" disabled={phase !== "idle"} />
        </label>

        {phase === "recording" ? (
          <div className="recording">
            <div className="rec-dot" /> Recording… speak naturally for {left.toFixed(0)} s more
            <div className="meter"><div style={{ width: `${Math.min(100, Math.sqrt(level) * 220)}%` }} /></div>
            <p className="muted small">Tip: read something aloud, e.g. the day's agenda, at your normal pace.</p>
          </div>
        ) : (
          <div className="row">
            <button className="btn primary" disabled={!ready} onClick={record}>Record {RECORD_S} s from mic</button>
            <label className={`btn ghost ${ready ? "" : "disabled"}`}>
              Upload a recording
              <input type="file" accept="audio/wav,audio/flac,audio/ogg" hidden disabled={!ready}
                     onChange={(e) => void fromFile(e.target.files)} />
            </label>
          </div>
        )}
        {phase === "uploading" && <p className="muted">Building voiceprint…</p>}
        {msg && <p className="success">{msg}</p>}
        {error && <p className="error">{error}</p>}
        <div className="row end">
          <button className="btn ghost" onClick={onClose}>{phase === "done" ? "Done" : "Cancel"}</button>
        </div>
      </div>
    </div>
  );
}
