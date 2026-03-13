from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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
class JobPreferences:
    preferred_titles: List[str] = field(default_factory=list)
    raw_preferences: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LinkedInProfile:
    full_name: str
    headline: str = ""
    location: str = ""
    summary: str = ""
    skills: List[str] = field(default_factory=list)
    experience: List[WorkExperience] = field(default_factory=list)
    education: List[EducationEntry] = field(default_factory=list)
    certifications: List[str] = field(default_factory=list)
    projects: List[Dict[str, Any]] = field(default_factory=list)
    publications: List[Dict[str, Any]] = field(default_factory=list)
    preferences: JobPreferences = field(default_factory=JobPreferences)


@dataclass
class CandidateProfile:
    full_name: str = ""
    location: str = ""
    source: str = ""
    resume_text: str = ""
    linkedin_profile: Optional[LinkedInProfile] = None
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
class ReviewAgentOutput:
    approved: bool
    grounding_issues: List[str] = field(default_factory=list)
    revision_requests: List[str] = field(default_factory=list)
    final_notes: List[str] = field(default_factory=list)


@dataclass
class AgentWorkflowResult:
    mode: str
    model: str
    profile: ProfileAgentOutput
    job: JobAgentOutput
    fit: FitAgentOutput
    tailoring: TailoringAgentOutput
    review: ReviewAgentOutput


@dataclass
class ApplicationReport:
    title: str
    filename_stem: str
    summary: str
    markdown: str
    plain_text: str
