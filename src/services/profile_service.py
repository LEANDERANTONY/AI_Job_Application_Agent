from src.schemas import (
    CandidateProfile,
    EducationEntry,
    JobPreferences,
    LinkedInProfile,
    ResumeDocument,
    WorkExperience,
)


def build_candidate_profile_from_resume(resume_document):
    if not isinstance(resume_document, ResumeDocument):
        raise TypeError("resume_document must be a ResumeDocument instance.")
    return CandidateProfile(
        source=resume_document.source or "resume_upload",
        resume_text=resume_document.text,
    )


def build_candidate_profile_from_linkedin_data(payload):
    summary = payload.get("summary", {})
    experiences = [
        WorkExperience(
            title=item.get("title", ""),
            organization=item.get("company", ""),
            location=item.get("location", ""),
            description=item.get("description", ""),
            start=item.get("start"),
            end=item.get("end"),
        )
        for item in payload.get("experience", [])
    ]
    education = [
        EducationEntry(
            institution=item.get("school", ""),
            degree=item.get("degree", ""),
            field_of_study=item.get("field", ""),
            start=item.get("start", ""),
            end=item.get("end", ""),
        )
        for item in payload.get("education", [])
    ]
    preferences = payload.get("preferences", {})
    linkedin_profile = LinkedInProfile(
        full_name=summary.get("name", ""),
        headline=summary.get("headline", ""),
        location=summary.get("location", ""),
        summary=summary.get("summary", ""),
        skills=payload.get("skills", []),
        experience=experiences,
        education=education,
        certifications=payload.get("certifications", []),
        projects=payload.get("projects", []),
        publications=payload.get("publications", []),
        preferences=JobPreferences(
            preferred_titles=[str(preferences.get("Preferred Title"))]
            if preferences.get("Preferred Title")
            else [],
            raw_preferences=preferences,
        ),
    )
    return CandidateProfile(
        full_name=linkedin_profile.full_name,
        location=linkedin_profile.location,
        source="linkedin_export",
        linkedin_profile=linkedin_profile,
        skills=linkedin_profile.skills,
        experience=linkedin_profile.experience,
        education=linkedin_profile.education,
        certifications=linkedin_profile.certifications,
    )

