// Shared atoms — floating assistant, simple icons, shared bits
// Used by both Direction A and Direction B.

const Icon = {
  Search: () => (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
      <circle cx="7" cy="7" r="5" />
      <path d="m11 11 3 3" />
    </svg>
  ),
  Pin: () => (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M8 1v6l3 3v1H5v-1l3-3V1z" /><path d="M8 11v4" />
    </svg>
  ),
  External: () => (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
      <path d="M9 2h5v5" /><path d="M14 2 7 9" /><path d="M11 9v4H3V5h4" />
    </svg>
  ),
  Send: () => (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="m2 14 12-6L2 2l2 6-2 6z" />
    </svg>
  ),
  Sparkle: () => (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 2v4M9 12v4M2 9h4M12 9h4M4 4l2.5 2.5M11.5 11.5 14 14M14 4l-2.5 2.5M6.5 11.5 4 14" />
    </svg>
  ),
  Check: () => (
    <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m2 6 3 3 5-6" />
    </svg>
  ),
  Close: () => (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
      <path d="m3 3 8 8M11 3l-8 8" />
    </svg>
  ),
  Upload: () => (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M8 11V2M5 5l3-3 3 3" /><path d="M2 11v2a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-2" />
    </svg>
  ),
  Play: () => (
    <svg width="11" height="11" viewBox="0 0 12 12" fill="currentColor"><path d="M3 2v8l7-4z" /></svg>
  ),
};

function FloatingAssistant({ accent }) {
  const [open, setOpen] = React.useState(false);
  const [input, setInput] = React.useState("");
  const [turns, setTurns] = React.useState(window.MOCK.assistant.turns);

  function handleSubmit(e) {
    e.preventDefault();
    if (!input.trim()) return;
    setTurns(t => [...t, { role: "user", text: input }]);
    setInput("");
    setTimeout(() => {
      setTurns(t => [...t, {
        role: "assistant",
        text: "Got it. Working through that against your tailored package now…",
      }]);
    }, 400);
  }

  return (
    <>
      <button className="rd-fab" onClick={() => setOpen(o => !o)} aria-label="Open assistant">
        <Icon.Sparkle />
        {!open && <span className="rd-fab-dot" />}
      </button>

      {open && (
        <div className="rd-assistant" role="dialog" aria-label="Workspace assistant">
          <div className="rd-assistant-head">
            <div>
              <div className="rd-assistant-title">Assistant</div>
              <div className="rd-assistant-sub">Grounded in your active workspace</div>
            </div>
            <button className="rd-assistant-close" onClick={() => setOpen(false)} aria-label="Close">
              <Icon.Close />
            </button>
          </div>

          <div className="rd-assistant-body">
            {turns.map((t, i) => (
              <div key={i} className={`rd-bubble ${t.role === "user" ? "rd-bubble-user" : "rd-bubble-assistant"}`}>
                {t.text}
              </div>
            ))}
          </div>

          {turns.length <= 2 && (
            <div className="rd-suggestions">
              {window.MOCK.assistant.suggestions.map(s => (
                <button key={s} className="rd-suggestion" onClick={() => setInput(s)}>
                  {s}
                </button>
              ))}
            </div>
          )}

          <form className="rd-assistant-form" onSubmit={handleSubmit}>
            <textarea
              className="rd-assistant-input"
              value={input}
              onChange={e => setInput(e.target.value)}
              placeholder="Ask about your tailored package…"
              onKeyDown={e => {
                if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSubmit(e); }
              }}
            />
            <button type="submit" className="rd-assistant-send" aria-label="Send">
              <Icon.Send />
            </button>
          </form>
        </div>
      )}
    </>
  );
}

window.Icon = Icon;
window.FloatingAssistant = FloatingAssistant;
