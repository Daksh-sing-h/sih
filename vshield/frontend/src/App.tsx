import { useCallback, useEffect, useState } from "react";
import { Brand } from "./components/Brand";
import { CallControls } from "./components/CallControls";
import { ChallengePanel } from "./components/ChallengePanel";
import { EnrollDialog } from "./components/EnrollDialog";
import { Gauge } from "./components/Gauge";
import { SignalPanel } from "./components/SignalPanel";
import { Timeline } from "./components/Timeline";
import { Transcript } from "./components/Transcript";
import { hasEvidence, type AppConfig } from "./types";
import { useCall } from "./useCall";

interface Health {
  ready: boolean;
  models: Record<string, string>;
}

const STATUS_LABEL = {
  idle: "No call",
  connecting: "Connecting…",
  live: "Live call",
  ending: "Finishing…",
  ended: "Call ended",
  error: "Error",
} as const;

export default function App() {
  const { state, start, stop, challenge, engine } = useCall();
  const [health, setHealth] = useState<Health | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [enrolling, setEnrolling] = useState(false);

  const loadConfig = useCallback(() => {
    fetch("/api/config").then((r) => (r.ok ? r.json() : null)).then((c) => c && setConfig(c)).catch(() => {});
  }, []);

  useEffect(() => {
    let stop = false;
    const poll = async () => {
      try {
        const h: Health = await fetch("/api/health").then((r) => r.json());
        if (stop) return;
        setHealth(h);
        if (h.ready) return loadConfig();
      } catch {
        setHealth(null);
      }
      if (!stop) setTimeout(poll, 1500);
    };
    void poll();
    return () => {
      stop = true;
    };
  }, [loadConfig]);

  const latest = hasEvidence(state.latest) ? state.latest : null;
  const live = state.status === "live";
  const band = latest?.band ?? null;
  const lastChallenge = state.challenges.at(-1);

  return (
    <div className={`app band-bg-${band ?? "none"}`}>
      <header>
        <Brand sub="Lab · test V-Shield with the mic or recorded clips" />
        <div className="header-right">
          {state.enrolled && <span className="pill">Verifying: {state.enrolled}</span>}
          {state.caller && <span className="pill">Caller: {state.caller}</span>}
          <span className={`pill status ${state.status}`}>
            {live && <span className="live-dot" />}
            {STATUS_LABEL[state.status]}
            {(live || state.status === "ending") && ` · ${state.streamT.toFixed(0)}s`}
          </span>
          <span className={`pill ${health?.ready ? "ok" : "warn"}`} title={health ? Object.values(health.models).join(" · ") : ""}>
            {health?.ready ? "Models ready · on-device" : health ? "Loading models…" : "Server offline"}
          </span>
        </div>
      </header>

      {state.error && <div className="banner error">{state.error}</div>}

      <main>
        <aside>
          <CallControls config={config} status={state.status} level={state.level} engine={engine}
                        onStart={start} onStop={stop} onEnroll={() => setEnrolling(true)} />
        </aside>

        <section className="center">
          <div className="card risk-card">
            <Gauge value={latest?.R ?? null} band={band} live={live} />
            <div className={`action band-${band ?? "none"}`}>
              <span className="action-label">Recommended action</span>
              <strong>{latest?.action ?? (live ? "Listening for speech…" : "Start a call to begin monitoring")}</strong>
            </div>
          </div>
          <div className="card">
            <div className="card-head">
              <h3>Risk signals</h3>
              <span className="muted small">R = 0.40·A + 0.20·S + 0.15·B + 0.25·C, plus escalation rules</span>
            </div>
            <SignalPanel latest={latest} />
          </div>
        </section>

        <section className="right">
          <div className="card">
            <ChallengePanel challenge={lastChallenge} now={state.streamT} live={live}
                            suggested={band === "high" || band === "critical"} onIssue={challenge} />
          </div>
          <div className="card transcript-card">
            <div className="card-head">
              <h3>Live transcript</h3>
              <span className="muted small">risky phrases highlighted</span>
            </div>
            <Transcript items={state.transcripts} live={live} />
          </div>
        </section>
      </main>

      <footer className="card">
        <div className="card-head">
          <h3>Risk over the call</h3>
          <div className="stats">
            <span title="Time to score the latest 3-second window">
              update <strong>{latest?.proc_ms != null ? `${latest.proc_ms.toFixed(0)} ms` : "–"}</strong>
            </span>
            <span>p95 <strong>{latest?.proc_ms_p95 != null ? `${latest.proc_ms_p95.toFixed(0)} ms` : "–"}</strong></span>
            <span title="Windows dropped to stay real-time">skipped <strong>{latest?.skipped ?? 0}</strong></span>
            <span className="muted">logs: scores &amp; flags only, no audio, no text</span>
          </div>
        </div>
        <Timeline scores={state.scores} transcripts={state.transcripts} challenges={state.challenges} now={state.streamT} />
      </footer>

      {enrolling && <EnrollDialog onClose={() => setEnrolling(false)} onEnrolled={loadConfig} />}
    </div>
  );
}
