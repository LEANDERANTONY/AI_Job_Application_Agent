// Direction B — "Workbench"
// Step rail in topbar, hairline-divided regions instead of nested cards.

function DirectionB({ tab, setTab }) {
  const M = window.MOCK;
  const [activeJob, setActiveJob] = React.useState(M.jobResults[0].id);
  const [resumeMode, setResumeMode] = React.useState("upload");
  const [artTab, setArtTab] = React.useState("resume");
  const [accountOpen, setAccountOpen] = React.useState(false);
  const [cmdOpen, setCmdOpen] = React.useState(false);

  // Global ⌘K / Ctrl+K opens the command palette. Bound to the document
  // because the artboard's scroll wrapper otherwise eats the keydown.
  React.useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCmdOpen((o) => !o);
      }
      if (e.key === "Escape") setCmdOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const steps = [
  { id: "resume", label: "Resume", done: true, active: tab === "resume" },
  { id: "jobs", label: "Job Search", done: true, active: tab === "jobs" },
  { id: "jd", label: "Job Detail", done: true, active: tab === "jd" },
  { id: "analysis", label: "Analysis", done: false, active: tab === "analysis" }];


  // Hero context — same shape as Direction A's hero, used on every page.
  // We pull a header line + subtitle per step so the user always knows what
  // role + workspace they're operating on.
  const hero = {
    title: "Workspace",
    sub: "Anthropic · Senior ML Engineer, Inference Platform"
  };

  return (
    <div className="rd-root b-shell" style={{ position: "relative" }}>
      <div className="b-topbar">
        <div className="b-brand">
          <div className="b-brand-mark"><img src="redesign/job-copilot-logo.png" alt="" /></div>
          <div className="b-brand-name">Job Application Copilot</div>
        </div>

        <div className="b-topbar-actions" style={{ textAlign: "center", justifyContent: "flex-end", display: "flex", alignItems: "center", gap: 10 }}>
          <button className="b-cmd-trigger" onClick={() => setCmdOpen(true)}>
            <span className="b-cmd-trigger-icon"><Icon.Search /></span>
            <span className="b-cmd-trigger-text">Search or run command…</span>
            <span className="b-cmd-trigger-keys">
              <span className="b-cmd-key">⌘</span>
              <span className="b-cmd-key">K</span>
            </span>
          </button>
          <div className="b-account" onClick={() => setAccountOpen((o) => !o)}>
            <div className="b-account-avatar">L</div>
            <div className="b-account-name">Leander</div>
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"><path d="m2.5 4 2.5 2.5L7.5 4" /></svg>
            {accountOpen &&
            <div className="b-account-popover" onClick={(e) => e.stopPropagation()}>
                <div className="b-account-pop-head">
                  <div className="b-account-avatar" style={{ width: 32, height: 32, fontSize: 13 }}>L</div>
                  <div>
                    <div style={{ fontSize: 13.5, fontWeight: 600 }}>Leander Antony</div>
                    <div style={{ fontSize: 12, color: "var(--fg-3)" }}>leander@example.com</div>
                  </div>
                </div>
                <div className="b-account-pop-meta">
                  <span className="rd-chip">Plan · Free</span>
                  <span className="rd-chip">Runs left · 12 / 20</span>
                </div>
                <hr className="rd-hairline" style={{ margin: "10px 0" }} />
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  <button className="rd-btn rd-btn-ghost rd-btn-sm" style={{ justifyContent: "flex-start", marginTop: 4 }}>Sign out</button>
                </div>
              </div>
            }
          </div>
        </div>
      </div>

      <div className="b-rail-row">
        <div className="b-rail" role="tablist">
          {steps.map((s, i) =>
            <React.Fragment key={s.id}>
              <button
                className="b-rail-step"
                role="tab"
                aria-selected={s.active}
                data-done={s.done && !s.active}
                onClick={() => setTab(s.id)}>
                <span className="b-rail-num">{s.done && !s.active ? <Icon.Check /> : `0${i + 1}`}</span>
                {s.label}
              </button>
              {i < steps.length - 1 && <div className="b-rail-divider" />}
            </React.Fragment>
          )}
        </div>
      </div>

      <div style={{ overflow: "auto" }}>
        <div className="b-hero">
          <div>
            <div className="b-hero-title">{hero.title}</div>
            <div className="b-hero-sub">{hero.sub}</div>
          </div>
          <div className="b-hero-stats">
            <span className="b-hero-stat"><strong>Resume</strong> · {M.candidate.name}</span>
            <span className="b-hero-stat"><strong>Mode</strong> · AI-assisted</span>
            <span className="b-hero-stat rd-pip rd-pip-live">Outputs ready</span>
          </div>
        </div>

        <div className="b-canvas">
          {tab === "resume" && <ResumeTabB mode={resumeMode} setMode={setResumeMode} />}
          {tab === "jobs" && <JobsTabB activeJob={activeJob} setActiveJob={setActiveJob} />}
          {tab === "jd" && <JDTabB />}
          {tab === "analysis" && <AnalysisTabB artTab={artTab} setArtTab={setArtTab} />}
        </div>
      </div>

      <FloatingAssistant />
      {cmdOpen && <CommandPalette onClose={() => setCmdOpen(false)} setTab={setTab} />}
    </div>);

}

