"use client";

// Resume intake (upload + guided builder) — Direction B redesign.
//
// Behavior preservation:
//   - Drag/picker upload → onResumeUpload
//   - "Build with assistant" toggle → load/start builder session
//   - Edit-in-place draft fields → onBuilderDraftSave
//   - Generated resume preview + commit → onBuilderCommit
//   - Last-upload metadata + clear-uploaded-resume button retained
//
// Layout (per handoff specs/01-resume.md):
//   1. b-intake-panel — header (eyebrow + title + mode toggle), body
//      switches between upload dropzone and builder Q&A
//   2. b-resume-hero — parsed-profile hero (name, title, meta dots)
//   3. b-resume-twoup — Skills + Experience side-by-side
//   4. b-twoup-section — Parser signals row

import {
  useEffect,
  useRef,
  type ChangeEvent,
  type Dispatch,
  type SetStateAction,
  type TextareaHTMLAttributes,
} from "react";

import {
  CheckIcon,
  UploadIcon,
} from "@/components/workspace/icons";
import { CollapsibleSection } from "@/components/workspace/CollapsibleSection";

// Auto-grow textarea — sizes itself to fit the current value so the
// draft profile no longer crams long answers into a tiny scroll-stuck
// box. Re-measures whenever the value changes.
type AutoTextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement>;

