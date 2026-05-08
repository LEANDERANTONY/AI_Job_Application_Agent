// Direction A — "Tightened"
// Same DNA, disciplined: one card level, calmer chips, demoted hero.

function DirectionA({ tab, setTab }) {
  const M = window.MOCK;
  const [activeJob, setActiveJob] = React.useState(M.jobResults[0].id);
  const [resumeMode, setResumeMode] = React.useState("upload");
  const [artTab, setArtTab] = React.useState("resume");
  const [accountOpen, setAccountOpen] = React.useState(false);

  const tabs = [
    { id: "resume",   label: "Resume",     status: "Ready",       state: "live" },
    { id: "jobs",     label: "Job Search", status: "4 matches",   state: "ready" },
    { id: "jd",       label: "Job Detail", status: "Ready",       state: "live" },
    { id: "analysis", label: "Analysis",   status: "Outputs ready", state: "live" },
  ];

  return (
    <div className="rd-root a-shell" style={{ position: "relative" }}>
      <div className="a-topbar">
        <div className="a-brand">
          <div className="a-brand-mark"><img src="redesign/job-copilot-logo.png" alt="" /></div>
          <div className="a-brand-name">Job Application Copilot</div>
        </div>
        <div className="a-topbar-actions">
          <button className="rd-btn rd-btn-quiet rd-btn-sm">Reload workspace</button>
          <div
            className="a-account"
            onClick={() => setAccountOpen((o) => !o)}
            aria-expanded={accountOpen}
            role="button"
            tabIndex={0}
          >
            <div className="a-account-avatar">L</div>
            <div className="a-account-name">Leander</div>
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" style={{ opacity: 0.6 }}>
              <path d="m2.5 4 2.5 2.5L7.5 4" />
            </svg>
            {accountOpen && (
              <div className="a-account-popover" onClick={(e) => e.stopPropagation()}>
                <div className="a-account-pop-head">
                  <div className="a-account-avatar" style={{ width: 32, height: 32, fontSize: 13 }}>L</div>
                  <div>
                    <div style={{ fontSize: 13.5, fontWeight: 600 }}>Leander Antony</div>
                    <div style={{ fontSize: 12, color: "var(--fg-3)" }}>leander@example.com</div>
                  </div>
                </div>
                <div className="a-account-pop-meta">
                  <span className="rd-chip">Plan · Free</span>
                  <span className="rd-chip">Runs left · 12 / 20</span>
                </div>
                <hr className="rd-hairline" style={{ margin: "10px 0" }} />
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  <button className="rd-btn rd-btn-ghost rd-btn-sm" style={{ justifyContent: "flex-start", marginTop: 4 }}>Sign out</button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="a-hero">
        <div className="a-hero-left">
          <div>
            <div className="a-hero-title">Workspace</div>
            <div className="a-hero-sub">Anthropic · Senior ML Engineer, Inference Platform</div>
          </div>
        </div>
        <div className="a-hero-stats">
          <span className="a-hero-stat"><strong>Resume</strong> · {M.candidate.name}</span>
          <span className="a-hero-stat"><strong>Mode</strong> · AI-assisted</span>
          <span className="a-hero-stat rd-pip rd-pip-live">Outputs ready</span>
        </div>
      </div>

      <div className="a-content">
        <div className="a-tabs" role="tablist">
          {tabs.map((t, i) => (
            <button
              key={t.id}
              className="a-tab"
              role="tab"
              aria-selected={tab === t.id}
              onClick={() => setTab(t.id)}
            >
              <span className="a-tab-num">0{i + 1}</span>
              {t.label}
            </button>
          ))}
        </div>

        {tab === "resume"   && <ResumeTabA mode={resumeMode} setMode={setResumeMode} />}
        {tab === "jobs"     && <JobsTabA activeJob={activeJob} setActiveJob={setActiveJob} />}
        {tab === "jd"       && <JDTabA />}
        {tab === "analysis" && <AnalysisTabA artTab={artTab} setArtTab={setArtTab} />}
      </div>

      <FloatingAssistant />
    </div>
  );
}

function ResumeTabA({ mode, setMode }) {
  const M = window.MOCK;
  return (
    <div className="rd-card">
      <div className="a-section-head">
        <div>
          <p className="rd-eyebrow">Step 01 · Resume</p>
          <div className="a-section-title">Bring in your resume</div>
          <div className="a-section-sub">Upload an existing one or build a base resume with the assistant.</div>
        </div>
        <span className="rd-pip rd-pip-live">Profile loaded</span>
      </div>

      <div className="a-mode-toggle">
        <button data-active={mode === "upload"}     onClick={() => setMode("upload")}>Upload resume</button>
        <button data-active={mode === "assistant"}  onClick={() => setMode("assistant")}>Build with assistant</button>
      </div>

      <div className="a-resume-grid">
        <div>
          {mode === "upload" ? (
            <div className="a-uploader">
              <div className="a-uploader-icon"><Icon.Upload /></div>
              <div className="a-uploader-title">Drop a PDF, DOCX or TXT</div>
              <div className="a-uploader-sub">Or click to browse — parsed in a few seconds.</div>
              <button className="rd-btn rd-btn-primary rd-btn-sm" style={{ marginTop: 8 }}>Choose file</button>
            </div>
          ) : (
            <div className="rd-inset" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontSize: 13.5, color: "var(--fg-2)" }}>
                The assistant will ask short focused questions about your background, then turn your answers into a clean base resume.
              </div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {["Basics","Target role","Experience","Education","Skills"].map((s, i) => (
                  <span key={s} className={`rd-chip ${i < 2 ? "rd-chip-soft" : ""}`}>
                    {i < 2 && <Icon.Check />} {s}
                  </span>
                ))}
              </div>
              <button className="rd-btn rd-btn-primary" style={{ alignSelf: "flex-start" }}>Continue</button>
            </div>
          )}
        </div>

        <div className="a-profile-card">
          <div className="a-profile-head">
            <div className="a-profile-avatar">{M.candidate.name.slice(0,1)}</div>
            <div>
              <div className="a-profile-name">{M.candidate.name}</div>
              <div className="a-profile-meta">{M.candidate.title} · {M.candidate.location}</div>
            </div>
          </div>

          <div className="a-stat-row" style={{ borderTop: "1px solid var(--hairline)", borderBottom: "1px solid var(--hairline)" }}>
            <div>
              <div className="a-stat-num">{M.candidate.skills.length}</div>
              <div className="a-stat-label">Skills</div>
            </div>
            <div>
              <div className="a-stat-num">{M.candidate.experience.length}</div>
              <div className="a-stat-label">Roles</div>
            </div>
            <div>
              <div className="a-stat-num">4y</div>
              <div className="a-stat-label">Tenure</div>
            </div>
          </div>

          <div className="a-skills-block">
            <div className="a-skills-block-label">Top skills</div>
            <div className="a-skills">
              {M.candidate.skills.slice(0, 10).map(s => <span key={s} className="rd-chip rd-chip-skill">{s}</span>)}
            </div>
          </div>

          <div className="a-skills-block">
            <div className="a-skills-block-label">Resume signals</div>
            <ul className="a-list">{M.candidate.signals.map(s => <li key={s}>{s}</li>)}</ul>
          </div>
        </div>
      </div>
    </div>
  );
}

