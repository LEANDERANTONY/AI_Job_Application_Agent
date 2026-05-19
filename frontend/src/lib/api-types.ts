export type BackendHealth = {
  status: string;
  service: string;
  version: string;
  frontend_url?: string;
  health_url?: string;
  providers: {
    greenhouse: {
      configured: boolean;
      board_count: number;
    };
    lever: {
      configured: boolean;
      site_count: number;
    };
  };
};

/** Canonical work-mode values the backend accepts on the dropdown
 *  filter. Anything outside this union gets dropped server-side, so
 *  keep this in sync with `_ALLOWED_WORK_MODES` in cached_jobs_store.py. */
export type WorkMode = "remote" | "hybrid" | "onsite";

/** Canonical employment-type values. Mirrors `_ALLOWED_EMPLOYMENT_TYPES`
 *  in cached_jobs_store.py — derived from the `employment_type_norm`
 *  generated column on cached_jobs. */
export type EmploymentType =
  | "fulltime"
  | "parttime"
  | "contract"
  | "internship"
  | "temporary";

/** Sort key sent to the search_cached_jobs_ranked RPC. Unknown values
 *  coerce to "relevance" both client- and server-side. */
export type JobSortBy = "relevance" | "newest" | "oldest" | "company_az";

export type JobSearchRequest = {
  query: string;
  location?: string;
  source_filters?: string[];
  remote_only?: boolean;
  posted_within_days?: number | null;
  page_size?: number;
  /** Pagination window start for "Load more" (0 / omitted = first
   *  page). Threaded into the search_cached_jobs_ranked RPC's
   *  p_offset; the live fan-out path applies it as a post-dedupe
   *  slice. Server clamps to [0, 100000]. */
  offset?: number;
  /** Multi-select dropdown. Empty / omitted = no filter applied. */
  work_modes?: WorkMode[];
  /** Multi-select dropdown. Empty / omitted = no filter applied. */
  employment_types?: EmploymentType[];
  /** Single-select sort. Defaults to "relevance" when omitted. */
  sort_by?: JobSortBy;
};

export type JobPosting = {
  id: string;
  source: string;
  title: string;
  company: string;
  location: string;
  employment_type: string;
  url: string;
  summary: string;
  description_text: string;
  posted_at: string;
  scraped_at: string;
  metadata: Record<string, unknown>;
  saved_at?: string;
  updated_at?: string;
  /** True when the upstream board (Greenhouse / Lever) is still
   *  returning this listing in its periodic refresh. False when the
   *  listing was tombstoned by the cache-cleanup pass — the job is
   *  no longer accepting applications. Optional + defaults to true
   *  on the frontend so old responses (before this field landed) and
   *  jobs from sources we don't cache stay rendered as active. */
  is_listing_active?: boolean;
};

export type JobSearchResponse = {
  query: JobSearchRequest;
  results: JobPosting[];
  total_results: number;
  /** True when this page came back full (results.length === page_size)
   *  → there is (probably) at least one more page. Drives the
   *  "Load more" CTA. Optional so responses predating the field
   *  (and the live-path fallback) degrade to "no more pages". */
  has_more?: boolean;
  source_status: Record<string, string>;
};

export type JobResolveResponse = {
  source: string;
  status: string;
  job_posting: JobPosting | null;
  error_message: string;
  source_details: Record<string, string>;
};

// Tokens live in HttpOnly cookies. Frontend never reads or sends them
// directly. This type is retained only as a marker for the response
// shape of /auth/session/restore, which still echoes
// `session: { authenticated: true }` so callers can distinguish a
// success payload from a sign-in prompt.
export type AuthSessionMarker = {
  authenticated: boolean;
};

export type AuthUser = {
  user_id: string;
  email: string;
  display_name: string;
  avatar_url: string;
};

export type EducationEntry = {
  institution: string;
  degree: string;
  field_of_study: string;
  start: string;
  end: string;
};

export type WorkExperience = {
  title: string;
  organization: string;
  location: string;
  description: string;
  start: string | null;
  end: string | null;
};

