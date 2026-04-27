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

export type JobSearchRequest = {
  query: string;
  location?: string;
  source_filters?: string[];
  remote_only?: boolean;
  posted_within_days?: number | null;
  page_size?: number;
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
};

export type JobSearchResponse = {
  query: JobSearchRequest;
  results: JobPosting[];
  total_results: number;
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

export type FitAgentOutput = {
  fit_summary: string;
  top_matches: string[];
  key_gaps: string[];
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
  fit: FitAgentOutput;
  tailoring: TailoringAgentOutput;
  review: ReviewAgentOutput;
  profile: ProfileAgentOutput;
  job: JobAgentOutput;
  strategy: StrategyAgentOutput | null;
  attempted_assisted: boolean;
  fallback_reason: string;
  fallback_details: string;
};

export type ReportArtifact = {
  title: string;
  filename_stem: string;
  summary: string;
  markdown: string;
  plain_text: string;
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
  change_log: string[];
  validation_notes: string[];
};

export type WorkspaceResumeUploadResponse = {
  resume_document: ResumeDocument;
  candidate_profile: CandidateProfile;
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
};

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
};

export type WorkspaceArtifacts = {
  tailored_resume: TailoredResumeArtifact;
  cover_letter: CoverLetterArtifact;
  report: ReportArtifact;
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
};

export type WorkspaceAssistantRequest = {
  question: string;
  current_page: string;
  workspace_snapshot?: WorkspaceAnalysisResponse | null;
  history?: WorkspaceAssistantHistoryTurn[];
};

export type WorkspaceArtifactKind =
  | "tailored_resume"
  | "cover_letter"
  | "report"
  | "bundle";

export type WorkspaceArtifactExportFormat = "markdown" | "pdf" | "zip";

export type WorkspaceArtifactExportRequest = {
  workspace_snapshot: WorkspaceAnalysisResponse;
  artifact_kind: WorkspaceArtifactKind;
  export_format: WorkspaceArtifactExportFormat;
  resume_theme?: string;
};

export type WorkspaceArtifactExportResponse = {
  status: string;
  artifact_kind: WorkspaceArtifactKind;
  export_format: WorkspaceArtifactExportFormat;
  file_name: string;
  mime_type: string;
  content_base64: string;
  resume_theme: string;
  artifact_title: string;
};

export type WorkspaceArtifactPreviewRequest = {
  workspace_snapshot: WorkspaceAnalysisResponse;
  artifact_kind: Exclude<WorkspaceArtifactKind, "bundle">;
  resume_theme?: string;
};

export type WorkspaceArtifactPreviewResponse = {
  status: string;
  artifact_kind: Exclude<WorkspaceArtifactKind, "bundle">;
  resume_theme: string;
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
