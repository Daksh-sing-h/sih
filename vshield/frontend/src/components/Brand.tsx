export function Brand({ sub }: { sub?: string }) {
  return (
    <a className="brand" href="/">
      <svg viewBox="0 0 32 32" aria-hidden="true"><path d="M16 2 4 6v9c0 7.5 5.1 13.4 12 15 6.9-1.6 12-7.5 12-15V6z" /></svg>
      <div>
        <h1>V-SHIELD</h1>
        <p>{sub ?? "Real-time voice impersonation & fraud-risk firewall for calls"}</p>
      </div>
    </a>
  );
}
