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