export type CandidateProfile = {
  full_name: string;
  location: string;
  contact_lines: string[];
  source: string;
  resume_text: string;
  skills: string[];
  experience: WorkExperience[];
  education: EducationEntry[];
  certifications: string[];
  source_signals: string[];
};

export type AppUserRecord = {
  id: string;
  email: string;
  display_name: string;
  avatar_url: string;
  created_at: string;
  last_seen_at: string;
  plan_tier: string;
  account_status: string;
};

export type ResumeDocument = {
  text: string;
  filetype: string;
  source: string;
};

export type JobRequirements = {
  hard_skills: string[];
  soft_skills: string[];
  experience_requirement: string | null;
  must_haves: string[];
  nice_to_haves: string[];
};

export type JobDescription = {
  title: string;
  raw_text: string;
  cleaned_text: string;
  location: string | null;
  salary: string | null;
  requirements: JobRequirements;
};

export type FitAnalysis = {
  target_role: string;
  overall_score: number;
  readiness_label: string;
  matched_hard_skills: string[];
  missing_hard_skills: string[];
  matched_soft_skills: string[];
  missing_soft_skills: string[];
  experience_signal: string;
  strengths: string[];
  gaps: string[];
  recommendations: string[];
};

export type TailoredResumeDraft = {
  target_role: string;
  professional_summary: string;
  highlighted_skills: string[];
  priority_bullets: string[];
  gap_mitigation_steps: string[];
};

export type JobSummarySection = {
  title: string;
  items: string[];
};

export type JobSummaryView = {
  headline: string;
  summary: string;
  sections: JobSummarySection[];
  fit_signals: string[];
  interview_focus: string[];
};

export type ProfileAgentOutput = {
  positioning_headline: string;
  evidence_highlights: string[];
  strengths: string[];
  cautions: string[];
};

export type JobAgentOutput = {
  requirement_summary: string;
  priority_skills: string[];
  must_have_themes: string[];
  messaging_guidance: string[];
};

export type TailoringAgentOutput = {
  professional_summary: string;
  rewritten_bullets: string[];
  highlighted_skills: string[];
  cover_letter_themes: string[];
};

export type StrategyAgentOutput = {
  recruiter_positioning: string;
  cover_letter_talking_points: string[];
  portfolio_project_emphasis: string[];
};

export type ReviewAgentOutput = {
  approved: boolean;
  grounding_issues: string[];
  unresolved_issues: string[];
  revision_requests: string[];
  final_notes: string[];
  corrected_tailoring: TailoringAgentOutput | null;
  corrected_strategy: StrategyAgentOutput | null;
};

export type AgentWorkflowResult = {
  mode: string;
  model: string;
  tailoring: TailoringAgentOutput;
  review: ReviewAgentOutput;
  profile: ProfileAgentOutput;
  job: JobAgentOutput;
  strategy: StrategyAgentOutput | null;
  attempted_assisted: boolean;
  fallback_reason: string;
  fallback_details: string;
};

export type CoverLetterArtifact = {
  title: string;
  filename_stem: string;
  summary: string;
  markdown: string;
  plain_text: string;
};

export type ResumeHeader = {
  full_name: string;
  location: string;
  contact_lines: string[];
};

export type ResumeExperienceEntry = {
  title: string;
  organization: string;
  location: string;
  start: string;
  end: string;
  bullets: string[];
};

export type TailoredResumeArtifact = {
  title: string;
  filename_stem: string;
  summary: string;
  markdown: string;
  plain_text: string;
  theme: string;
  header: ResumeHeader;
  target_role: string;
  professional_summary: string;
  highlighted_skills: string[];
  experience_entries: ResumeExperienceEntry[];
  education_entries: EducationEntry[];
  certifications: string[];
  /** Canonical section ids in render order: 'summary', 'skills',
   *  'experience', 'projects', 'education', 'publications',
   *  'certifications'. Backend picks per-profile (students lead with
   *  Education + Projects; academics with Publications; seniors with
   *  Experience). Empty list = render with backend's default order. */
  section_order: string[];
  change_log: string[];
  validation_notes: string[];
};