function ResumeTabB({ mode, setMode }) {
  const M = window.MOCK;
  const c = M.candidate;
  return (
    <div className="b-region">
      {/* 1. Intake first — mode toggle + the actual upload/builder UI.
          The hero below represents what was parsed FROM this upload. */}
      <div className="b-intake-panel">
        <div className="b-intake-head">
          <div>
            <div className="b-section-label">STEP 01 · IMPORT RESUME</div>
            <div className="b-intake-title">Bring in your resume</div>
          </div>
          <div className="b-intake-modes">
            <button className="b-intake-mode" data-active={mode === "upload"} onClick={() => setMode("upload")}>Upload</button>
            <button className="b-intake-mode" data-active={mode === "assistant"} onClick={() => setMode("assistant")}>Build with assistant</button>
          </div>
        </div>

        {mode === "upload" ? (
          <div className="b-drop">
            <div style={{ display: "grid", placeItems: "center", margin: "0 auto 10px", width: 30, height: 30, borderRadius: 999, background: "var(--accent-soft)", color: "var(--accent-strong)" }}>
              <Icon.Upload />
            </div>
            <div style={{ fontSize: 13.5, color: "var(--fg)", fontWeight: 500 }}>Drop your resume here</div>
            <div style={{ fontSize: 12.5, color: "var(--fg-3)", marginTop: 4 }}>PDF, DOCX or TXT · Up to 5MB</div>
            <button className="rd-btn rd-btn-ghost rd-btn-sm" style={{ marginTop: 12 }}>Choose file</button>
            <div style={{ fontSize: 12, color: "var(--fg-3)", marginTop: 14 }}>
              Last upload: <span className="rd-mono" style={{ color: "var(--fg-2)" }}>resume_v3.pdf</span> · 2d ago
            </div>
          </div>
        ) : (
          <div>
            <div style={{ fontSize: 13, color: "var(--fg-2)", lineHeight: 1.65, marginBottom: 12 }}>
              The guided builder asks short, focused questions and turns your answers into a clean base resume.
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {[
                ["Basics", true],
                ["Target role", true],
                ["Experience", false],
                ["Education", false],
                ["Skills", false]
              ].map(([s, done]) => (
                <div key={s} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid var(--hairline)", fontSize: 13 }}>
                  <span style={{ color: done ? "var(--fg-2)" : "var(--fg-3)" }}>{s}</span>
                  <span className="rd-mono" style={{ color: done ? "var(--success)" : "var(--fg-4)", fontSize: 11 }}>
                    {done ? "DONE" : "—"}
                  </span>
                </div>
              ))}
            </div>
            <button className="rd-btn rd-btn-primary rd-btn-sm" style={{ alignSelf: "flex-start", marginTop: 12 }}>Continue</button>
          </div>
        )}
      </div>

      {/* 2. Parsed result hero — appears below because it's the OUTPUT of the upload */}
      <div className="b-resume-hero">
        <span className="b-resume-hero-pill">Parsed profile</span>
        <h1 className="b-resume-hero-title">{c.name}</h1>
        <div className="b-resume-hero-meta">
          <span>{c.title}</span>
          <span>{c.location}</span>
          <span>{c.experience.length} roles · {c.skills.length} skills detected</span>
          <span><span className="rd-mono" style={{ color: "var(--fg-2)" }}>resume_v3.pdf</span> · 2d ago</span>
        </div>
      </div>

      {/* 3. Two-up — Skills + Experience side-by-side */}
      <div className="b-resume-twoup">
        <div className="b-twoup-section">
          <div className="b-twoup-head">
            <div className="b-twoup-title">Skills</div>
            <div className="b-twoup-sub">{c.skills.length} detected</div>
          </div>
          <div className="b-skill-chips">
            {c.skills.map((s, i) => (
              <span key={s} className="b-skill-chip" data-tone={i % 4 === 0 ? "bold" : null}>{s}</span>
            ))}
          </div>
        </div>

        <div className="b-twoup-section">
          <div className="b-twoup-head">
            <div className="b-twoup-title">Experience</div>
            <div className="b-twoup-sub">{c.experience.length} roles</div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {c.experience.map((e) => (
              <div key={e.org} className="b-experience-card">
                <div>
                  <div className="b-experience-title">{e.title}</div>
                  <div className="b-experience-org">{e.org}</div>
                </div>
                <div className="b-experience-period">{e.period}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 4. Parser signals — full-width row */}
      <div className="b-twoup-section">
        <div className="b-twoup-head">
          <div className="b-twoup-title">Parser signals</div>
          <div className="b-twoup-sub">Live read of your CV</div>
        </div>
        <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          {c.signals.map((s) => (
            <li key={s} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 12.5, color: "var(--fg-2)" }}>
              <span style={{
                width: 22, height: 22, borderRadius: 6, display: "grid", placeItems: "center",
                background: "color-mix(in oklch, var(--success) 18%, transparent)",
                color: "var(--success)",
                flex: "0 0 auto",
              }}><Icon.Check /></span>
              {s}
            </li>
          ))}
        </ul>
      </div>
    </div>);

}

