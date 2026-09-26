const STAGES = [
  { key: "hook", title: "Hook", sub: "Claims authority, KYC, prize or refund" },
  { key: "pressure", title: "Pressure", sub: "Urgency, threats, “digital arrest”" },
  { key: "isolation", title: "Isolation", sub: "Don't hang up, don't tell anyone" },
  { key: "ask", title: "Ask", sub: "Money, OTP, AnyDesk, new account" },
];

function headline(reached: string[]) {
  if (reached.includes("ask") && reached.length >= 2) return ["critical", "Scam request made"];
  if (reached.includes("ask")) return ["high", "Sensitive request made"];
  if (reached.length >= 3) return ["high", "Scam script in progress"];
  if (reached.length === 2) return ["medium", "Heading into scam territory"];
  if (reached.length === 1) return ["low", "One warning sign so far"];
  return ["none", "No scam pattern so far"];
}

/** Where the conversation sits on the classic phone-scam script. */
export function ScamStages({ reached }: { reached: string[] }) {
  const [tone, text] = headline(reached);
  return (
    <div className="stages">
      <div className="stages-head">
        <h3>Scam-script tracker</h3>
        <span className={`stages-verdict tone-${tone}`}>{text}</span>
      </div>
      <ol className="stage-list">
        {STAGES.map((s, i) => {
          const order = reached.indexOf(s.key);
          return (
            <li key={s.key} className={`stage ${order >= 0 ? "on" : ""} stage-${s.key}`}>
              <span className="stage-num">{order >= 0 ? "✓" : i + 1}</span>
              <span className="stage-title">{s.title}</span>
              <span className="stage-sub">{s.sub}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