/** Honest "an LLM stage degraded because OpenAI was down" notice.
 *  Present + `unavailable: true` ONLY for a genuine provider outage
 *  (not content degradation), so the surface can show a cause-
 *  accurate "try again shortly" banner instead of silently shipping
 *  a worse result. Mirrors `workflow.service_unavailable` /
 *  `fallback_reason` for the standalone résumé-upload step (which has
 *  no `workflow`). Null/absent when the stage was healthy. */
export type ServiceNotice = {
  unavailable: boolean;
  category: string;
  message: string;
};

export type WorkspaceResumeUploadResponse = {
  resume_document: ResumeDocument;
  candidate_profile: CandidateProfile;
  service_notice?: ServiceNotice | null;
};

export type ResumeBuilderDraftProfile = {
  full_name: string;
  location: string;
  contact_lines: string[];
  target_role: string;
  professional_summary: string;
  experience_notes: string;
  education_notes: string;
  skills: string[];
  certifications: string[];
  /** Optional — free-form prose describing side projects / portfolio
   *  pieces. Captured verbatim by the LLM intake; the structuring
   *  pass converts it into ProjectEntry objects on the artifact. */
  projects_notes: string;
  /** Optional — list of publication / paper / talk citation strings.
   *  Like certifications: each item is a single line of citation
   *  text, no further structuring. */
  publications: string[];
};

export type ResumeBuilderPersistenceStatus =
  | "saved"
  | "skipped"
  | "unauthenticated";

export type ResumeBuilderSessionResponse = {
  session_id: string;
  status: string;
  current_step: string;
  completed_steps: number;
  total_steps: number;
  progress_percent: number;
  assistant_message: string;
  draft_profile: ResumeBuilderDraftProfile;
  generated_resume_markdown: string;
  generated_resume_plain_text: string;
  ready_to_generate: boolean;
  ready_to_commit: boolean;
  /** Outcome of the Supabase upsert that the route ran after the
   *  service mutation. Optional because /resume-builder/latest
   *  doesn't include it (a session loaded from latest is implicitly
   *  saved if it exists). */
  persistence_status?: ResumeBuilderPersistenceStatus;
  /** ISO timestamp at which the persisted draft will be GC'd by the
   *  Supabase cron (cleanup-expired-resume-builder-sessions) and
   *  hidden by RLS. Only present when persistence_status === 'saved';
   *  the TTL refreshes on every save so an active user keeps their
   *  draft alive. */
  expires_at?: string;
  resume_document?: ResumeDocument;
  candidate_profile?: CandidateProfile;
};

export type LoadResumeBuilderSessionResponse = {
  status: string;
  session: ResumeBuilderSessionResponse | null;
};

export type ResumeBuilderCommitResponse = {
  resume_document: ResumeDocument;
  candidate_profile: CandidateProfile;
  generated_resume_markdown: string;
  generated_resume_plain_text: string;
  builder_session_id: string;
};

/** Phase 5 of the DOCX export plan: download the resume builder's
 *  generated base resume as PDF or DOCX. Mirrors the shape of
 *  `WorkspaceArtifactExportResponse` so the same `downloadBase64File`
 *  helper handles both surfaces. */
export type ResumeBuilderExportResponse = {
  status: string;
  export_format: WorkspaceArtifactExportFormat;
  file_name: string;
  mime_type: string;
  content_base64: string;
  theme: ArtifactTheme;
  artifact_title: string;
};

export type WorkspaceJobDescriptionUploadResponse = {
  job_description_text: string;
  job_description: JobDescription;
  jd_summary_view: JobSummaryView;
};

export type WorkspaceWorkflow = {
  mode: string;
  assisted_requested: boolean;
  assisted_available: boolean;
  review_approved: boolean;
  fallback_reason: string;
  /** True only when the run downgraded to deterministic because the
   *  AI provider (OpenAI) was unreachable — NOT for content
   *  degradation. Drives the honest outage banner. Optional so
   *  responses predating the field (and the saved-workspace restore
   *  path) safely read as "not an outage". */
  service_unavailable?: boolean;
};

