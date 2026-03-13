import mimetypes

from src.errors import ParsingError


def rewind(file):
    if hasattr(file, "seek"):
        file.seek(0)


def detect_file_type(file):
    if hasattr(file, "type") and file.type:
        return file.type
    filename = getattr(file, "name", "")
    mime_guess, _ = mimetypes.guess_type(filename)
    return mime_guess or "application/octet-stream"


def read_file_bytes(file):
    try:
        rewind(file)
        contents = file.read()
    except Exception as exc:
        raise ParsingError("Could not read the provided file.") from exc

    if isinstance(contents, bytes):
        file_bytes = contents
    else:
        file_bytes = str(contents).encode("utf-8")

    if not file_bytes.strip():
        raise ParsingError("The provided file appears to be empty.")

    return file_bytes


def decode_text(file_bytes):
    return file_bytes.decode("utf-8", errors="ignore")

