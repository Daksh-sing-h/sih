import type { ChallengeState } from "../useCall";

export function ChallengePanel({
  challenge,
  now,
  live,
  suggested,
  onIssue,
  pushed = false,
}: {
  challenge: ChallengeState | undefined;
  now: number;
  live: boolean;
  suggested: boolean;
  onIssue: () => void;
  /** two-person call: the phrase is pushed to the other person's screen */
  pushed?: boolean;
}) {
  const waiting = challenge && !challenge.result;
  const elapsed = challenge ? Math.max(0, now - challenge.issued_at) : 0;
  return (
    <div className={`challenge ${suggested && !challenge ? "suggested" : ""}`}>
      <div className="challenge-row">
        <div>
          <h3>{pushed ? "Challenge the caller" : "Challenge-response"}</h3>
          <p className="muted">
            {pushed
              ? "V-Shield shows them a random phrase to read aloud. A live person does it in about a second; a cloning tool has to type and synthesise it."
              : "A live person repeats a random phrase in about a second. A cloning tool needs time to type and synthesise it."}
          </p>
        </div>
        <button className="btn primary" onClick={onIssue} disabled={!live || !!waiting}>
          {challenge ? "New challenge" : "Issue challenge"}
        </button>
      </div>
      {challenge && (
        <div className="challenge-body">
          <span className="muted">{pushed ? "Shown on the caller's screen:" : "Ask the caller to repeat:"}</span>
          <div className="phrase">“{challenge.phrase}”</div>
          {waiting && <div className="timer">waiting for reply… {elapsed.toFixed(1)} s</div>}
          {challenge.result && (
            <div className={`verdict ${challenge.result.slow ? "bad" : "good"}`}>
              Answered after <strong>{challenge.result.latency_s.toFixed(1)} s</strong>
              {challenge.result.slow ? ": too slow for a live person" : ": consistent with a live person"}
            </div>
          )}
          {challenge.result && !challenge.verdict && <div className="muted small">checking what was said…</div>}
          {challenge.verdict && (
            <div className={`verdict ${challenge.verdict.matched ? "good" : "bad"}`}>
              {challenge.verdict.matched ? "✓ Phrase repeated" : "✗ Phrase not repeated"}
              <span className="muted small"> · heard “{challenge.verdict.heard}”</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
