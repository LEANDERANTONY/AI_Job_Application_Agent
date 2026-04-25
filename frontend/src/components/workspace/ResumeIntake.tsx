"use client";

// Resume intake (upload + guided builder) — extracted from
// `job-application-workspace.tsx` as part of the Item 2 frontend split
// (see `docs/NEXT-STEPS-FRONTEND.md`).
//
// Two modes share this surface:
//   - "upload": file picker + parsed candidate snapshot.
//   - "assistant": guided builder Q&A + draft-profile editor.
// State stays in the parent for now and is passed as props; the lift
// to a Zustand `resumeIntake` slice is a separate task (#13).

import type { ChangeEvent, Dispatch, SetStateAction } from "react";

import type {
  CandidateProfile,
  ResumeBuilderSessionResponse,
  WorkspaceResumeUploadResponse,
} from "@/lib/api-types";

export type ResumeIntakeMode = "upload" | "assistant";

export type ResumeIntakeNotice = {
  level: "info" | "success" | "warning";
  message: string;
};

export type ResumeBuilderDraftForm = {
  full_name: string;
  location: string;
  contact_lines: string;
  target_role: string;
  professional_summary: string;
  experience_notes: string;
  education_notes: string;
  skills: string;
  certifications: string;
};

const RESUME_BUILDER_STEP_LABELS: Record<string, string> = {
  basics: "Basics",
  role: "Target role",
  experience: "Experience",
  education: "Education",
  skills: "Skills",
  review: "Review",
};

const BUILDER_STEP_KEYS = Object.keys(RESUME_BUILDER_STEP_LABELS);

type DraftFieldKey = keyof ResumeBuilderDraftForm;

type DraftFieldConfig = {
  key: DraftFieldKey;
  label: string;
  kind: "input" | "textarea";
  wide?: boolean;
  placeholder?: string;
};

const DRAFT_FIELDS: DraftFieldConfig[] = [
  { key: "full_name", label: "Full name", kind: "input" },
  { key: "location", label: "Location", kind: "input" },
  { key: "target_role", label: "Target role", kind: "input" },
  {
    key: "contact_lines",
    label: "Contact lines",
    kind: "textarea",
    wide: true,
    placeholder: "One line per item: email, phone, LinkedIn, GitHub...",
  },
  {
    key: "professional_summary",
    label: "Summary",
    kind: "textarea",
    wide: true,
  },
  {
    key: "experience_notes",
    label: "Experience notes",
    kind: "textarea",
    wide: true,
  },
  { key: "education_notes", label: "Education", kind: "textarea", wide: true },
  {
    key: "skills",
    label: "Skills",
    kind: "input",
    placeholder: "Python, FastAPI, Docker, SQL",
  },
  {
    key: "certifications",
    label: "Certifications",
    kind: "input",
    placeholder: "Optional",
  },
];

function noticeClassName(level: ResumeIntakeNotice["level"]) {
  if (level === "success") return "notice-panel notice-success";
  if (level === "warning") return "notice-panel notice-warning";
  return "notice-panel notice-info";
}

export type ResumeIntakeProps = {
  mode: ResumeIntakeMode;
  onModeChange: (mode: ResumeIntakeMode) => void;
  onResetBuilderInitialized: () => void;

  // Upload mode
  selectedResumeFile: File | null;
  onSelectedResumeFileChange: (file: File | null) => void;
  onResumeUpload: (file: File | null) => void;
  resumeUploading: boolean;
  resumeState: WorkspaceResumeUploadResponse | null;
  resumeNotice: ResumeIntakeNotice | null;
  currentProfile: CandidateProfile | null;
  onClearUploadedResumeProfile: () => void;

  // Builder mode
  authSignedIn: boolean;
  builderSession: ResumeBuilderSessionResponse | null;
  builderCollapsed: boolean;
  onToggleBuilderCollapsed: () => void;
  builderAnswer: string;
  onBuilderAnswerChange: (value: string) => void;
  builderNotice: ResumeIntakeNotice | null;
  builderLoading: boolean;
  builderGenerating: boolean;
  builderCommitting: boolean;
  builderEditing: boolean;
  builderDraftForm: ResumeBuilderDraftForm;
  setBuilderDraftForm: Dispatch<SetStateAction<ResumeBuilderDraftForm>>;
  onBuilderAnswerSubmit: () => void;
  onBuilderGenerate: () => void;
  onBuilderCommit: () => void;
  onBuilderDraftSave: () => void;
};