function JobsTabA({ activeJob, setActiveJob }) {
  const M = window.MOCK;
  // Local saved state — mirrored from mock data so the user can toggle save/unsave
  // without mutating the global mock.
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

  // Render helper so the same tile markup serves both lists.
  const renderTile = (j) => {
    const isSaved = savedIds.has(j.id);
    return (
      <div key={j.id} className="a-job" data-active={activeJob === j.id} onClick={() => setActiveJob(j.id)}>
        <div className="a-job-head">
          <div>
            <div className="a-job-title">{j.title}</div>
            <div className="a-job-company">{j.company} · {j.source}</div>
          </div>
          {isSaved && <span className="a-saved-mark">SAVED</span>}
        </div>
        <div className="a-job-summary">{j.summary}</div>
        <div className="a-job-meta">
          <span>{j.location}</span>
          <span className="a-job-meta-dot" />
          <span>{j.posted}</span>
          {j.badges.slice(0, 1).map(b => (
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
    <div className="rd-card">
      <div className="a-section-head">
        <div>
          <p className="rd-eyebrow">Step 02 · Job Search</p>
          <div className="a-section-title">Find a role to apply for</div>
          <div className="a-section-sub">Search live listings, paste a posting URL, or open one from saved jobs.</div>
        </div>
      </div>

      <div className="a-search-form">
        <div>
          <label className="rd-label">Keywords</label>
          <input className="rd-input" defaultValue="machine learning engineer" />
        </div>
        <div>
          <label className="rd-label">Location</label>
          <input className="rd-input" placeholder="Anywhere" />
        </div>
        <button className="rd-btn rd-btn-primary"><Icon.Search /> Search</button>
      </div>

      <div className="a-search-filters">
        <label className="a-toggle"><input type="checkbox" /> Remote only</label>
        <label className="a-toggle">Posted within
          <select className="rd-select" style={{ width: "auto", padding: "4px 8px", marginLeft: 4 }}>
            <option>Any time</option><option>Last 7 days</option><option>Last 30 days</option>
          </select>
        </label>
        <div style={{ flex: 1 }} />
        <div className="a-import-row" style={{ flex: "0 0 360px" }}>
          <input className="rd-input" placeholder="Or paste a Greenhouse / Lever job URL" />
          <button className="rd-btn rd-btn-ghost">Import</button>
        </div>
      </div>

      {/* Saved jobs — collapsible, sits above fresh matches so a new search
          doesn't bury the user's existing shortlist. */}
      <div className="a-saved-section">
        <button
          type="button"
          className="a-saved-toggle"
          onClick={() => setSavedOpen((o) => !o)}
          aria-expanded={savedOpen}
        >
          <svg
            className="a-saved-caret"
            width="11" height="11" viewBox="0 0 11 11"
            fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"
            style={{ transform: savedOpen ? "rotate(90deg)" : "rotate(0deg)" }}
          >
            <path d="M3.5 2L7 5.5L3.5 9" />
          </svg>
          <span className="a-section-title" style={{ fontSize: 14 }}>Saved jobs</span>
          <span className="a-results-count">{savedJobs.length} saved</span>
        </button>
        {savedOpen && (
          savedJobs.length ? (
            <div className="a-job-grid" style={{ marginTop: 10 }}>
              {savedJobs.map(renderTile)}
            </div>
          ) : (
            <div className="a-saved-empty">Nothing saved yet. Save matches to revisit them later.</div>
          )
        )}
      </div>

      <div className="a-results-head">
        <div className="a-section-title" style={{ fontSize: 14 }}>Matches</div>
        <div className="a-results-count">{matchJobs.length} results</div>
      </div>

      <div className="a-job-grid">
        {matchJobs.map(renderTile)}
      </div>
    </div>
  );
}

function JDTabA() {
  const M = window.MOCK.jd;
  return (
    <div className="rd-card">
      <div className="a-section-head">
        <div>
          <p className="rd-eyebrow">Step 03 · Job Description</p>
          <div className="a-section-title">{M.title}</div>
          <div className="a-section-sub">{M.company} · imported from Greenhouse</div>
        </div>
        <span className="rd-pip rd-pip-live">Parsed</span>
      </div>

      <div className="a-jd-grid">
        <div className="a-jd-input">
          <button className="rd-btn rd-btn-ghost rd-btn-sm" style={{ alignSelf: "flex-start" }}>
            <Icon.Upload /> Upload JD file
          </button>
          <textarea
            className="rd-textarea"
            defaultValue={M.summary}
          />
          <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
            <button className="rd-btn rd-btn-quiet rd-btn-sm">Clear</button>
            <button className="rd-btn rd-btn-ghost rd-btn-sm">Re-parse</button>
          </div>
        </div>

        <div className="a-jd-summary">
          <div className="a-jd-metrics">
            {M.metrics.map(m => (
              <div key={m.label} className="a-jd-metric">
                <div className="a-jd-metric-label">{m.label}</div>
                <div className="a-jd-metric-value">{m.value}<sup>{m.unit}</sup></div>
              </div>
            ))}
          </div>

          <div className="a-skills-block">
            <div className="a-skills-block-label">Hard skills · {M.hardSkills.length}</div>
            <div className="a-skills">{M.hardSkills.map(s => <span key={s} className="rd-chip rd-chip-skill">{s}</span>)}</div>
          </div>
          <div className="a-skills-block">
            <div className="a-skills-block-label">Soft skills</div>
            <div className="a-skills">{M.softSkills.map(s => <span key={s} className="rd-chip rd-chip-skill">{s}</span>)}</div>
          </div>

          <div>
            {M.sections.map(s => (
              <div key={s.title} className="a-jd-section">
                <h4>{s.title}</h4>
                <p>{s.body}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function AnalysisTabA({ artTab, setArtTab }) {
  const M = window.MOCK;
  const art = M.artifact[artTab === "resume" ? "resume" : "cover"];

  return (
    <>
      <div className="rd-card">
        <div className="a-section-head">
          <div>
            <p className="rd-eyebrow">Step 04 · Analysis</p>
            <div className="a-section-title">Tailored package</div>
            <div className="a-section-sub">AI-assisted run finished in 38s · 4 stages</div>
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <button className="rd-btn rd-btn-ghost rd-btn-sm">Re-run</button>
            <button className="rd-btn rd-btn-danger rd-btn-sm">Clear role</button>
          </div>
        </div>

        <div className="a-progress">
          {M.workflow.stages.map(s => (
            <div key={s.id} className="a-stage" data-state={s.value === 100 ? "done" : s.value > 0 ? "active" : "next"}>
              <div className="a-stage-name">{s.title} {s.value === 100 ? "✓" : ""}</div>
              <div className="a-stage-detail">{s.detail}</div>
              <div className="a-stage-bar"><span style={{ width: `${s.value}%` }} /></div>
            </div>
          ))}
        </div>
      </div>

      <div className="rd-card">
        <div className="a-artifact-tabs" role="tablist">
          <button className="a-artifact-tab" aria-selected={artTab === "resume"} onClick={() => setArtTab("resume")}>Tailored Resume</button>
          <button className="a-artifact-tab" aria-selected={artTab === "cover"} onClick={() => setArtTab("cover")}>Cover Letter</button>
        </div>

        <div className="a-artifact-body">
          <div className="a-artifact-preview">{art.preview}</div>

          <div className="a-artifact-aside">
            <h4>{art.title}</h4>
            <p>{art.summary}</p>
            <hr className="rd-hairline" style={{ margin: "8px 0" }} />
            <div className="a-artifact-actions">
              <button className="rd-btn rd-btn-primary rd-btn-sm">Download PDF</button>
              <button className="rd-btn rd-btn-ghost rd-btn-sm">Download Markdown</button>
              <button className="rd-btn rd-btn-quiet rd-btn-sm">Copy to clipboard</button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

window.DirectionA = DirectionA;