function JobsTabB({ activeJob, setActiveJob }) {
  const M = window.MOCK;

  // Mirror saved state locally so the user can toggle save/unsave inside this artboard.
  const [savedIds, setSavedIds] = React.useState(
    () => new Set(M.jobResults.filter((j) => j.saved).map((j) => j.id))
  );
  const [savedOpen, setSavedOpen] = React.useState(false);
  const toggleSaved = (id) => {
    setSavedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const renderTile = (j, opts = {}) => {
    const isSaved = savedIds.has(j.id);
    const isTopMatch = opts.topMatch === true;
    return (
      <div key={j.id} className="a-job" data-active={activeJob === j.id} data-top-match={isTopMatch} onClick={() => setActiveJob(j.id)}>
        <div className="a-job-head">
          <div>
            <div className="a-job-title">{j.title}</div>
            <div className="a-job-company">{j.company} · {j.source}</div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
            {isTopMatch && (
              <span className="b-top-match-badge">
                <svg viewBox="0 0 12 12" fill="currentColor"><path d="M6 .5l1.6 3.4 3.7.5-2.7 2.6.6 3.7L6 8.9 2.8 10.7l.6-3.7L.7 4.4l3.7-.5z" /></svg>
                Top match
              </span>
            )}
            {isSaved && <span className="a-saved-mark">SAVED</span>}
          </div>
        </div>
        <div className="a-job-summary">{j.summary}</div>
        <div className="a-job-meta">
          <span>{j.location}</span>
          <span className="a-job-meta-dot" />
          <span>{j.posted}</span>
          {j.badges.slice(0, 1).map((b) => (
            <React.Fragment key={b}>
              <span className="a-job-meta-dot" />
              <span>{b}</span>
            </React.Fragment>
          ))}
        </div>
        <div className="a-job-actions">
          <button className="rd-btn rd-btn-sm rd-btn-ghost">Review</button>
          <button className="rd-btn rd-btn-sm rd-btn-quiet"><Icon.External /> Open</button>
          <button
            className="rd-btn rd-btn-sm rd-btn-quiet"
            onClick={(e) => { e.stopPropagation(); toggleSaved(j.id); }}
            aria-pressed={isSaved}
          >
            <Icon.Pin /> {isSaved ? "Unsave" : "Save"}
          </button>
        </div>
      </div>
    );
  };

  const savedJobs = M.jobResults.filter((j) => savedIds.has(j.id));
  const matchJobs = M.jobResults.filter((j) => !savedIds.has(j.id));

  return (
    <div className="b-region">
      <div className="b-region-head">
        <div>
          <div className="b-region-title">Find a role</div>
          <div className="b-region-sub">Search live listings, paste a posting URL, or open a saved job.</div>
        </div>
        <span className="b-region-tag">STEP 02</span>
      </div>

      <div className="b-search-bar">
        <div className="b-search-icon"><Icon.Search /></div>
        <input defaultValue="machine learning engineer" placeholder="Keywords" />
        <div className="b-search-divider" />
        <input placeholder="Location · or remote" />
        <button className="rd-btn rd-btn-primary rd-btn-sm">Search</button>
      </div>

      <div className="b-search-row">
        <div className="b-search-filters">
          <label className="a-toggle"><input type="checkbox" /> Remote only</label>
          <label className="a-toggle">Posted within
            <select className="rd-select" style={{ width: "auto", padding: "3px 6px", marginLeft: 4, height: 26 }}>
              <option>Any time</option><option>Last 7 days</option><option>Last 30 days</option>
            </select>
          </label>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span>Or paste URL:</span>
          <input className="rd-input" placeholder="greenhouse.io/…" style={{ width: 240, height: 30, padding: "4px 10px" }} />
          <button className="rd-btn rd-btn-ghost rd-btn-sm">Import</button>
        </div>
      </div>

      {/* Saved jobs — collapsible drawer above fresh matches */}
      <div className="b-saved-section">
        <button
          type="button"
          className="b-saved-toggle"
          onClick={() => setSavedOpen((o) => !o)}
          aria-expanded={savedOpen}
        >
          <svg
            className="b-saved-caret"
            width="11" height="11" viewBox="0 0 11 11"
            fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"
            style={{ transform: savedOpen ? "rotate(90deg)" : "rotate(0deg)" }}
          >
            <path d="M3.5 2L7 5.5L3.5 9" />
          </svg>
          <span className="b-saved-title">Saved jobs</span>
          <span className="b-saved-count">{savedJobs.length} saved</span>
        </button>
        {savedOpen && (
          savedJobs.length ? (
            <div className="a-job-grid" style={{ marginTop: 12 }}>
              {savedJobs.map(renderTile)}
            </div>
          ) : (
            <div className="b-saved-empty">Nothing saved yet. Save matches to revisit them later.</div>
          )
        )}
      </div>

      <div className="b-results-head">
        <div className="b-section-label">MATCHES · {matchJobs.length} ROLES</div>
        <div style={{ fontSize: 12.5, color: "var(--fg-3)" }}>Sorted by recency</div>
      </div>

      <div className="a-job-grid">
        {matchJobs.map((j, i) => renderTile(j, { topMatch: i === 0 }))}
      </div>
    </div>);

}

function JDTabB() {
  const M = window.MOCK.jd;
  const [jdMode, setJdMode] = React.useState("paste"); // 'paste' | 'url'
  return (
    <div className="b-region">
      {/* 1. Source intake — paste/upload/import row, mirroring the resume intake card */}
      <div className="b-intake-panel">
        <div className="b-intake-head">
          <div>
            <div className="b-section-label">STEP 03 · IMPORT JD</div>
            <div className="b-intake-title">Bring in the job description</div>
          </div>
          <div className="b-intake-modes">
            <button className="b-intake-mode" data-active={jdMode === "paste"} onClick={() => setJdMode("paste")}>Paste text</button>
            <button className="b-intake-mode" data-active={jdMode === "url"} onClick={() => setJdMode("url")}>From URL</button>
          </div>
        </div>

        {jdMode === "paste" ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <textarea
              className="rd-textarea"
              defaultValue={M.summary + "\n\n" + M.sections.map((s) => `${s.title}\n${s.body}`).join("\n\n")}
              style={{ minHeight: 160 }}
            />
            <div style={{ display: "flex", gap: 6, justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ fontSize: 12, color: "var(--fg-3)" }}>
                Imported from <span className="rd-mono" style={{ color: "var(--fg-2)" }}>greenhouse.io</span> · 4m ago
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <button className="rd-btn rd-btn-quiet rd-btn-sm">Clear</button>
                <button className="rd-btn rd-btn-ghost rd-btn-sm">Re-parse</button>
              </div>
            </div>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div style={{ display: "flex", gap: 8 }}>
              <input className="rd-input" placeholder="https://boards.greenhouse.io/…" defaultValue="https://boards.greenhouse.io/anthropic/jobs/4719" style={{ flex: 1 }} />
              <button className="rd-btn rd-btn-primary rd-btn-sm"><Icon.External /> Import</button>
            </div>
            <div style={{ fontSize: 12, color: "var(--fg-3)" }}>
              Supports Greenhouse, Lever, Ashby, LinkedIn, and most common ATS pages.
            </div>
          </div>
        )}
      </div>

      {/* 2. Parsed-JD hero — same shape as the Resume tab's hero */}
      <div className="b-resume-hero">
        <span className="b-resume-hero-pill">Parsed JD</span>
        <h1 className="b-resume-hero-title">{M.title}</h1>
        <div className="b-resume-hero-meta">
          <span>{M.company}</span>
          <span>San Francisco · Remote OK</span>
          <span>Source: Greenhouse</span>
          <span><span className="rd-mono" style={{ color: "var(--fg-2)" }}>jd_4719.txt</span> · 4m ago</span>
        </div>
        {/* Metrics row — three quiet stat tiles inline in the hero */}
        <div className="b-jd-metrics">
          {M.metrics.map((m) => (
            <div key={m.label} className="b-jd-metric">
              <div className="b-jd-metric-label">{m.label}</div>
              <div className="b-jd-metric-value">
                {m.value}<span className="b-jd-metric-unit">{m.unit}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 3. Summary — full-width section block */}
      <div className="b-twoup-section">
        <div className="b-twoup-head">
          <div className="b-twoup-title">Summary</div>
          <div className="b-twoup-sub">At a glance</div>
        </div>
        <p style={{ fontSize: 13.5, lineHeight: 1.7, color: "var(--fg-2)", margin: 0 }}>{M.summary}</p>
      </div>

      {/* 4. Two-up — Hard skills + Soft skills */}
      <div className="b-resume-twoup">
        <div className="b-twoup-section">
          <div className="b-twoup-head">
            <div className="b-twoup-title">Hard skills</div>
            <div className="b-twoup-sub">{M.hardSkills.length} required</div>
          </div>
          <div className="b-skill-chips">
            {M.hardSkills.map((s, i) => (
              <span key={s} className="b-skill-chip" data-tone={i % 3 === 0 ? "bold" : null}>{s}</span>
            ))}
          </div>
        </div>
        <div className="b-twoup-section">
          <div className="b-twoup-head">
            <div className="b-twoup-title">Soft skills</div>
            <div className="b-twoup-sub">{M.softSkills.length} signals</div>
          </div>
          <div className="b-skill-chips">
            {M.softSkills.map((s) => <span key={s} className="b-skill-chip">{s}</span>)}
          </div>
        </div>
      </div>

      {/* 5. JD body sections — each a full-width section block */}
      {M.sections.map((s) => (
        <div key={s.title} className="b-twoup-section">
          <div className="b-twoup-head">
            <div className="b-twoup-title">{s.title}</div>
          </div>
          <p style={{ fontSize: 13.5, lineHeight: 1.7, color: "var(--fg-2)", margin: 0 }}>{s.body}</p>
        </div>
      ))}
    </div>);

}

function AnalysisTabB({ artTab, setArtTab }) {
  const M = window.MOCK;
  const art = M.artifact[artTab === "resume" ? "resume" : "cover"];

  // Stream the artifact body in on tab change. Reveals char-by-char with a
  // blinking caret — signals "this output is alive / freshly generated".
  const [streamed, setStreamed] = React.useState("");
  const [streaming, setStreaming] = React.useState(true);
  React.useEffect(() => {
    setStreamed("");
    setStreaming(true);
    const full = art.preview || "";
    // Chunk-stream rather than char-stream — chars feel slow on long docs,
    // chunks of 6–10 feel like a fast LLM completion.
    let i = 0;
    const tick = () => {
      i = Math.min(full.length, i + 8);
      setStreamed(full.slice(0, i));
      if (i >= full.length) {
        setStreaming(false);
        return;
      }
      timer = setTimeout(tick, 12);
    };
    let timer = setTimeout(tick, 200);
    return () => clearTimeout(timer);
  }, [art.preview]);

  return (
    <>
      <div className="b-region">
        <div className="b-region-head">
          <div>
            <div className="b-region-title">Workflow run</div>
            <div className="b-region-sub">AI-assisted · finished in 38s · 4 stages</div>
          </div>
          <span className="b-region-tag">STEP 04</span>
        </div>

        <div className="b-run-bar">
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span className="rd-pip rd-pip-live">Outputs ready</span>
            <span style={{ fontSize: 13, color: "var(--fg-3)" }}>Last run · 2 minutes ago</span>
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <button className="rd-btn rd-btn-ghost rd-btn-sm"><Icon.Play /> Re-run</button>
            <button className="rd-btn rd-btn-danger rd-btn-sm">Clear role</button>
          </div>
        </div>

        <div className="b-pipeline">
          {M.workflow.stages.map((s) =>
          <div key={s.id} className="b-pipeline-stage" data-state={s.value === 100 ? "done" : s.value > 0 ? "active" : "next"}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <span className="b-pipeline-stage-name">{s.title}</span>
                <span className="rd-mono" style={{ fontSize: 11, color: "var(--fg-3)" }}>{s.value}%</span>
              </div>
              <div className="b-pipeline-stage-detail">{s.detail}</div>
              <div className="b-pipeline-stage-bar"><span style={{ width: `${s.value}%` }} /></div>
            </div>
          )}
        </div>
      </div>

      <div className="b-region">
        <div className="b-region-head">
          <div>
            <div className="b-region-title">Documents</div>
            <div className="b-region-sub">Review and download your tailored package.</div>
          </div>
        </div>

        <div className="b-artifact-tabs" role="tablist">
          <button className="b-artifact-tab" aria-selected={artTab === "resume"} onClick={() => setArtTab("resume")}>
            Tailored Resume
          </button>
          <button className="b-artifact-tab" aria-selected={artTab === "cover"} onClick={() => setArtTab("cover")}>
            Cover Letter
          </button>
        </div>

        <div className="b-artifact-body">
          <div className={"b-artifact-doc" + (streaming ? " is-streaming" : "")}>{streamed}</div>

          <div className="b-artifact-aside">
            <h4 className="b-artifact-aside-title">{art.title}</h4>
            {streaming && (
              <span className="b-streaming-chip">
                <span className="b-streaming-chip-dot" /> Streaming
              </span>
            )}
            <p className="b-artifact-aside-text">{art.summary}</p>
            <hr className="rd-hairline" style={{ margin: "10px 0" }} />
            <div className="b-artifact-actions">
              <button className="rd-btn rd-btn-primary rd-btn-sm">Download PDF</button>
              <button className="rd-btn rd-btn-ghost rd-btn-sm">Download Markdown</button>
              <button className="rd-btn rd-btn-quiet rd-btn-sm">Copy to clipboard</button>
            </div>
          </div>
        </div>
      </div>
    </>);

}

window.DirectionB = DirectionB;

// ── Command palette ────────────────────────────────────────────────────
// A ⌘K overlay listing nav targets and AI actions. Mostly visual
// affordance — confirms "this is an AI-native app" and provides quick
// step-jumping. Keyboard navigation: ↑↓ to move, ↵ to run, Esc to close.
function CommandPalette({ onClose, setTab }) {
  const [query, setQuery] = React.useState("");
  const [active, setActive] = React.useState(0);
  const inputRef = React.useRef(null);

  React.useEffect(() => { inputRef.current?.focus(); }, []);

  const items = [
    { group: "Navigate", icon: <Icon.Upload />, title: "Go to Resume",     sub: "Step 01 · Import & parse",       run: () => setTab("resume"),   shortcut: "1" },
    { group: "Navigate", icon: <Icon.Search />, title: "Go to Job Search", sub: "Step 02 · Roles & filters",      run: () => setTab("jobs"),     shortcut: "2" },
    { group: "Navigate", icon: <Icon.Sparkle />, title: "Go to Job Detail",sub: "Step 03 · Parsed JD",            run: () => setTab("jd"),       shortcut: "3" },
    { group: "Navigate", icon: <Icon.Play />,   title: "Go to Analysis",   sub: "Step 04 · Run & artifacts",      run: () => setTab("analysis"), shortcut: "4" },
    { group: "Actions",  icon: <Icon.Sparkle />,title: "Tailor resume to active JD",  sub: "Re-runs the workflow with current selection" },
    { group: "Actions",  icon: <Icon.Sparkle />,title: "Generate cover letter",       sub: "Uses parsed JD + resume profile" },
    { group: "Actions",  icon: <Icon.Sparkle />,title: "Find skill gaps",             sub: "Compare resume to JD requirements" },
    { group: "Actions",  icon: <Icon.Sparkle />,title: "Explain a job match score",   sub: "Why was this role surfaced?" },
    { group: "Settings", icon: <Icon.Upload />, title: "Re-upload resume",            sub: "Replace the parsed source file" },
    { group: "Settings", icon: <Icon.Close />,  title: "Clear active role",           sub: "Removes the JD from the workspace" },
  ];

  const filtered = query
    ? items.filter((i) =>
        (i.title + " " + i.sub).toLowerCase().includes(query.toLowerCase())
      )
    : items;

  // Group results in display order.
  const groups = [];
  filtered.forEach((it) => {
    let g = groups.find((x) => x.label === it.group);
    if (!g) { g = { label: it.group, items: [] }; groups.push(g); }
    g.items.push(it);
  });

  // Build a flat index map so up/down navigation works across groups.
  const flat = filtered;
  const safeActive = Math.min(active, flat.length - 1);

  const onKey = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, flat.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === "Enter") {
      e.preventDefault();
      const it = flat[safeActive];
      if (it?.run) { it.run(); onClose(); }
    }
  };

  return (
    <div className="b-cmd-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="b-cmd-panel" onKeyDown={onKey}>
        <div className="b-cmd-input-wrap">
          <span className="b-cmd-input-icon"><Icon.Search /></span>
          <input
            ref={inputRef}
            className="b-cmd-input"
            placeholder="Search or run a command…"
            value={query}
            onChange={(e) => { setQuery(e.target.value); setActive(0); }}
          />
          <span className="b-cmd-esc">Esc</span>
        </div>

        <div className="b-cmd-list">
          {groups.length === 0 ? (
            <div style={{ padding: "20px 12px", color: "var(--fg-3)", fontSize: 13, textAlign: "center" }}>
              No results for "{query}"
            </div>
          ) : (
            groups.map((g) => {
              return (
                <React.Fragment key={g.label}>
                  <div className="b-cmd-section-label">{g.label}</div>
                  {g.items.map((it) => {
                    const idx = flat.indexOf(it);
                    return (
                      <button
                        key={it.title}
                        className="b-cmd-item"
                        data-active={idx === safeActive}
                        onMouseEnter={() => setActive(idx)}
                        onClick={() => { if (it.run) { it.run(); onClose(); } }}
                      >
                        <span className="b-cmd-item-icon">{it.icon}</span>
                        <span className="b-cmd-item-main">
                          <span className="b-cmd-item-title">{it.title}</span>
                          <span className="b-cmd-item-sub">{it.sub}</span>
                        </span>
                        {it.shortcut && <span className="b-cmd-item-shortcut">⌘{it.shortcut}</span>}
                      </button>
                    );
                  })}
                </React.Fragment>
              );
            })
          )}
        </div>

        <div className="b-cmd-footer">
          <span>Grounded in your active workspace</span>
          <span className="b-cmd-footer-keys">
            <span className="b-cmd-footer-key">↑↓ navigate</span>
            <span className="b-cmd-footer-key">↵ run</span>
            <span className="b-cmd-footer-key">esc close</span>
          </span>
        </div>
      </div>
    </div>
  );
}