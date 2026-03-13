import json
import zipfile
from io import TextIOWrapper

import pandas as pd

from src.errors import ParsingError


EXPECTED_EXPORT_FILES = {
    "Profile.csv",
    "Education.csv",
    "Skills.csv",
    "Certifications.csv",
    "Projects.csv",
    "Publications.csv",
    "Job Seeker Preferences.csv",
    "Positions.json",
}


def _safe_read_csv(zip_handle, filename):
    try:
        with zip_handle.open(filename) as file_handle:
            return pd.read_csv(TextIOWrapper(file_handle, encoding="utf-8"))
    except Exception:
        return None


def _safe_read_json(zip_handle, filename):
    try:
        with zip_handle.open(filename) as file_handle:
            return json.load(file_handle)
    except Exception:
        return None


def _find_matching_file(files, target_name):
    target_name_lower = target_name.lower()
    return next((name for name in files if name.lower().endswith(target_name_lower)), None)


def _clean_string_list(values):
    cleaned = []
    seen = set()
    for value in values:
        if pd.isna(value):
            continue
        normalized = str(value).strip()
        if normalized and normalized not in seen:
            cleaned.append(normalized)
            seen.add(normalized)
    return cleaned


def parse_linkedin_payload(zip_file):
    data = {
        "summary": {},
        "experience": [],
        "education": [],
        "skills": [],
        "certifications": [],
        "projects": [],
        "publications": [],
        "preferences": {},
    }

    try:
        archive = zipfile.ZipFile(zip_file, "r")
    except zipfile.BadZipFile as exc:
        raise ParsingError("The uploaded LinkedIn archive is not a valid ZIP file.") from exc

    with archive:
        files = archive.namelist()
        matched_files = {
            name for expected in EXPECTED_EXPORT_FILES for name in files if name.lower().endswith(expected.lower())
        }
        if not matched_files:
            raise ParsingError(
                "The ZIP file does not look like a LinkedIn data export with the expected files."
            )

        profile_csv = _find_matching_file(files, "Profile.csv")
        if profile_csv:
            profile_df = _safe_read_csv(archive, profile_csv)
            if profile_df is not None and not profile_df.empty:
                row = profile_df.iloc[0]
                data["summary"] = {
                    "name": f"{row.get('First Name', '')} {row.get('Last Name', '')}".strip(),
                    "headline": str(row.get("Headline", "") or "").strip(),
                    "location": str(row.get("Location", "") or "").strip(),
                    "summary": str(row.get("Summary", "") or "").strip(),
                }

        education_csv = _find_matching_file(files, "Education.csv")
        if education_csv:
            education_df = _safe_read_csv(archive, education_csv)
            if education_df is not None:
                for _, row in education_df.iterrows():
                    data["education"].append(
                        {
                            "school": str(row.get("School Name", "") or "").strip(),
                            "degree": str(row.get("Degree Name", "") or "").strip(),
                            "field": str(row.get("Field of Study", "") or "").strip(),
                            "start": str(row.get("Start Date", "") or "").strip(),
                            "end": str(row.get("End Date", "") or "").strip(),
                        }
                    )

        skills_csv = _find_matching_file(files, "Skills.csv")
        if skills_csv:
            skills_df = _safe_read_csv(archive, skills_csv)
            if skills_df is not None and "Name" in skills_df:
                data["skills"] = _clean_string_list(skills_df["Name"].tolist())

        certifications_csv = _find_matching_file(files, "Certifications.csv")
        if certifications_csv:
            certifications_df = _safe_read_csv(archive, certifications_csv)
            if certifications_df is not None and "Name" in certifications_df:
                data["certifications"] = _clean_string_list(certifications_df["Name"].tolist())

        projects_csv = _find_matching_file(files, "Projects.csv")
        if projects_csv:
            projects_df = _safe_read_csv(archive, projects_csv)
            if projects_df is not None:
                for _, row in projects_df.iterrows():
                    data["projects"].append(
                        {
                            "title": str(row.get("Title", "") or "").strip(),
                            "description": str(row.get("Description", "") or "").strip(),
                            "start": str(row.get("Start Date", "") or "").strip(),
                            "end": str(row.get("End Date", "") or "").strip(),
                        }
                    )

        publications_csv = _find_matching_file(files, "Publications.csv")
        if publications_csv:
            publications_df = _safe_read_csv(archive, publications_csv)
            if publications_df is not None:
                for _, row in publications_df.iterrows():
                    data["publications"].append(
                        {
                            "title": str(row.get("Title", "") or "").strip(),
                            "publisher": str(row.get("Publisher", "") or "").strip(),
                            "date": str(row.get("Publication Date", "") or "").strip(),
                            "description": str(row.get("Description", "") or "").strip(),
                        }
                    )

        preferences_csv = _find_matching_file(files, "Job Seeker Preferences.csv")
        if preferences_csv:
            preferences_df = _safe_read_csv(archive, preferences_csv)
            if preferences_df is not None and not preferences_df.empty:
                raw_preferences = preferences_df.iloc[0].to_dict()
                data["preferences"] = {
                    str(key): value for key, value in raw_preferences.items() if pd.notnull(value)
                }

        positions_json = _find_matching_file(files, "Positions.json")
        if positions_json:
            positions = _safe_read_json(archive, positions_json)
            if isinstance(positions, list):
                for position in positions:
                    data["experience"].append(
                        {
                            "title": str(position.get("title", "") or "").strip(),
                            "company": str(position.get("companyName", "") or "").strip(),
                            "location": str(position.get("locationName", "") or "").strip(),
                            "start": position.get("timePeriod", {}).get("startDate", {}),
                            "end": position.get("timePeriod", {}).get("endDate", {}),
                            "description": str(position.get("description", "") or "").strip(),
                        }
                    )

    return data

