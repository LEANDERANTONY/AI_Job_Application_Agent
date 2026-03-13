from src.parsers.jd import clean_text, extract_job_details, parse_jd_text


def parse_jd_file(file):
    """Compatibility wrapper that returns parsed job-description text."""
    return parse_jd_text(file)
