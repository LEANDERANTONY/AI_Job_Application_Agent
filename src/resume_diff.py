from difflib import SequenceMatcher, unified_diff


def build_resume_diff(original_text: str, tailored_text: str, context_lines: int = 2) -> str:
    original_lines = str(original_text or "").splitlines()
    tailored_lines = str(tailored_text or "").splitlines()
    diff_lines = list(
        unified_diff(
            original_lines,
            tailored_lines,
            fromfile="original_resume",
            tofile="tailored_resume",
            lineterm="",
            n=context_lines,
        )
    )
    return "\n".join(diff_lines) if diff_lines else "No line-level differences detected."


def build_resume_diff_metrics(original_text: str, tailored_text: str) -> dict:
    original_lines = str(original_text or "").splitlines()
    tailored_lines = str(tailored_text or "").splitlines()
    diff = list(unified_diff(original_lines, tailored_lines, lineterm="", n=0))
    added_lines = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
    removed_lines = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
    similarity_ratio = SequenceMatcher(None, str(original_text or ""), str(tailored_text or "")).ratio()
    return {
        "original_line_count": len(original_lines),
        "tailored_line_count": len(tailored_lines),
        "added_lines": added_lines,
        "removed_lines": removed_lines,
        "similarity_ratio": round(similarity_ratio * 100),
    }