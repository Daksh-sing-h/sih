import { useState } from "react";
import { Brand } from "./components/Brand";

const ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"; // no 0/O or 1/I confusion

function newRoomCode() {
  const bytes = crypto.getRandomValues(new Uint8Array(6));
  return Array.from(bytes, (b) => ALPHABET[b % ALPHABET.length]).join("");
}

export function Home() {
  const [code, setCode] = useState("");
  const go = (room: string) => (location.href = `/?room=${encodeURIComponent(room.trim().toUpperCase())}`);

  return (
    <div className="app home">
      <header><Brand /></header>
      <section className="hero">
        <h2>Talk normally. V-Shield listens for the scam.</h2>
        <p className="muted">
          Two people join a voice call. On your side, V-Shield checks the other person's voice for cloning, compares it
          with the identity their caller ID claims, and watches the conversation for the scam script (hook → pressure →
          isolation → ask), warning you before the money request, not after.
        </p>
      </section>
      <div className="home-grid">
        <div className="card">
          <h3>Start a protected call</h3>
          <p className="muted small">You get a link to send to the other person.</p>
          <button className="btn primary" onClick={() => go(newRoomCode())}>Start a call</button>
        </div>
        <div className="card">
          <h3>Join a call</h3>
          <form className="row" onSubmit={(e) => { e.preventDefault(); if (code.trim()) go(code); }}>
            <input value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} placeholder="Room code"
                   maxLength={12} aria-label="Room code" />
            <button className="btn" type="submit" disabled={!code.trim()}>Join</button>
          </form>
        </div>
        <div className="card">
          <h3>Lab</h3>
          <p className="muted small">Test V-Shield alone with the mic or recorded clips, and enroll voices.</p>
          <a className="btn ghost" href="/?lab">Open the lab</a>
        </div>
      </div>
      <ol className="how">
        <li><strong>Voice authenticity</strong> spots synthetic-speech artefacts from voice-cloning tools.</li>
        <li><strong>Speaker check</strong> compares the voice with the enrolled voiceprint for the caller ID they show.</li>
        <li><strong>Behaviour</strong> tracks pitch and voice quality, and how fast they repeat a random challenge phrase.</li>
        <li><strong>Context</strong> reads the conversation (English, Hinglish, Hindi) for the scam script and money requests.</li>
      </ol>
    </div>
  );
}
