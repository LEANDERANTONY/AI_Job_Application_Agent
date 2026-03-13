from src.parsers.jd import clean_text, extract_job_details
from src.schemas import JobDescription, JobRequirements


def build_job_description_from_text(raw_text):
    cleaned_text = clean_text(raw_text)
    extracted = extract_job_details(cleaned_text)
    return JobDescription(
        title=extracted.get("title", "Unknown Role"),
        raw_text=raw_text,
        cleaned_text=cleaned_text,
        location=extracted.get("location"),
        requirements=JobRequirements(
            hard_skills=extracted.get("skills", []),
            soft_skills=extracted.get("soft_skills", []),
            experience_requirement=extracted.get("experience_required"),
        ),
    )
