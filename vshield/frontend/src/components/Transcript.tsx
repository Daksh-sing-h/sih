import { useEffect, useRef } from "react";
import type { Span, TranscriptMsg } from "../types";

const KIND_LABEL: Record<string, string> = {
  amount: "amount",
  transfer: "transfer",
  urgency: "urgency",
  secrecy: "secrecy",
  callback_avoid: "avoid call-back",
  credential: "credential",
  new_beneficiary: "new beneficiary",
  unusual_payment: "unusual payment",
  authority_claim: "authority claim",
  threat: "threat",
  remote_access: "remote-access app",
  lure: "prize / refund lure",
  kyc: "KYC / ID request",
  stay_on_line: "keeps you on the line",
};

/** Split text into plain / highlighted pieces; overlapping spans keep the first. */
function segments(text: string, spans: Span[]) {
  const sorted = [...spans].sort((a, b) => a.start - b.start || b.end - a.end);
  const out: { text: string; kind?: string }[] = [];
  let pos = 0;
  for (const s of sorted) {
    if (s.start < pos) continue;
    if (s.start > pos) out.push({ text: text.slice(pos, s.start) });
    out.push({ text: text.slice(s.start, s.end), kind: s.kind });
    pos = s.end;
  }
  if (pos < text.length) out.push({ text: text.slice(pos) });
  return out;
}

export function Transcript({ items, live }: { items: TranscriptMsg[]; live: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  // Scroll only this panel (not the page). Braces matter: scroll methods now return a
  // Promise in Chromium, and React would try to call a returned Promise as cleanup.
  useEffect(() => {
    const el = box.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [items.length]);

  return (
    <div className="transcript" ref={box}>
      {items.length === 0 && (
        <p className="empty">{live ? "Listening… transcripts appear ~1 s after each sentence." : "No call in progress."}</p>
      )}
      {items.map((tr, i) => (
        <div key={i} className={`utterance ${tr.spans.length ? "risky" : ""}`}>
          <div className="utt-meta">
            <span>{tr.t0.toFixed(1)}s</span>
            {tr.lang && tr.lang !== "en" && <span className="lang">{tr.lang.toUpperCase()} → EN</span>}
          </div>
          <p>
            {segments(tr.text, tr.spans).map((seg, j) =>
              seg.kind ? (
                <mark key={j} className={`hl hl-${seg.kind}`} title={KIND_LABEL[seg.kind] ?? seg.kind}>
                  {seg.text}
                </mark>
              ) : (
                <span key={j}>{seg.text}</span>
              ),
            )}
          </p>
        </div>
      ))}
      <p className="privacy-note">Transcript is held in memory for this screen only. It is never stored or logged.</p>
    </div>
  );
}