function AutoTextarea({ value, ...rest }: AutoTextareaProps) {
  const ref = useRef<HTMLTextAreaElement | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight + 2}px`;
  }, [value]);
  return <textarea ref={ref} value={value} {...rest} />;
}
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

function noticeClassName(level: ResumeIntakeNotice["level"]) {
  if (level === "success") return "b-notice b-notice-success";
  if (level === "warning") return "b-notice b-notice-warning";
  return "b-notice";
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

  const profileFileLabel =
    selectedResumeFile?.name ||
    resumeState?.resume_document.filetype ||
    null;

  return (
    <div className="b-region">
      {/* 1 — Intake panel: upload OR guided builder */}
      <div className="b-intake-panel">
        <div className="b-intake-head">
          <div>
            <div className="b-section-label">Step 01 · Import resume</div>
            <div className="b-intake-title">Bring in your resume</div>
          </div>
          <div className="b-intake-modes">
            <button
              className="b-intake-mode"
              data-active={mode === "upload"}
              onClick={() => onModeChange("upload")}
              type="button"
            >
              Upload
            </button>
            <button
              className="b-intake-mode"
              data-active={mode === "assistant"}
              onClick={() => {
                onModeChange("assistant");
                onResetBuilderInitialized();
              }}
              type="button"
            >
              Build with assistant
            </button>
          </div>
        </div>

        {mode === "upload" ? (
          <>
            <input
              accept=".pdf,.docx,.txt"
              id="resume-upload"
              onChange={handleFileInputChange}
              style={{ display: "none" }}
              type="file"
            />
            {currentProfile ? (
              // Parsed state — collapse the dropzone to a compact "Last
              // upload" row + Re-upload / Clear actions. Frees up the
              // canvas for the parsed-profile hero, two-up, and
              // signals.
              <div className="b-intake-compact">
                <div className="b-intake-compact-meta">
                  <span className="b-section-label">Last upload</span>
                  {profileFileLabel ? (
                    <span
                      className="rd-mono"
                      style={{ color: "var(--fg)", fontSize: 13 }}
                    >
                      {profileFileLabel}
                    </span>
                  ) : null}
                </div>
                <div className="b-intake-compact-actions">
                  {resumeUploading ? (
                    <span style={{ fontSize: 12.5, color: "var(--fg-3)" }}>
                      Parsing resume…
                    </span>
                  ) : null}
                  <label
                    className="rd-btn rd-btn-ghost rd-btn-sm"
                    htmlFor="resume-upload"
                  >
                    <UploadIcon /> Re-upload
                  </label>
                  <button
                    className="rd-btn rd-btn-danger rd-btn-sm"
                    onClick={onClearUploadedResumeProfile}
                    type="button"
                  >
                    Clear
                  </button>
                </div>
              </div>
            ) : (
              <>
                <div className="b-drop">
                  <span className="b-drop-icon">
                    <UploadIcon />
                  </span>
                  <div className="b-drop-title">Drop your resume here</div>
                  <div className="b-drop-sub">PDF, DOCX or TXT · Up to 5MB</div>
                  <label
                    className="rd-btn rd-btn-ghost rd-btn-sm"
                    htmlFor="resume-upload"
                    style={{ marginTop: 12 }}
                  >
                    Choose file
                  </label>
                  {profileFileLabel ? (
                    <div className="b-drop-meta">
                      Last upload:{" "}
                      <span className="rd-mono" style={{ color: "var(--fg-2)" }}>
                        {profileFileLabel}
                      </span>
                    </div>
                  ) : null}
                </div>

                <div className="b-intake-status-row">
                  {resumeUploading ? <span>Parsing resume…</span> : null}
                </div>
              </>
            )}

            {resumeNotice ? (
              <div
                className={noticeClassName(resumeNotice.level)}
                style={{ marginTop: 12 }}
              >
                {resumeNotice.message}
              </div>
            ) : null}
          </>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <p style={{ fontSize: 13, color: "var(--fg-2)", lineHeight: 1.65 }}>
              The guided builder asks short, focused questions and turns your
              answers into a clean base resume.
            </p>

            {authSignedIn ? (
              <p style={{ fontSize: 12, color: "var(--fg-3)" }}>
                Your latest draft will reopen here automatically when available.
              </p>
            ) : null}

            {builderSession ? (
              <div className="b-builder-steps">
                {BUILDER_STEP_KEYS.map((key) => {
                  const label = RESUME_BUILDER_STEP_LABELS[key];
                  const isActive = builderSession.current_step === key;
                  const isComplete =
                    key !== "review" &&
                    builderSession.completed_steps >
                      BUILDER_STEP_KEYS.indexOf(key);
                  return (
                    <div
                      className="b-builder-step"
                      data-active={isActive || undefined}
                      data-done={isComplete && !isActive ? true : undefined}
                      key={key}
                    >
                      <span>{label}</span>
                      <span className="b-builder-step-status">
                        {isComplete && !isActive
                          ? "DONE"
                          : isActive
                            ? "ACTIVE"
                            : "—"}
                      </span>
                    </div>
                  );
                })}
              </div>
            ) : null}

            <div
              style={{
                display: "flex",
                gap: 8,
                alignItems: "center",
                justifyContent: "space-between",
              }}
            >
              <div
                className="b-section-label"
                style={{ textTransform: "uppercase" }}
              >
                {builderStepLabel}
              </div>
              <button
                className="rd-btn rd-btn-ghost rd-btn-sm"
                onClick={onToggleBuilderCollapsed}
                type="button"
              >
                {builderCollapsed ? "Show builder" : "Hide builder"}
              </button>
            </div>

            {!builderCollapsed ? (
              <>
                <p
                  style={{
                    fontSize: 13,
                    color: "var(--fg-2)",
                    lineHeight: 1.65,
                  }}
                >
                  {builderSession?.assistant_message ||
                    "The guided assistant will ask a few focused questions and turn your answers into a base resume."}
                </p>

                {builderNotice ? (
                  <div className={noticeClassName(builderNotice.level)}>
                    {builderNotice.message}
                  </div>
                ) : null}

                {!builderSession && builderLoading ? (
                  <div className="b-twoup-empty">
                    Starting the guided resume builder…
                  </div>
                ) : null}

                {builderSession && !builderSession.ready_to_generate ? (
                  <>
                    <textarea
                      className="rd-textarea"
                      onChange={(event) =>
                        onBuilderAnswerChange(event.target.value)
                      }
                      placeholder="Type your answer here. Keep it natural — the assistant will structure it for you."
                      value={builderAnswer}
                    />
                    <div>
                      <button
                        className="rd-btn rd-btn-primary rd-btn-sm"
                        disabled={builderLoading}
                        onClick={onBuilderAnswerSubmit}
                        type="button"
                      >
                        {builderLoading ? "Saving…" : "Continue"}
                      </button>
                    </div>
                  </>
                ) : null}

                {builderSession?.ready_to_generate &&
                !builderSession.generated_resume_markdown ? (
                  <div>
                    <button
                      className="rd-btn rd-btn-primary rd-btn-sm"
                      disabled={builderGenerating}
                      onClick={onBuilderGenerate}
                      type="button"
                    >
                      {builderGenerating
                        ? "Generating…"
                        : "Generate base resume"}
                    </button>
                  </div>
                ) : null}

                {builderSession?.generated_resume_markdown ? (
                  <div>
                    <button
                      className="rd-btn rd-btn-primary rd-btn-sm"
                      disabled={builderCommitting}
                      onClick={onBuilderCommit}
                      type="button"
                    >
                      {builderCommitting
                        ? "Using profile…"
                        : "Use this profile"}
                    </button>
                  </div>
                ) : null}
              </>
            ) : (
              <p style={{ fontSize: 12.5, color: "var(--fg-3)" }}>
                The assistant is hidden for now. You can reopen it anytime to
                continue answering questions.
              </p>
            )}

            {builderSession ? (
              <div
                className="b-builder-preview-card"
                style={{ marginTop: 0 }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "baseline",
                    marginBottom: 12,
                  }}
                >
                  <div className="b-twoup-title">Draft profile</div>
                  <span className="b-twoup-sub">
                    Progress · {builderSession.progress_percent}%
                  </span>
                </div>

                {/* Draft fields grouped into the same five sections the
                    wizard itself walks through, each independently
                    collapsible. Textareas auto-grow to fit content so a
                    long experience or summary doesn't get crammed into
                    a 70px scroll-stuck box. Defaults open. */}
                {(() => {
                  const renderInput = (key: DraftFieldKey, label: string, placeholder?: string) => (
                    <label className="b-builder-field" key={key}>
                      <span className="b-builder-field-label">{label}</span>
                      <input
                        className="rd-input"
                        onChange={(event) => setDraftField(key, event.target.value)}
                        placeholder={placeholder}
                        value={builderDraftForm[key]}
                      />
                    </label>
                  );
                  const renderTextarea = (
                    key: DraftFieldKey,
                    label: string,
                    placeholder?: string,
                  ) => (
                    <label
                      className="b-builder-field b-builder-field-wide"
                      key={key}
                    >
                      <span className="b-builder-field-label">{label}</span>
                      <AutoTextarea
                        className="rd-textarea b-builder-textarea-grow"
                        onChange={(event) => setDraftField(key, event.target.value)}
                        placeholder={placeholder}
                        value={builderDraftForm[key]}
                      />
                    </label>
                  );

                  return (
                    <>
                      <CollapsibleSection sub="Name, location, contact lines" title="Basics">
                        <div className="b-builder-form">
                          {renderInput("full_name", "Full name")}
                          {renderInput("location", "Location")}
                          {renderTextarea(
                            "contact_lines",
                            "Contact lines",
                            "One line per item: email, phone, LinkedIn, GitHub…",
                          )}
                        </div>
                      </CollapsibleSection>

                      <CollapsibleSection sub="What you're aiming at" title="Target role">
                        <div className="b-builder-form">
                          {renderInput("target_role", "Target role")}
                          {renderTextarea("professional_summary", "Summary")}
                        </div>
                      </CollapsibleSection>

                      <CollapsibleSection sub="Roles, impact, dates" title="Experience">
                        <div className="b-builder-form">
                          {renderTextarea("experience_notes", "Experience notes")}
                        </div>
                      </CollapsibleSection>

                      <CollapsibleSection sub="Degrees, programs" title="Education">
                        <div className="b-builder-form">
                          {renderTextarea("education_notes", "Education")}
                        </div>
                      </CollapsibleSection>

                      <CollapsibleSection
                        sub="Tools + certifications"
                        title="Skills"
                      >
                        <div className="b-builder-form">
                          {renderInput(
                            "skills",
                            "Skills",
                            "Python, FastAPI, Docker, SQL",
                          )}
                          {renderInput(
                            "certifications",
                            "Certifications",
                            "Optional",
                          )}
                        </div>
                      </CollapsibleSection>
                    </>
                  );
                })()}

                <div style={{ marginTop: 12 }}>
                  <button
                    className="rd-btn rd-btn-ghost rd-btn-sm"
                    disabled={builderEditing}
                    onClick={onBuilderDraftSave}
                    type="button"
                  >
                    {builderEditing ? "Saving edits…" : "Save draft edits"}
                  </button>
                </div>

                {builderSession.generated_resume_markdown ? (
                  <pre className="b-builder-preview">
                    {builderSession.generated_resume_markdown}
                  </pre>
                ) : (
                  <div
                    className="b-twoup-empty"
                    style={{ marginTop: 12 }}
                  >
                    Your base resume preview will appear here once the guided
                    intake is complete.
                  </div>
                )}
              </div>
            ) : null}
          </div>
        )}
      </div>

      {/* 2 — Parsed profile hero (only after upload) */}
      {currentProfile ? (
        <div className="b-resume-hero">
          <div className="b-resume-hero-head">
            <div>
              <span className="b-resume-hero-pill">Parsed profile</span>
              <h1 className="b-resume-hero-title">
                {currentProfile.full_name?.trim() ||
                  "Profile in progress"}
              </h1>
              {!currentProfile.full_name?.trim() ? (
                <p
                  style={{
                    fontSize: 13,
                    color: "var(--fg-3)",
                    margin: "4px 0 0",
                    lineHeight: 1.55,
                  }}
                >
                  We couldn&apos;t infer a name from your inputs. Edit the
                  Full name field on the draft profile so the rest of the
                  workflow uses the right header.
                </p>
              ) : null}
              <div className="b-resume-hero-meta">
                <span>
                  {currentProfile.experience?.[0]?.title || "Role pending"}
                </span>
                {currentProfile.location ? (
                  <span>{currentProfile.location}</span>
                ) : null}
                <span>
                  {currentProfile.experience.length} role
                  {currentProfile.experience.length === 1 ? "" : "s"} ·{" "}
                  {currentProfile.skills.length} skill
                  {currentProfile.skills.length === 1 ? "" : "s"} detected
                </span>
                {profileFileLabel ? (
                  <span>
                    <span className="rd-mono" style={{ color: "var(--fg-2)" }}>
                      {profileFileLabel}
                    </span>
                  </span>
                ) : null}
              </div>
            </div>
            <button
              className="rd-btn rd-btn-ghost rd-btn-sm"
              onClick={onClearUploadedResumeProfile}
              type="button"
            >
              Re-upload
            </button>
          </div>
        </div>
      ) : null}

      {/* 3 — Skills (full-width, collapsible) — stacked vertically with
          Experience below. Stacked rather than two-up so a long
          resume's experience list doesn't overshoot the much-shorter
          skills column, and so the layout reads naturally on phones.
          Collapsible so phone users can fold a section closed and
          scroll past it quickly. */}
      {currentProfile ? (
        <CollapsibleSection
          sub={`${currentProfile.skills.length} detected`}
          title="Skills"
        >
          {currentProfile.skills.length ? (
            <div className="b-skill-chips">
              {currentProfile.skills.map((skill, index) => (
                <span
                  className="b-skill-chip"
                  data-tone={index % 4 === 0 ? "bold" : undefined}
                  key={skill}
                >
                  {skill}
                </span>
              ))}
            </div>
          ) : (
            <div className="b-twoup-empty">
              Skills will surface once the parser settles.
            </div>
          )}
        </CollapsibleSection>
      ) : null}

      {currentProfile ? (
        <CollapsibleSection
          sub={`${currentProfile.experience.length} role${currentProfile.experience.length === 1 ? "" : "s"}`}
          title="Experience"
        >
          {currentProfile.experience.length ? (
            <div className="b-twoup-body">
              {currentProfile.experience.map((entry, index) => (
                <div
                  className="b-experience-card"
                  key={`${entry.organization}-${entry.title}-${index}`}
                >
                  <div>
                    <div className="b-experience-title">
                      {entry.title || "Role title pending"}
                    </div>
                    <div className="b-experience-org">
                      {entry.organization || "Organisation pending"}
                    </div>
                  </div>
                  <div className="b-experience-period">
                    {entry.start || "—"}
                    {" — "}
                    {entry.end || "Now"}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="b-twoup-empty">
              Experience entries will populate after the parser runs.
            </div>
          )}
        </CollapsibleSection>
      ) : null}

      {/* 4 — "What we found" — user-friendlier name for the parser
          signals row. Same data, friendlier label. */}
      {currentProfile && currentProfile.source_signals.length ? (
        <CollapsibleSection
          sub="Quick read of your resume"
          title="What we found"
        >
          <ul className="b-signal-list">
            {currentProfile.source_signals.slice(0, 6).map((signal) => (
              <li className="b-signal-item" key={signal}>
                <span className="b-signal-icon">
                  <CheckIcon />
                </span>
                {signal}
              </li>
            ))}
          </ul>
        </CollapsibleSection>
      ) : null}

      {/* Empty-state placeholder shown when nothing has been parsed yet
          so the canvas isn't a tall black void below the intake card. */}
      {!currentProfile && mode === "upload" ? (
        <div className="b-empty-hint">
          <div className="b-empty-hint-eyebrow">Once parsed</div>
          <div className="b-empty-hint-body">
            Your candidate profile, skills, experience timeline, and a
            quick read of what we found will appear right here.
          </div>
        </div>
      ) : null}
    </div>
  );
}