export type WorkspaceArtifacts = {
  tailored_resume: TailoredResumeArtifact;
  cover_letter: CoverLetterArtifact;
};

export type WorkspaceAnalysisResponse = {
  resume_document: ResumeDocument;
  candidate_profile: CandidateProfile;
  job_description: JobDescription;
  jd_summary_view: JobSummaryView;
  fit_analysis: FitAnalysis;
  tailored_draft: TailoredResumeDraft;
  agent_result: AgentWorkflowResult | null;
  artifacts: WorkspaceArtifacts;
  workflow: WorkspaceWorkflow;
  imported_job_posting?: JobPosting | null;
};

export type WorkspaceAnalysisJobCreatedResponse = {
  job_id: string;
  status: string;
  stage_title: string | null;
  stage_detail: string | null;
  progress_percent: number;
};

export type WorkspaceAnalysisJobStatusResponse = {
  job_id: string;
  status: string;
  stage_title: string | null;
  stage_detail: string | null;
  progress_percent: number;
  result: WorkspaceAnalysisResponse | null;
  error_message: string | null;
};

export type WorkspaceAssistantResponse = {
  answer: string;
  sources: string[];
  suggested_follow_ups: string[];
};

// Server-Sent Events emitted by `POST /api/workspace/assistant/answer/stream`.
// Order on the happy path: meta -> delta* -> done.
// Order on failure: error -> done. The frontend treats either `done`
// or `error` as terminal and stops reading the stream.
//
// A `followups` event used to sit between the last `delta` and `done`,
// but the suggested-follow-up UI was removed (commit 9138ead) and the
// event became dead code on both ends. Re-add the event type if/when
// the panel is reintroduced.
export type AssistantStreamMetaEvent = {
  type: "meta";
  sources: string[];
};

export type AssistantStreamDeltaEvent = {
  type: "delta";
  text: string;
};

export type AssistantStreamDoneEvent = {
  type: "done";
};

export type AssistantStreamErrorEvent = {
  type: "error";
  detail: string;
};

export type AssistantStreamEvent =
  | AssistantStreamMetaEvent
  | AssistantStreamDeltaEvent
  | AssistantStreamDoneEvent
  | AssistantStreamErrorEvent;

export type WorkspaceAssistantHistoryTurn = {
  question: string;
  answer: string;
};

export type UploadedFilePayload = {
  filename: string;
  mime_type: string;
  content_base64: string;
};

export type WorkspaceAnalysisRequest = {
  resume_text: string;
  resume_filetype: string;
  resume_source: string;
  job_description_text: string;
  imported_job_posting?: JobPosting | null;
  run_assisted: boolean;
  /** Opt-in per-run premium routing (Step 7a). When true AND the
   *  user's tier supports it (Pro+), the workflow agents route to
   *  gpt-5.5 for review / resume_generation / cover_letter and the
   *  request burns a `premium_applications` credit. Free tier with
   *  premium=true is rejected at the gate with a 429 + "Pro+ only"
   *  message; the toggle is disabled for Free in the UI so this
   *  combination shouldn't occur on the happy path. Optional so
   *  existing callers keep working without an explicit field. */
  premium?: boolean;
};

/** Per-counter snapshot returned by GET /workspace/quota.
 *  `limit === -1` is the UNLIMITED sentinel — render as "Unlimited"
 *  pill instead of a number. `remaining === -1` mirrors the same.
 *  `reset_period`:
 *    - "monthly"    — resets on the 1st of next month UTC
 *    - "lifetime"   — Free-tier resume_builder_sessions only; never resets
 *    - "persistent" — row-count quota (saved_jobs, saved_workspaces);
 *                     decreases when the user explicitly deletes a row */
export type WorkspaceQuotaCounter = {
  current: number;
  limit: number;
  remaining: number;
  reset_period: "monthly" | "lifetime" | "persistent";
};

