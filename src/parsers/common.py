import mimetypes
import re

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


def _looks_like_letter_spaced_text(line):
    tokens = [token for token in line.split() if token]
    if len(tokens) < 6:
        return False
    single_char_tokens = 0
    alpha_tokens = 0
    for token in tokens:
        letters_only = re.sub(r"[^A-Za-z0-9]", "", token)
        if not letters_only:
            continue
        alpha_tokens += 1
        if len(letters_only) == 1:
            single_char_tokens += 1
    return alpha_tokens >= 6 and single_char_tokens >= max(4, int(alpha_tokens * 0.6))


def _repair_letter_spaced_line(line):
    placeholder = "\uFFF0"
    repaired = re.sub(r" {2,}", placeholder, line)
    repaired = re.sub(r"(?<=\w) (?=\w)", "", repaired)
    repaired = repaired.replace(placeholder, " ")
    repaired = re.sub(r"(?<=\d)(?=[A-Za-z])", " ", repaired)
    repaired = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", repaired)
    return repaired


def normalize_extracted_text(text):
    normalized = str(text or "")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\xa0", " ").replace("\u200b", "")
    normalized = normalized.replace("\ufffd", " • ")
    normalized = normalized.replace("\uf0b7", "•")

    lines = []
    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _looks_like_letter_spaced_text(line):
            line = _repair_letter_spaced_line(line)
        line = re.sub(r"\s*[|•·]\s*", " • ", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines).strip()

