// Shown once: recovery codes are stored hashed and cannot be displayed again.
export function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  return (
    <div className="recovery">
      <p>
        <strong>Save these 10 recovery codes</strong> (password manager or paper). Each works once
        if you lose your devices; they will not be shown again.
      </p>
      <ol className="codes">
        {codes.map((c) => (
          <li key={c}>
            <code>{c}</code>
          </li>
        ))}
      </ol>
      <div className="row">
        <button
          className="btn"
          onClick={() => void navigator.clipboard?.writeText(codes.join("\n"))}
        >
          Copy
        </button>
        <button className="btn primary" onClick={onDone}>
          I've saved them
        </button>
      </div>
    </div>
  );
}