/** Full /workspace/quota response. Drives the Premium toggle's
 *  enabled/disabled state, the per-counter indicators, and the
 *  upgrade CTA URL. Counter keys match `backend.tiers.TIER_CAPS`. */
export type WorkspaceQuotaResponse = {
  tier: "free" | "pro" | "business";
  counters: {
    tailored_applications: WorkspaceQuotaCounter;
    premium_applications: WorkspaceQuotaCounter;
    resume_builder_sessions: WorkspaceQuotaCounter;
    assistant_turns: WorkspaceQuotaCounter;
    resume_parses: WorkspaceQuotaCounter;
    job_searches: WorkspaceQuotaCounter;
    saved_jobs: WorkspaceQuotaCounter;
    saved_workspaces: WorkspaceQuotaCounter;
  };
  /** True when the tier's premium_applications cap is non-zero —
   *  drives the Premium toggle's enabled/disabled state. Free → false,
   *  Pro/Business → true. */
  premium_available: boolean;
  /** First-of-month UTC date in YYYY-MM-DD; UI uses this for
   *  "resets on X" copy. */
  period_start: string;
  /** Upgrade page URL; the 429 toast and the disabled-toggle tooltip
   *  both deep-link here. */
  upgrade_url: string;
};

/** Structured 429 body returned by the global QuotaExceededError
 *  handler. Frontend's fetch wrapper parses this and surfaces a
 *  toast with an "Upgrade" CTA rather than the generic error path. */
export type TierLimitExceededPayload = {
  detail: string;
  code: "tier_limit_exceeded";
  counter: string;
  current: number;
  cap: number;
  reset_period: string;
  tier: "free" | "pro" | "business";
};

/**
 * Compact projection of the live workspace state, sent on every
 * assistant query so the LLM can answer state-aware questions
 * ("what should I do next?", "is my resume parsed?", "why is
 * analysis locked?") even before the full `workspace_snapshot`
 * exists.
 *
 * Intentionally small — name + counts + booleans, no resume text or
 * full JD body. The full snapshot still rides separately when an
 * analysis has run; this object covers the pre-analysis gap.
 */
export type WorkspaceStateContext = {
  /** Which step the user is currently looking at. */
  current_step: "resume" | "jobs" | "jd" | "analysis";
  /** Has a CandidateProfile been parsed from the user's resume? */
  has_resume: boolean;
  /** Small projection of the parsed resume — null until parsed.
   *  `experience_entries_count` is the number of work-experience
   *  *entries* on the resume (e.g. 4 jobs held), NOT years of total
   *  experience. The earlier name `experience_count` led the model
   *  to answer "how many years?" with the entry count. */
  resume_summary: {
    name: string;
    location: string;
    skills_count: number;
    experience_entries_count: number;
    has_certifications: boolean;
  } | null;
  /** Has the user pasted/imported a JD that's been at least
   *  scaffolded into a JobDescription? */
  has_jd: boolean;
  /** Small projection of the parsed JD — null until present. */
  jd_summary: {
    title: string;
    location: string | null;
    hard_skills_count: number;
    soft_skills_count: number;
    must_haves_count: number;
  } | null;
  /** True once an analysis has run and produced a fit score. */
  has_analysis: boolean;
  /** How many jobs the user has saved to their shortlist. */
  saved_jobs_count: number;
  /** What they last typed in the search box, if anything. */
  last_search_query: string | null;
};

export type WorkspaceAssistantRequest = {
  question: string;
  current_page: string;
  workspace_state?: WorkspaceStateContext | null;
  workspace_snapshot?: WorkspaceAnalysisResponse | null;
  history?: WorkspaceAssistantHistoryTurn[];
};

export type WorkspaceArtifactKind =
  | "tailored_resume"
  | "cover_letter";

// DOCX replaced the markdown download in Phase 2 of the DOCX export
// plan. PDF stays for printable copies.
export type WorkspaceArtifactExportFormat = "pdf" | "docx";

