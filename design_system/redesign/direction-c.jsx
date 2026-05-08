// Direction C — Atmosphere
// Same 4-step structure as A, but with vivid SaaS/AI-product polish.

function DirectionC({ tab, setTab }) {
  return (
    <div className="c-root">
      <CTopBar />
      <div style={{ display: "grid", gridTemplateRows: "auto 1fr", overflow: "hidden" }}>
        <CProgress tab={tab} setTab={setTab} />
        <div className="c-main">
          {tab === "resume"   && <CResume />}
          {tab === "jobs"     && <CJobs />}
          {tab === "jd"       && <CJD />}
          {tab === "analysis" && <CAnalysis />}
        </div>
      </div>
    </div>
  );
}

function CTopBar() {
  return (
    <div className="c-topbar">
      <div className="c-brand">
        <div className="c-brand-mark"><img src="redesign/job-copilot-logo.png" alt="" /></div>
        <div className="c-brand-name">
          Job Application
          <small>Copilot</small>
        </div>
      </div>
      <div className="c-topbar-search">
        <Icon.Search />
        <span>Search jobs, resumes, or keywords…</span>
        <kbd>⌘ K</kbd>
      </div>
      <div className="c-topbar-meta">
        <span className="c-topbar-saved"><Icon.Check /> Saved 2m ago</span>
        <span className="c-topbar-quota">
          <span className="c-topbar-spark"><Icon.Sparkle /></span>
          <span>42 / 100 workflows</span>
          <span className="c-topbar-quota-bar"><span /></span>
        </span>
        <div className="c-avatar">LA</div>
      </div>
    </div>
  );
}

const STEPS = [
  { id: "resume",   num: 1, label: "Resume",     status: "done",   ready: "Ready"     },
  { id: "jobs",     num: 2, label: "Job Search", status: "done",   ready: "4 saved"   },
  { id: "jd",       num: 3, label: "JD Review",  status: "done",   ready: "Role loaded" },
  { id: "analysis", num: 4, label: "Analysis",   status: "active", ready: "AI ready"  },
];

function CProgress({ tab, setTab }) {
  return (
    <div className="c-progress">
      {STEPS.map(s => {
        const isActive = s.id === tab;
        const isDone = !isActive && s.status === "done";
        const cls = ["c-step", isActive && "c-step-active", isDone && "c-step-done"].filter(Boolean).join(" ");
        return (
          <button key={s.id} className={cls} onClick={() => setTab(s.id)}>
            <div className="c-step-num">{isDone ? <Icon.Check /> : s.num}</div>
            <div className="c-step-body">
              <div className="c-step-label">{s.label}</div>
              <div className="c-step-status">{s.ready}</div>
            </div>
          </button>
        );
      })}
    </div>
  );
}

