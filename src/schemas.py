from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class EducationEntry:
    institution: str
    degree: str = ""
    field_of_study: str = ""
    start: str = ""
    end: str = ""


@dataclass
class WorkExperience:
    title: str
    organization: str
    location: str = ""
    description: str = ""
    start: Any = None
    end: Any = None


@dataclass
class CandidateProfile:
    full_name: str = ""
    location: str = ""
    source: str = ""
    resume_text: str = ""
    skills: List[str] = field(default_factory=list)
    experience: List[WorkExperience] = field(default_factory=list)
    education: List[EducationEntry] = field(default_factory=list)
    certifications: List[str] = field(default_factory=list)
    source_signals: List[str] = field(default_factory=list)


@dataclass
class ResumeDocument:
    text: str
    filetype: str
    source: str = ""


@dataclass
class ResumeHeader:
    full_name: str = ""
    location: str = ""
    contact_lines: List[str] = field(default_factory=list)


@dataclass
class ResumeExperienceEntry:
    title: str
    organization: str = ""
    location: str = ""
    start: str = ""
    end: str = ""
    bullets: List[str] = field(default_factory=list)


@dataclass
class JobRequirements:
    hard_skills: List[str] = field(default_factory=list)
    soft_skills: List[str] = field(default_factory=list)
    experience_requirement: Optional[str] = None
    must_haves: List[str] = field(default_factory=list)
    nice_to_haves: List[str] = field(default_factory=list)


@dataclass
class JobDescription:
    title: str
    raw_text: str
    cleaned_text: str
    location: Optional[str] = None
    requirements: JobRequirements = field(default_factory=JobRequirements)


@dataclass
class FitAnalysis:
    target_role: str
    overall_score: int
    readiness_label: str
    matched_hard_skills: List[str] = field(default_factory=list)
    missing_hard_skills: List[str] = field(default_factory=list)
    matched_soft_skills: List[str] = field(default_factory=list)
    missing_soft_skills: List[str] = field(default_factory=list)
    experience_signal: str = ""
    strengths: List[str] = field(default_factory=list)
    gaps: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


@dataclass
class TailoredResumeDraft:
    target_role: str
    professional_summary: str
    highlighted_skills: List[str] = field(default_factory=list)
    priority_bullets: List[str] = field(default_factory=list)
    gap_mitigation_steps: List[str] = field(default_factory=list)


@dataclass
class ProfileAgentOutput:
    positioning_headline: str
    evidence_highlights: List[str] = field(default_factory=list)
    strengths: List[str] = field(default_factory=list)
    cautions: List[str] = field(default_factory=list)


@dataclass
class JobAgentOutput:
    requirement_summary: str
    priority_skills: List[str] = field(default_factory=list)
    must_have_themes: List[str] = field(default_factory=list)
    messaging_guidance: List[str] = field(default_factory=list)


@dataclass
class FitAgentOutput:
    fit_summary: str
    top_matches: List[str] = field(default_factory=list)
    key_gaps: List[str] = field(default_factory=list)
    interview_themes: List[str] = field(default_factory=list)


@dataclass
class TailoringAgentOutput:
    professional_summary: str
    rewritten_bullets: List[str] = field(default_factory=list)
    highlighted_skills: List[str] = field(default_factory=list)
    cover_letter_themes: List[str] = field(default_factory=list)


@dataclass
class StrategyAgentOutput:
    recruiter_positioning: str
    cover_letter_talking_points: List[str] = field(default_factory=list)
    interview_preparation_themes: List[str] = field(default_factory=list)
    portfolio_project_emphasis: List[str] = field(default_factory=list)


@dataclass
class ResumeGenerationAgentOutput:
    professional_summary: str
    highlighted_skills: List[str] = field(default_factory=list)
    experience_bullets: List[str] = field(default_factory=list)
    section_order: List[str] = field(default_factory=list)
    template_hint: str = "classic_ats"


@dataclass
class ReviewAgentOutput:
    approved: bool
    grounding_issues: List[str] = field(default_factory=list)
    revision_requests: List[str] = field(default_factory=list)
    final_notes: List[str] = field(default_factory=list)


@dataclass
class ReviewPassResult:
    pass_index: int
    tailoring: TailoringAgentOutput
    strategy: StrategyAgentOutput
    review: ReviewAgentOutput


@dataclass
class AgentWorkflowResult:
    mode: str
    model: str
    profile: ProfileAgentOutput
    job: JobAgentOutput
    fit: FitAgentOutput
    tailoring: TailoringAgentOutput
    review: ReviewAgentOutput
    strategy: Optional[StrategyAgentOutput] = None
    resume_generation: Optional[ResumeGenerationAgentOutput] = None
    review_history: List[ReviewPassResult] = field(default_factory=list)
    attempted_assisted: bool = False
    fallback_reason: str = ""
    fallback_details: str = ""


@dataclass
class ApplicationReport:
    title: str
    filename_stem: str
    summary: str
    markdown: str
    plain_text: str


@dataclass
class TailoredResumeArtifact:
    title: str
    filename_stem: str
    summary: str
    markdown: str
    plain_text: str
    theme: str = "classic_ats"
    header: ResumeHeader = field(default_factory=ResumeHeader)
    target_role: str = ""
    professional_summary: str = ""
    highlighted_skills: List[str] = field(default_factory=list)
    experience_entries: List[ResumeExperienceEntry] = field(default_factory=list)
    education_entries: List[EducationEntry] = field(default_factory=list)
    certifications: List[str] = field(default_factory=list)
    change_log: List[str] = field(default_factory=list)
    validation_notes: List[str] = field(default_factory=list)


@dataclass
class AssistantResponse:
    answer: str
    sources: List[str] = field(default_factory=list)
    suggested_follow_ups: List[str] = field(default_factory=list)


@dataclass
class AssistantTurn:
    mode: str
    question: str
    response: AssistantResponse


@dataclass
class AppUserRecord:
    id: str
    email: str = ""
    display_name: str = ""
    avatar_url: str = ""
    created_at: str = ""
    last_seen_at: str = ""
    plan_tier: str = "free"
    account_status: str = "active"


@dataclass
class UsageEventRecord:
    user_id: str
    task_name: str = ""
    model_name: str = ""
    request_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    response_id: str = ""
    status: str = ""
    created_at: str = ""


@dataclass
class DailyQuotaStatus:
    user_id: str
    plan_tier: str = "free"
    request_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    max_calls: Optional[int] = None
    max_total_tokens: Optional[int] = None
    remaining_calls: Optional[int] = None
    remaining_total_tokens: Optional[int] = None
    quota_exhausted: bool = False
    window_start: str = ""
    window_end: str = ""


@dataclass
class SavedWorkflowSnapshot:
    candidate_profile: CandidateProfile
    job_description: JobDescription
    fit_analysis: FitAnalysis
    tailored_draft: TailoredResumeDraft
    agent_result: Optional[AgentWorkflowResult] = None


@dataclass
class SavedWorkspaceRecord:
    user_id: str
    job_title: str = ""
    workflow_signature: str = ""
    workflow_snapshot_json: str = ""
    report_payload_json: str = ""
    tailored_resume_payload_json: str = ""
    expires_at: str = ""
    updated_at: str = ""
