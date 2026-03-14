import hashlib
import json
from dataclasses import asdict


def workflow_signature(candidate_profile, job_description, fit_analysis, tailored_draft):
    payload = {
        "candidate_profile": asdict(candidate_profile),
        "job_description": asdict(job_description),
        "fit_analysis": asdict(fit_analysis),
        "tailored_draft": asdict(tailored_draft),
    }
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def report_signature(report):
    raw = json.dumps(
        {
            "title": report.title,
            "summary": report.summary,
            "markdown": report.markdown,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()