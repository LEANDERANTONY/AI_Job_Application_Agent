import json
from io import BytesIO
from zipfile import ZipFile

from src.linkedin_parser import parse_linkedin_zip


def build_linkedin_export():
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(
            "Profile.csv",
            "First Name,Last Name,Headline,Location,Summary\n"
            "Leander,Antony,AI Engineer,Chennai,Builds ML apps\n",
        )
        archive.writestr("Skills.csv", "Name\nPython\nSQL\n")
        archive.writestr(
            "Education.csv",
            "School Name,Degree Name,Field of Study,Start Date,End Date\n"
            "XYZ University,B.Tech,Computer Science,2019,2023\n",
        )
        archive.writestr(
            "Job Seeker Preferences.csv",
            "Open To Remote,Preferred Title\nYes,Machine Learning Engineer\n",
        )
        archive.writestr(
            "Positions.json",
            json.dumps(
                [
                    {
                        "title": "AI Intern",
                        "companyName": "Example Labs",
                        "locationName": "Chennai",
                        "description": "Worked on NLP pipelines",
                        "timePeriod": {
                            "startDate": {"year": 2024, "month": 1},
                            "endDate": {"year": 2024, "month": 6},
                        },
                    }
                ]
            ),
        )
    buffer.seek(0)
    return buffer


def test_parse_linkedin_zip_normalizes_export_data():
    parsed = parse_linkedin_zip(build_linkedin_export())

    assert parsed["summary"]["name"] == "Leander Antony"
    assert parsed["summary"]["headline"] == "AI Engineer"
    assert parsed["skills"] == ["Python", "SQL"]
    assert parsed["education"][0]["school"] == "XYZ University"
    assert parsed["preferences"]["Preferred Title"] == "Machine Learning Engineer"
    assert parsed["experience"][0]["company"] == "Example Labs"