/** Each artifact has its own theme so the user can pick a different
 *  treatment for the resume vs the cover letter (e.g. classic_ats for
 *  the resume on a startup application but professional_neutral for the
 *  cover letter on a bank application). */
export type ArtifactTheme =
  | "classic_ats"
  | "professional_neutral"
  | "modern_blue"
  | "creative_warm"
  | "architect_mono"
  | "presentation_twocol";

export type WorkspaceArtifactExportRequest = {
  workspace_snapshot: WorkspaceAnalysisResponse;
  artifact_kind: WorkspaceArtifactKind;
  export_format: WorkspaceArtifactExportFormat;
  resume_theme?: ArtifactTheme;
  cover_letter_theme?: ArtifactTheme;
};

export type WorkspaceArtifactExportResponse = {
  status: string;
  artifact_kind: WorkspaceArtifactKind;
  export_format: WorkspaceArtifactExportFormat;
  file_name: string;
  mime_type: string;
  content_base64: string;
  resume_theme: string;
  cover_letter_theme: string;
  artifact_title: string;
};

export type WorkspaceArtifactPreviewRequest = {
  workspace_snapshot: WorkspaceAnalysisResponse;
  artifact_kind: WorkspaceArtifactKind;
  resume_theme?: ArtifactTheme;
  cover_letter_theme?: ArtifactTheme;
};

export type WorkspaceArtifactPreviewResponse = {
  status: string;
  artifact_kind: WorkspaceArtifactKind;
  resume_theme: string;
  cover_letter_theme: string;
  artifact_title: string;
  html: string;
};

export type DailyQuotaStatus = {
  user_id: string;
  plan_tier: string;
  request_count: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  max_calls: number | null;
  max_total_tokens: number | null;
  remaining_calls: number | null;
  remaining_total_tokens: number | null;
  quota_exhausted: boolean;
  window_start: string;
  window_end: string;
};

export type AuthFeatures = {
  saved_workspace_enabled: boolean;
  saved_jobs_enabled: boolean;
  usage_tracking_enabled: boolean;
  assisted_workflow_requires_login: boolean;
};

export type AuthSessionResponse = {
  authenticated: boolean;
  session: AuthSessionMarker | null;
  user: AuthUser;
  app_user: AppUserRecord;
  daily_quota: DailyQuotaStatus | null;
  features: AuthFeatures;
};

export type GoogleSignInStartResponse = {
  url: string;
  auth_flow: string;
  redirect_url: string;
};

export type WorkspaceHandoffStartResponse = {
  status: string;
  redirect_url: string;
};

export type SavedWorkspaceMeta = {
  job_title: string;
  expires_at: string;
  updated_at: string;
};

export type SaveWorkspaceResponse = {
  status: string;
  saved_workspace: SavedWorkspaceMeta;
};

export type LoadSavedWorkspaceResponse = {
  status: string;
  saved_workspace: SavedWorkspaceMeta | null;
  workspace_snapshot?: WorkspaceAnalysisResponse;
};

export type SavedJobsResponse = {
  status: string;
  saved_jobs: JobPosting[];
  total_saved_jobs: number;
  latest_saved_at: string;
};

export type SaveSavedJobResponse = {
  status: string;
  saved_job: JobPosting;
  message: string;
};

export type RemoveSavedJobResponse = {
  status: string;
  job_id: string;
};

/**
 * Online feedback surfaces. Mirrors the CHECK constraint on
 * `aijobagent_feedback.surface` (see docs/sql/supabase-feedback.sql)
 * so a typo at the call site fails at compile time instead of
 * bouncing off the Postgres check.
 */
export type FeedbackSurface =
  | "tailored_resume"
  | "cover_letter"
  | "jd_summary"
  | "assistant_turn"
  | "resume_builder_session";

export type FeedbackRequest = {
  surface: FeedbackSurface;
  rating: "up" | "down";
  trace_id?: string | null;
  comment?: string;
};

export type FeedbackResponse = {
  status: "recorded";
  surface: FeedbackSurface;
  rating: "up" | "down";
};
