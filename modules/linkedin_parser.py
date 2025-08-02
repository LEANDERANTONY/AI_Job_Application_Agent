import zipfile
import json
import pandas as pd
from io import TextIOWrapper


def parse_linkedin_zip(zip_file):
    """
    Parses LinkedIn Data Export (.zip) and returns structured profile data.
    Supports both CSV (basic export) and JSON (full archive) formats.
    Returns:
        dict with keys: summary, experience, education, skills, certifications, projects, publications, preferences
    """

    data = {
        "summary": {},
        "experience": [],
        "education": [],
        "skills": [],
        "certifications": [],
        "projects": [],
        "publications": [],
        "preferences": {}
    }

    def safe_read_csv(z, filename):
        try:
            with z.open(filename) as f:
                return pd.read_csv(TextIOWrapper(f, 'utf-8'))
        except:
            return None

    def safe_read_json(z, filename):
        try:
            with z.open(filename) as f:
                return json.load(f)
        except:
            return None

    with zipfile.ZipFile(zip_file, 'r') as z:
        files = z.namelist()

        # Summary: Profile.csv
        profile_csv = next((f for f in files if "Profile.csv" in f), None)
        if profile_csv:
            df = safe_read_csv(z, profile_csv)
            if df is not None and not df.empty:
                row = df.iloc[0]
                data["summary"] = {
                    "name": f"{row.get('First Name', '')} {row.get('Last Name', '')}".strip(),
                    "headline": row.get('Headline', ''),
                    "location": row.get('Location', ''),
                    "summary": row.get('Summary', '')
                }

        # Education
        edu_csv = next((f for f in files if "Education.csv" in f), None)
        if edu_csv:
            df = safe_read_csv(z, edu_csv)
            if df is not None:
                for _, row in df.iterrows():
                    data["education"].append({
                        "school": row.get("School Name", ""),
                        "degree": row.get("Degree Name", ""),
                        "field": row.get("Field of Study", ""),
                        "start": row.get("Start Date", ""),
                        "end": row.get("End Date", "")
                    })

        # Skills
        skills_csv = next((f for f in files if "Skills.csv" in f), None)
        if skills_csv:
            df = safe_read_csv(z, skills_csv)
            if df is not None:
                data["skills"] = df["Name"].dropna().tolist()

        # Certifications
        certs_csv = next((f for f in files if "Certifications.csv" in f), None)
        if certs_csv:
            df = safe_read_csv(z, certs_csv)
            if df is not None:
                data["certifications"] = df["Name"].dropna().tolist()

        # Projects
        projects_csv = next((f for f in files if "Projects.csv" in f), None)
        if projects_csv:
            df = safe_read_csv(z, projects_csv)
            if df is not None:
                for _, row in df.iterrows():
                    data["projects"].append({
                        "title": row.get("Title", ""),
                        "description": row.get("Description", ""),
                        "start": row.get("Start Date", ""),
                        "end": row.get("End Date", "")
                    })

        # Publications
        pubs_csv = next((f for f in files if "Publications.csv" in f), None)
        if pubs_csv:
            df = safe_read_csv(z, pubs_csv)
            if df is not None:
                for _, row in df.iterrows():
                    data["publications"].append({
                        "title": row.get("Title", ""),
                        "publisher": row.get("Publisher", ""),
                        "date": row.get("Publication Date", ""),
                        "description": row.get("Description", "")
                    })

        # Preferences
        prefs_csv = next((f for f in files if "Job Seeker Preferences.csv" in f), None)
        if prefs_csv:
            df = safe_read_csv(z, prefs_csv)
            if df is not None and not df.empty:
                prefs = df.iloc[0].to_dict()
                data["preferences"] = {k: v for k, v in prefs.items() if pd.notnull(v)}

        # Experience (only in full archive)
        positions_json = next((f for f in files if "Positions.json" in f), None)
        if positions_json:
            positions = safe_read_json(z, positions_json)
            if positions:
                for pos in positions:
                    data["experience"].append({
                        "title": pos.get("title", ""),
                        "company": pos.get("companyName", ""),
                        "location": pos.get("locationName", ""),
                        "start": pos.get("timePeriod", {}).get("startDate", {}),
                        "end": pos.get("timePeriod", {}).get("endDate", {}),
                        "description": pos.get("description", "")
                    })

    return data