// ============ ANALYSIS (hero + outputs) ============
function CAnalysis() {
  const jd = window.MOCK.jd;
  const outputs = [
    { id: "resume", icon: <Icon.Upload />,   name: "Tailored Resume",
      bullets: ["2 pages", "ATS optimized", "Skills matched"] },
    { id: "cover",  icon: <Icon.Send />,     name: "Cover Letter",
      bullets: ["Personalized", "Role-focused", "Company aligned"] },
    { id: "email",  icon: <Icon.External />, name: "Recruiter Email",
      bullets: ["Short & professional", "Highlights fit", "Call-to-action"] },
    { id: "prep",   icon: <Icon.Sparkle />,  name: "Interview Prep",
      bullets: ["Top topics", "Sample answers", "Tips & frameworks"] },
  ];

  return (
    <div className="c-twocol">
      <div>
        <div className="c-hero">
          <span className="c-hero-pill">Active Role</span>
          <h1 className="c-hero-title">{jd.title}</h1>
          <div className="c-hero-meta">
            <span>🏢 {jd.company}</span>
            <span>📍 San Francisco · Remote OK</span>
            <span>Source: <a href="#">LinkedIn</a></span>
            <span>Imported: May 18, 2025</span>
          </div>

          <div className="c-hero-banner">
            <div className="c-hero-banner-icon"><Icon.Sparkle /></div>
            <div className="c-hero-banner-text">
              <b>We've loaded the job and parsed the description.</b><br/>
              Review the details, run the AI workflow, and generate tailored materials.
            </div>
          </div>

          <div className="c-hero-actions">
            <button className="c-btn c-btn-primary"><Icon.Sparkle /> Run AI Workflow</button>
            <button className="c-btn"><Icon.Upload /> Upload Resume</button>
            <button className="c-btn"><Icon.External /> Import Job URL</button>
            <button className="c-btn"><Icon.Check /> Review JD</button>
          </div>
        </div>

        <div className="c-outputs">
          <div className="c-outputs-head">
            <div className="c-outputs-title">
              Generated Outputs
              <span className="c-outputs-count">{outputs.length}</span>
            </div>
            <div className="c-outputs-sub">All outputs are tailored to this role and JD.</div>
          </div>
          <div className="c-outputs-grid">
            {outputs.map(o => (
              <div key={o.id} className="c-output-card">
                <div className="c-output-head">
                  <div className="c-output-icon">{o.icon}</div>
                  <div className="c-output-name">{o.name}</div>
                  <span className="c-ready-badge">Ready <Icon.Check /></span>
                </div>
                <div className="c-output-preview">
                  Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.
                </div>
                <ul className="c-output-bullets">
                  {o.bullets.map(b => <li key={b}>{b}</li>)}
                </ul>
                <div className="c-output-foot">
                  <button className="c-output-action"><Icon.Upload /> Export PDF</button>
                  <button className="c-output-more">⋯</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <CRail />
    </div>
  );
}

// ============ ASSISTANT RAIL ============
function CRail() {
  const sugs = [
    { icon: <Icon.Upload />,  text: "Improve my resume for this role" },
    { icon: <Icon.Check />,   text: "What skills am I missing?" },
    { icon: <Icon.Sparkle />, text: "Generate interview questions" },
    { icon: <Icon.Send />,    text: "Write a recruiter email" },
  ];
  return (
    <aside className="c-rail">
      <div className="c-rail-head">
        <div className="c-rail-icon"><Icon.Sparkle /></div>
        <div className="c-rail-title">AI Assistant</div>
        <div className="c-rail-tools">
          <button title="Refresh">↻</button>
          <button title="More">⋯</button>
        </div>
      </div>

      <div className="c-rail-msg">
        <div className="c-rail-msg-avatar"><Icon.Sparkle /></div>
        <div className="c-rail-msg-bubble">
          Hi Leander! I'm your AI copilot. I can help you tailor your application materials, analyze the role, and prepare you for interviews.
          <small className="c-rail-msg-time">10:24 AM</small>
        </div>
      </div>
      <div className="c-rail-msg c-rail-msg-user">
        <div className="c-rail-msg-avatar">LA</div>
        <div className="c-rail-msg-bubble">
          What would you like to work on today?
          <small className="c-rail-msg-time">10:24 AM</small>
        </div>
      </div>

      <div className="c-rail-suggestions-label">Suggested prompts</div>
      {sugs.map(s => (
        <button key={s.text} className="c-rail-suggestion">
          <span className="c-rail-suggestion-icon">{s.icon}</span>
          <span>{s.text}</span>
          <span className="c-rail-suggestion-arrow">›</span>
        </button>
      ))}

      <div className="c-rail-input">
        <input placeholder="Ask anything about this application…" />
        <button className="c-rail-send" aria-label="Send"><Icon.Send /></button>
      </div>
      <div className="c-rail-foot">AI can make mistakes. Verify important info.</div>
    </aside>
  );
}

// ============ RESUME ============
function CResume() {
  const c = window.MOCK.candidate;
  return (
    <div>
      <div className="c-hero">
        <span className="c-hero-pill">Step 01 · Resume</span>
        <h1 className="c-hero-title">{c.name}</h1>
        <div className="c-hero-meta">
          <span>{c.title}</span>
          <span>📍 {c.location}</span>
          <span>3 roles · 12 skills detected</span>
        </div>
        <div className="c-hero-actions">
          <button className="c-btn c-btn-primary"><Icon.Upload /> Re-upload Resume</button>
          <button className="c-btn">Edit Builder</button>
        </div>
      </div>

      <div className="c-resume-twoup">
        <div className="c-section">
          <div className="c-section-head">
            <div className="c-section-title">Skills</div>
            <div className="c-section-sub">{c.skills.length} detected</div>
          </div>
          <div className="c-chips">
            {c.skills.map((s, i) => (
              <span key={s} className="c-chip" data-tone={i % 4 === 0 ? "bold" : null}>{s}</span>
            ))}
          </div>
        </div>
        <div className="c-section">
          <div className="c-section-head">
            <div className="c-section-title">Experience</div>
            <div className="c-section-sub">{c.experience.length} roles</div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {c.experience.map(e => (
              <div key={e.org} style={{
                padding: "10px 12px", borderRadius: 10,
                background: "var(--c-bg-elev)",
                border: "1px solid var(--c-border-soft)",
                display: "flex", justifyContent: "space-between", alignItems: "center",
              }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>{e.title}</div>
                  <div style={{ fontSize: 12, color: "var(--c-fg-3)" }}>{e.org}</div>
                </div>
                <div style={{ fontSize: 11.5, color: "var(--c-fg-3)" }}>{e.period}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="c-section">
        <div className="c-section-head">
          <div className="c-section-title">Parser signals</div>
          <div className="c-section-sub">Live read of your CV</div>
        </div>
        <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 8 }}>
          {c.signals.map(s => (
            <li key={s} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 12.5, color: "var(--c-fg-2)" }}>
              <span style={{
                width: 22, height: 22, borderRadius: 6, display: "grid", placeItems: "center",
                background: "color-mix(in oklch, var(--c-emerald) 20%, transparent)",
                color: "var(--c-emerald)",
              }}><Icon.Check /></span>
              {s}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

// ============ JOBS ============
function CJobs() {
  const jobs = window.MOCK.jobResults;
  return (
    <div>
      <div className="c-hero">
        <span className="c-hero-pill">Step 02 · Job Search</span>
        <h1 className="c-hero-title">Find your next role</h1>
        <div className="c-hero-meta">
          <span>{jobs.length} matches</span>
          <span>{jobs.filter(j => j.saved).length} saved</span>
          <span>Sources: LinkedIn · Greenhouse · Lever</span>
        </div>
        <div className="c-hero-actions">
          <button className="c-btn c-btn-primary"><Icon.Search /> Search</button>
          <button className="c-btn"><Icon.External /> Import Job URL</button>
        </div>
      </div>

      <div className="c-section">
        <div className="c-section-head">
          <div className="c-section-title">Matches</div>
          <div className="c-section-sub">Sorted by fit</div>
        </div>
        <div className="c-jobs">
          {jobs.map((j) => (
            <div key={j.id} className="c-job">
              <div className="c-job-head">
                <div className="c-job-title">{j.title}</div>
                <button className={`c-job-save ${j.saved ? "c-job-saved" : ""}`}>
                  <Icon.Pin /> {j.saved ? "Saved" : "Save"}
                </button>
              </div>
              <div className="c-job-meta">
                <b>{j.company}</b>
                <span>{j.location}</span>
                <span>{j.posted}</span>
              </div>
              <div className="c-job-summary">{j.summary}</div>
              <div className="c-job-foot">
                {j.badges.map(b => <span key={b} className="c-job-badge">{b}</span>)}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ============ JD ============
function CJD() {
  const jd = window.MOCK.jd;
  return (
    <div>
      <div className="c-hero">
        <span className="c-hero-pill">Step 03 · JD Review</span>
        <h1 className="c-hero-title">{jd.title}</h1>
        <div className="c-hero-meta">
          <span>🏢 {jd.company}</span>
          <span>San Francisco · Remote OK</span>
          <span>Source: LinkedIn</span>
        </div>
        <div className="c-metrics">
          {jd.metrics.map(m => (
            <div key={m.label} className="c-metric">
              <div className="c-metric-label">{m.label}</div>
              <div className="c-metric-value">{m.value}<span className="c-metric-unit">{m.unit}</span></div>
            </div>
          ))}
        </div>
      </div>

      <div className="c-section">
        <div className="c-section-head">
          <div className="c-section-title">Summary</div>
        </div>
        <p style={{ fontSize: 13, lineHeight: 1.6, color: "var(--c-fg-2)", margin: 0 }}>{jd.summary}</p>
      </div>

      <div className="c-resume-twoup">
        <div className="c-section">
          <div className="c-section-head">
            <div className="c-section-title">Hard skills</div>
            <div className="c-section-sub">{jd.hardSkills.length} required</div>
          </div>
          <div className="c-chips">
            {jd.hardSkills.map((s, i) => (
              <span key={s} className="c-chip" data-tone={i % 3 === 0 ? "bold" : null}>{s}</span>
            ))}
          </div>
        </div>
        <div className="c-section">
          <div className="c-section-head">
            <div className="c-section-title">Soft skills</div>
          </div>
          <div className="c-chips">
            {jd.softSkills.map(s => <span key={s} className="c-chip">{s}</span>)}
          </div>
        </div>
      </div>

      {jd.sections.map(s => (
        <div key={s.title} className="c-section">
          <div className="c-section-head">
            <div className="c-section-title">{s.title}</div>
          </div>
          <p style={{ fontSize: 13, lineHeight: 1.6, color: "var(--c-fg-2)", margin: 0 }}>{s.body}</p>
        </div>
      ))}
    </div>
  );
}

window.DirectionC = DirectionC;
