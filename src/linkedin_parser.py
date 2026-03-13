from src.parsers.linkedin import parse_linkedin_payload


def parse_linkedin_zip(zip_file):
    """Compatibility wrapper that returns parsed LinkedIn export payloads."""
    return parse_linkedin_payload(zip_file)