export function ResumeIntake({
  mode,
  onModeChange,
  onResetBuilderInitialized,
  selectedResumeFile,
  onSelectedResumeFileChange,
  onResumeUpload,
  resumeUploading,
  resumeState,
  resumeNotice,
  currentProfile,
  onClearUploadedResumeProfile,
  authSignedIn,
  builderSession,
  builderCollapsed,
  onToggleBuilderCollapsed,
  builderAnswer,
  onBuilderAnswerChange,
  builderNotice,
  builderLoading,
  builderGenerating,
  builderCommitting,
  builderEditing,
  builderDraftForm,
  setBuilderDraftForm,
  onBuilderAnswerSubmit,
  onBuilderGenerate,
  onBuilderCommit,
  onBuilderDraftSave,
}: ResumeIntakeProps) {
  const builderStepLabel = builderSession
    ? RESUME_BUILDER_STEP_LABELS[builderSession.current_step] ??
      "Resume builder"
    : "Resume builder";

  function handleFileInputChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    onSelectedResumeFileChange(file);
    onResumeUpload(file);
    event.target.value = "";
  }

  function setDraftField(key: DraftFieldKey, value: string) {
    setBuilderDraftForm((current) => ({ ...current, [key]: value }));
  }

  return (
    <section className="workspace-section-stack">
      <article className="surface-card surface-card-neutral">
        <div className="section-head">
          <div>
            <p className="eyebrow">Step 1</p>
            <h2 className="section-title">Resume intake</h2>
          </div>
          <span className="status-chip">
            {resumeState ? "Ready" : "Start here"}
          </span>
        </div>
        <p className="section-copy">
          Bring in an existing resume or build a base one with the assistant.
        </p>

        <div className="workspace-tab-row">
          {(["upload", "assistant"] as ResumeIntakeMode[]).map((value) => (
            <button
              className={
                mode === value
                  ? "inspector-tab inspector-tab-active"
                  : "inspector-tab"
              }
              key={value}
              onClick={() => {
                onModeChange(value);
                if (value === "assistant") {
                  onResetBuilderInitialized();
                }
              }}
              type="button"
            >
              {value === "upload" ? "Upload Resume" : "Build With Assistant"}
            </button>
          ))}
        </div>

        {mode === "upload" ? (
          <>
            <div className="workspace-uploader">
              <label
                className="primary-button workspace-button workspace-upload-trigger"
                htmlFor="resume-upload"
              >
                Upload resume
              </label>
              <input
                accept=".pdf,.docx,.txt"
                className="workspace-hidden-input"
                id="resume-upload"
                onChange={handleFileInputChange}
                type="file"
              />
              <span className="workspace-file-name">
                {selectedResumeFile?.name ||
                  resumeState?.resume_document.filetype ||
                  "No resume selected"}
              </span>
              {resumeUploading ? (
                <span className="workspace-file-status">
                  Parsing resume...
                </span>
              ) : null}
              {currentProfile ? (
                <button
                  className="danger-button workspace-button workspace-action-end"
                  onClick={onClearUploadedResumeProfile}
                  type="button"
                >
                  Clear uploaded resume
                </button>
              ) : null}
            </div>

            {resumeNotice ? (
              <div className={noticeClassName(resumeNotice.level)}>
                {resumeNotice.message}
              </div>
            ) : null}
          </>
        ) : (
          <div className="workspace-builder-stack">
            <div className="workspace-section-card">
              <div className="section-head">
                <div>
                  <span className="workspace-label">
                    Resume builder assistant
                  </span>
                  <h3>{builderStepLabel}</h3>
                </div>
                <button
                  className="secondary-button workspace-button workspace-button-small"
                  onClick={onToggleBuilderCollapsed}
                  type="button"
                >
                  {builderCollapsed ? "Show builder" : "Hide builder"}
                </button>
              </div>

              {!builderCollapsed ? (
                <>
                  <p className="workspace-role-copy">
                    {builderSession?.assistant_message ||
                      "The guided assistant will ask a few focused questions and turn your answers into a base resume."}
                  </p>

                  {authSignedIn ? (
                    <p className="workspace-muted-copy">
                      Your latest draft will reopen here automatically when
                      available.
                    </p>
                  ) : null}

                  {builderSession ? (
                    <div className="workspace-chip-grid">
                      {BUILDER_STEP_KEYS.map((key) => {
                        const label = RESUME_BUILDER_STEP_LABELS[key];
                        const isActive = builderSession.current_step === key;
                        const isComplete =
                          key !== "review" &&
                          builderSession.completed_steps >
                            BUILDER_STEP_KEYS.indexOf(key);
                        return (
                          <span
                            className={
                              isActive
                                ? "workspace-meta-chip workspace-builder-chip-active"
                                : "workspace-meta-chip"
                            }
                            key={key}
                          >
                            {label}
                            {isComplete && !isActive ? " - Done" : ""}
                          </span>
                        );
                      })}
                    </div>
                  ) : null}

                  {builderNotice ? (
                    <div className={noticeClassName(builderNotice.level)}>
                      {builderNotice.message}
                    </div>
                  ) : null}

                  {!builderSession && builderLoading ? (
                    <div className="workspace-empty-state">
                      Starting the guided resume builder...
                    </div>
                  ) : null}

                  {builderSession && !builderSession.ready_to_generate ? (
                    <div className="workspace-form-stack">
                      <textarea
                        className="workspace-textarea workspace-builder-answer"
                        onChange={(event) =>
                          onBuilderAnswerChange(event.target.value)
                        }
                        placeholder="Type your answer here. Keep it natural - the assistant will structure it for you."
                        value={builderAnswer}
                      />
                      <div className="workspace-run-actions">
                        <button
                          className="primary-button workspace-button"
                          disabled={builderLoading}
                          onClick={onBuilderAnswerSubmit}
                          type="button"
                        >
                          {builderLoading ? "Saving..." : "Continue"}
                        </button>
                      </div>
                    </div>
                  ) : null}

                  {builderSession?.ready_to_generate &&
                  !builderSession.generated_resume_markdown ? (
                    <div className="workspace-run-actions">
                      <button
                        className="primary-button workspace-button"
                        disabled={builderGenerating}
                        onClick={onBuilderGenerate}
                        type="button"
                      >
                        {builderGenerating
                          ? "Generating..."
                          : "Generate Base Resume"}
                      </button>
                    </div>
                  ) : null}

                  {builderSession?.generated_resume_markdown ? (
                    <div className="workspace-run-actions">
                      <button
                        className="primary-button workspace-button"
                        disabled={builderCommitting}
                        onClick={onBuilderCommit}
                        type="button"
                      >
                        {builderCommitting
                          ? "Using profile..."
                          : "Use This Profile"}
                      </button>
                    </div>
                  ) : null}
                </>
              ) : (
                <p className="workspace-muted-copy workspace-builder-collapsed-copy">
                  The assistant is hidden for now. You can reopen it anytime to
                  continue answering questions.
                </p>
              )}
            </div>

            <div className="workspace-section-card">
              <span className="workspace-label">Draft profile</span>
              <h3>
                {builderSession?.draft_profile.full_name ||
                  "Your base resume will build here"}
              </h3>
              <p className="workspace-role-copy">
                {builderSession?.generated_resume_markdown
                  ? "Review the generated base resume before moving it into the workspace."
                  : "As you answer each prompt, the assistant will collect the details needed to create a clean starting resume."}
              </p>

              {builderSession ? (
                <>
                  <div className="workspace-summary-grid">
                    <div className="metric-tile">
                      <span>Target role</span>
                      <strong>
                        {builderSession.draft_profile.target_role ||
                          "Still collecting"}
                      </strong>
                      <small>
                        The role direction you want this base resume to
                        support.
                      </small>
                    </div>
                    <div className="metric-tile">
                      <span>Skills</span>
                      <strong>{builderSession.draft_profile.skills.length}</strong>
                      <small>Skills or tools confirmed so far.</small>
                    </div>
                    <div className="metric-tile">
                      <span>Progress</span>
                      <strong>{builderSession.progress_percent}%</strong>
                      <small>
                        {builderSession.status === "ready"
                          ? "Base resume generated."
                          : "Guided intake in progress."}
                      </small>
                    </div>
                  </div>

                  <div className="workspace-review-columns">
                    <div className="soft-panel">
                      <span className="soft-panel-label">Contact</span>
                      <ul className="workspace-feature-list workspace-feature-list-compact">
                        {builderSession.draft_profile.contact_lines.length ? (
                          builderSession.draft_profile.contact_lines.map(
                            (line) => <li key={line}>{line}</li>,
                          )
                        ) : (
                          <li>
                            Add your email, phone, and links in the basics
                            step.
                          </li>
                        )}
                      </ul>
                    </div>
                    <div className="soft-panel">
                      <span className="soft-panel-label">Skills</span>
                      <div className="workspace-chip-grid">
                        {builderSession.draft_profile.skills.length ? (
                          builderSession.draft_profile.skills.map((skill) => (
                            <span className="workspace-meta-chip" key={skill}>
                              {skill}
                            </span>
                          ))
                        ) : (
                          <p className="workspace-muted-copy">
                            Skills will appear here once you reach that step.
                          </p>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="workspace-form-stack workspace-builder-edit-grid">
                    {DRAFT_FIELDS.map((field) => (
                      <label
                        className={
                          field.wide
                            ? "workspace-field workspace-builder-field-wide"
                            : "workspace-field"
                        }
                        key={field.key}
                      >
                        <span className="workspace-label">{field.label}</span>
                        {field.kind === "input" ? (
                          <input
                            className="workspace-input"
                            onChange={(event) =>
                              setDraftField(field.key, event.target.value)
                            }
                            placeholder={field.placeholder}
                            value={builderDraftForm[field.key]}
                          />
                        ) : (
                          <textarea
                            className="workspace-textarea workspace-builder-compact-textarea"
                            onChange={(event) =>
                              setDraftField(field.key, event.target.value)
                            }
                            placeholder={field.placeholder}
                            value={builderDraftForm[field.key]}
                          />
                        )}
                      </label>
                    ))}
                  </div>

                  <div className="workspace-run-actions">
                    <button
                      className="secondary-button workspace-button"
                      disabled={builderEditing}
                      onClick={onBuilderDraftSave}
                      type="button"
                    >
                      {builderEditing ? "Saving edits..." : "Save Draft Edits"}
                    </button>
                  </div>

                  {builderSession.generated_resume_markdown ? (
                    <div className="workspace-section-card workspace-builder-preview-card">
                      <span className="workspace-label">
                        Base resume preview
                      </span>
                      <pre className="workspace-builder-preview">
                        {builderSession.generated_resume_markdown}
                      </pre>
                    </div>
                  ) : (
                    <div className="workspace-empty-state workspace-empty-state-compact">
                      Your base resume preview will appear here once the guided
                      intake is complete.
                    </div>
                  )}
                </>
              ) : (
                <div className="workspace-empty-state workspace-empty-state-compact">
                  Switch to the assistant lane to start building a resume from
                  scratch.
                </div>
              )}
            </div>
          </div>
        )}

        {mode === "upload" && currentProfile ? (
          <>
            <div className="workspace-summary-grid">
              <div className="metric-tile">
                <span>Candidate</span>
                <strong>
                  {currentProfile.full_name || "Name not inferred"}
                </strong>
                <small>
                  {currentProfile.location || "Location not inferred"}
                </small>
              </div>
              <div className="metric-tile">
                <span>Skills</span>
                <strong>{currentProfile.skills.length}</strong>
                <small>Matched skill signals from the parsed resume.</small>
              </div>
              <div className="metric-tile">
                <span>Experience Entries</span>
                <strong>{currentProfile.experience.length}</strong>
                <small>
                  Structured roles or project entries available for reuse.
                </small>
              </div>
            </div>

            <div className="workspace-review-columns">
              <div className="soft-panel">
                <span className="soft-panel-label">Top skills</span>
                <div className="workspace-chip-grid">
                  {currentProfile.skills.slice(0, 10).map((skill) => (
                    <span className="workspace-meta-chip" key={skill}>
                      {skill}
                    </span>
                  ))}
                </div>
              </div>
              <div className="soft-panel">
                <span className="soft-panel-label">Resume signals</span>
                <ul className="workspace-feature-list workspace-feature-list-compact">
                  {currentProfile.source_signals.slice(0, 4).map((signal) => (
                    <li key={signal}>{signal}</li>
                  ))}
                </ul>
              </div>
            </div>

            <div className="workspace-next-step-note">
              You can proceed to Job Search if you want help finding roles, or
              move to the JD section if you already have a job description
              ready.
            </div>
          </>
        ) : mode === "upload" ? (
          <div className="workspace-empty-state">
            Your parsed candidate snapshot will appear here after the upload
            finishes.
          </div>
        ) : null}
      </article>
    </section>
  );
}
