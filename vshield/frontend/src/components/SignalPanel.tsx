import type { ScoreMsg, SignalKey } from "../types";

const META: Record<SignalKey, { title: string; sub: string }> = {
  A: { title: "Voice authenticity", sub: "Synthesis artefacts · XLS-R detector" },
  S: { title: "Speaker identity", sub: "ECAPA voiceprint vs. enrolled voice" },
  B: { title: "Speech behaviour", sub: "Pitch, voice quality, challenge latency" },
  C: { title: "Call & request context", sub: "Transcript rules + caller record" },
};

const TERM_LABEL: Record<string, string> = {
  transfer: "money transfer",
  amount_high: "≥ ₹1 lakh",
  amount: "amount",
  urgency: "urgency",
  secrecy: "secrecy",
  callback_avoid: "avoid call-back",
  credential: "credential ask",
  new_beneficiary: "new beneficiary",
  unusual_payment: "gift card / crypto",
  authority_claim: "claims authority",
  pressure_combo: "pressure combo",
  unusual_for_caller: "unusual for caller",
  unknown_caller: "unknown number",
  threat: "threat / arrest",
  remote_access: "remote-access app",
  lure: "prize / refund",
  kyc: "KYC / Aadhaar",
  stay_on_line: "don't hang up",
};

function detail(key: SignalKey, m: ScoreMsg): React.ReactNode {
  const d = m.details;
  switch (key) {
    case "A":
      return d.A ? `avg P(fake) ${d.A.mean_p.toFixed(2)} vs threshold ${d.A.threshold.toFixed(2)}` : "waiting for speech";
    case "S":
      if (!m.enrolled) return "no voiceprint enrolled for this call";
      return d.S?.cos != null ? `cosine to ${m.enrolled}'s voiceprint ${d.S.cos.toFixed(2)}` : "waiting for speech";
    case "B": {
      const parts: string[] = [];
      if (d.B?.b_latency != null) parts.push(`challenge latency score ${d.B.b_latency.toFixed(2)}`);
      const z = d.B?.z ? Object.entries(d.B.z).sort((a, b) => b[1] - a[1])[0] : undefined;
      if (z) parts.push(`most unusual: ${z[0].replace(/_/g, " ")} (z ${z[1].toFixed(1)})`);
      if (parts.length) return parts.join(" · ");
      return m.enrolled ? "waiting for speech" : "no enrolled voice to compare with; a challenge still works";
    }
    case "C": {
      const terms = Object.keys(d.C?.terms ?? {});
      if (!terms.length) return d.C?.caller ? `caller: ${d.C.caller} · no risky request yet` : "no risky request yet";
      return (
        <span className="chips">
          {terms.map((t) => (
            <span key={t} className={`chip term-${t}`}>
              {TERM_LABEL[t] ?? t}
            </span>
          ))}
        </span>
      );
    }
  }
}

export function SignalPanel({ latest }: { latest: ScoreMsg | null }) {
  const keys: SignalKey[] = ["A", "S", "B", "C"];
  const uplift = latest?.contributions.rules ?? 0;
  return (
    <div className="signals">
      {keys.map((k) => {
        const v = latest?.signals[k] ?? null;
        const pts = latest?.contributions[k];
        const level = v === null ? "off" : v >= 0.7 ? "hot" : v >= 0.4 ? "warm" : "cool";
        return (
          <div key={k} className={`signal ${level}`}>
            <div className="sig-letter">{k}</div>
            <div className="sig-body">
              <div className="sig-head">
                <span className="sig-title">{META[k].title}</span>
                <span className="sig-value">{v === null ? "–" : v.toFixed(2)}</span>
              </div>
              <div className="bar">
                <div className="bar-fill" style={{ width: `${(v ?? 0) * 100}%` }} />
              </div>
              <div className="sig-detail">{latest ? detail(k, latest) : META[k].sub}</div>
            </div>
            <div className="sig-pts" title="Points this signal adds to the risk score R">
              {pts != null ? `+${pts.toFixed(0)}` : ""}
            </div>
          </div>
        );
      })}
      {latest && latest.rules.length > 0 && (
        <div className="signal rules">
          <div className="sig-letter">⚑</div>
          <div className="sig-body">
            <div className="sig-head">
              <span className="sig-title">Escalation rules fired</span>
            </div>
            <div className="sig-detail">{latest.rules.join(" · ")}</div>
          </div>
          <div className="sig-pts" title="Extra points needed to reach the rule's minimum risk">
            {uplift > 0 ? `+${uplift.toFixed(0)}` : ""}
          </div>
        </div>
      )}
    </div>
  );
}
