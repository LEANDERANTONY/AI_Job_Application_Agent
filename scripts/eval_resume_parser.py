import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.config import DEMO_RESUME_DIR
from src.parsers.resume import parse_resume_document
from src.services.profile_service import build_candidate_profile_from_resume
from src.services.resume_llm_parser_service import ResumeLLMParserService


DEFAULT_OUTPUT_DIR = REPO_ROOT / ".codex-local" / "resume-parser-eval"
SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt"}


def _to_jsonable(value: Any):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    return value


def _collect_default_samples() -> list[Path]:
    if not DEMO_RESUME_DIR.exists():
        return []
    return sorted(
        file
        for file in DEMO_RESUME_DIR.iterdir()
        if file.is_file() and file.suffix.lower() in SUPPORTED_SUFFIXES
    )


def _load_resume_document(path: Path):
    with path.open("rb") as handle:
        return parse_resume_document(handle, source="offline_eval")


def _slugify(path: Path) -> str:
    return path.stem.lower().replace(" ", "_").replace("-", "_")


def _build_summary(deterministic_profile: Any, llm_profile: dict[str, Any], resume_document) -> dict[str, Any]:
    deterministic = _to_jsonable(deterministic_profile)
    return {
        "filetype": resume_document.filetype,
        "source_word_count": len(str(resume_document.text or "").split()),
        "deterministic_skill_count": len(deterministic.get("skills") or []),
        "deterministic_experience_count": len(deterministic.get("experience") or []),
        "deterministic_education_count": len(deterministic.get("education") or []),
        "llm_skill_count": len(llm_profile.get("skills") or []),
        "llm_experience_count": len(llm_profile.get("experience") or []),
        "llm_project_count": len(llm_profile.get("projects") or []),
        "llm_education_count": len(llm_profile.get("education") or []),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate deterministic vs experimental LLM resume parsing on sample resumes."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional resume file paths. If omitted, uses files from static/demo_resume.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory to store evaluation JSON outputs.",
    )
    args = parser.parse_args()

    sample_paths = [Path(path).expanduser() for path in args.paths] if args.paths else _collect_default_samples()
    sample_paths = [path for path in sample_paths if path.exists() and path.suffix.lower() in SUPPORTED_SUFFIXES]
    if not sample_paths:
        raise SystemExit("No supported resume samples found.")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    llm_parser = ResumeLLMParserService()
    if not llm_parser.is_available():
        raise SystemExit("OpenAI is not configured. Set OPENAI_API_KEY or openai_key.txt first.")

    index_rows = []
    for path in sample_paths:
        try:
            resume_document = _load_resume_document(path)
            deterministic_profile = build_candidate_profile_from_resume(resume_document)
            llm_profile = llm_parser.parse(resume_document)
            summary = _build_summary(deterministic_profile, llm_profile, resume_document)

            payload = {
                "source_path": str(path),
                "summary": summary,
                "extracted_resume_text": resume_document.text,
                "deterministic_profile": _to_jsonable(deterministic_profile),
                "llm_profile": llm_profile,
            }

            destination = output_dir / f"{_slugify(path)}.json"
            destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            index_rows.append(
                {
                    "status": "ok",
                    "source_path": str(path),
                    "output_file": str(destination),
                    **summary,
                }
            )
            print(
                "[ok] {name} | words={words} | det_exp={det_exp} | llm_exp={llm_exp} | llm_projects={llm_projects}".format(
                    name=path.name,
                    words=summary["source_word_count"],
                    det_exp=summary["deterministic_experience_count"],
                    llm_exp=summary["llm_experience_count"],
                    llm_projects=summary["llm_project_count"],
                )
            )
        except Exception as exc:
            index_rows.append(
                {
                    "status": "error",
                    "source_path": str(path),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            print(f"[error] {path.name} | {type(exc).__name__}: {exc}")

    index_path = output_dir / "index.json"
    index_path.write_text(json.dumps(index_rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved evaluation results to {output_dir}")


if __name__ == "__main__":
    main()
