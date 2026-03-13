from src.parsers.resume import parse_resume_document


def parse_resume(file, source="uploaded"):
    """Compatibility wrapper that returns `(text, filetype)`."""
    document = parse_resume_document(file, source=source)
    return document.text, document.filetype
