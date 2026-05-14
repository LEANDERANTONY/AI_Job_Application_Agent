"""Nightly quality-evaluation CLI for AI Job Application Agent.

Wraps the existing per-agent quality runners under ``tests/quality/`` in
a single batch script suitable for a VPS cron. Each runner already
scores itself against the same fixture pairs that the dev tier-3 suite
exercises; this script aggregates the headline metrics into one JSON
summary, compares them against an optional baseline, and exits non-zero
on any regression beyond ``--regression-threshold`` (default 5%).

The point is "catch the night where a model upgrade silently drops
tailoring grounding from 0.93 to 0.78". The dev runners are designed
for human-eyeball inspection; this script is the unattended counter-
part — print a JSON line, exit 0/1, leave the rest to log-shipping.

Usage:
    python -m backend.nightly_eval                                # deterministic baseline
    python -m backend.nightly_eval --include-llm                  # full LLM run (~$0.25 / night)
    python -m backend.nightly_eval --include-llm --baseline X.json --output Y.json
    python -m backend.nightly_eval --include-llm --regression-threshold 0.07

Exit codes:
    0  every runner passed AND no headline metric regressed
    1  at least one runner failed OR a metric regressed past the threshold
    2  fatal config error (no fixtures, etc.)

The script is intentionally subprocess-free: it imports each runner's
helper functions directly so the OpenAI client / Supabase client stay
in-process and we don't pay extra cold-start cost per runner. Each
runner exposes the same ``score_*`` / ``FIXTURE_PAIRS`` surface that
the dev CLIs use, so we lean on those rather than parsing CLI output.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import traceback
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Optional


LOGGER = logging.getLogger("backend.nightly_eval")


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass
class RunnerOutcome:
    """One runner's pass/fail snapshot.

    ``headline_metric`` is the single floating value we threshold against
    the baseline (usually average overall score across fixtures). If the
    runner threw or had no fixtures we leave it at ``None`` and mark
    ``passed=False`` so a downstream observer can spot "didn't even
    execute" cleanly from "executed but regressed".
    """

    name: str
    passed: bool
    duration_seconds: float
    headline_metric: Optional[float] = None
    metric_label: str = ""
    fixture_count: int = 0
    error: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class NightlySummary:
    started_at: str
    duration_seconds: float
    include_llm: bool
    regression_threshold: float
    runners: list[dict[str, Any]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    regressions: list[dict[str, Any]] = field(default_factory=list)
    baseline_path: str = ""
    overall_pass: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Individual runner adapters
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_average(values: list[float]) -> Optional[float]:
    cleaned = [float(v) for v in values if v is not None]
    if not cleaned:
        return None
    return round(sum(cleaned) / len(cleaned), 4)


def _run_tailoring(openai_service) -> RunnerOutcome:
    """Programmatic wrapper around ``tests/quality/tailoring_quality_runner``.

    Scores the LLM mode when ``openai_service`` is available, otherwise
    falls back to the deterministic mode (still useful for catching
    fixture regressions even without a paid LLM run).
    """
    from tests.quality.tailoring_quality_runner import (
        FIXTURE_PAIRS,
        RESUMES_DIR,
        JDS_DIR,
        _build_inputs,
        _run_deterministic,
        _run_llm,
        score_output,
    )

    started = time.perf_counter()
    scores: list[float] = []
    fixtures_ok = 0
    for label, resume_filename, jd_filename in FIXTURE_PAIRS:
        resume_path = RESUMES_DIR / resume_filename
        jd_path = JDS_DIR / jd_filename
        if not resume_path.exists() or not jd_path.exists():
            continue
        candidate_profile, job_description, fit_analysis, tailored_draft = _build_inputs(
            resume_path, jd_path
        )
        if openai_service is not None:
            output = _run_llm(
                openai_service,
                candidate_profile,
                job_description,
                fit_analysis,
                tailored_draft,
            )
        else:
            output = _run_deterministic(
                candidate_profile, job_description, fit_analysis, tailored_draft
            )
        if output is None:
            continue
        result = score_output(
            output,
            candidate_profile.skills,
            fit_analysis.matched_hard_skills,
            fit_analysis.missing_hard_skills,
            candidate_profile.resume_text,
        )
        scores.append(result["overall"])
        fixtures_ok += 1

    duration = round(time.perf_counter() - started, 3)
    headline = _safe_average(scores)
    return RunnerOutcome(
        name="tailoring",
        passed=bool(headline and headline >= 0.7) and fixtures_ok > 0,
        duration_seconds=duration,
        headline_metric=headline,
        metric_label="average overall score",
        fixture_count=fixtures_ok,
        details={"per_fixture_overall": scores},
    )


def _run_review(openai_service) -> RunnerOutcome:
    """Programmatic wrapper around ``tests/quality/review_quality_runner``.

    The dev CLI exposes scenario scoring helpers; we reuse the clean
    scenarios as a lightweight signal. Adversarial scenarios still run
    in the dev workflow — here we want a stable headline that won't be
    LLM-flaky in the cron.
    """
    from tests.quality.review_quality_runner import (
        SCENARIOS,
        RESUMES_DIR,
        JDS_DIR,
    )
    from src.agents.review_agent import ReviewAgent
    from src.schemas import ResumeDocument
    from src.services.fit_service import build_fit_analysis
    from src.services.job_service import build_job_description_from_text
    from src.services.profile_service import build_candidate_profile_from_resume_auto
    from src.services.tailoring_service import build_tailored_resume_draft

    started = time.perf_counter()
    approvals: list[bool] = []
    fixtures_ok = 0
    for scenario in SCENARIOS:
        if scenario.get("mode") != "clean":
            # Adversarial fixtures are expensive and LLM-dependent — keep
            # them on the dev workflow. The cron wants a stable signal.
            continue
        resume_path = RESUMES_DIR / scenario["resume"]
        jd_path = JDS_DIR / scenario["jd"]
        if not resume_path.exists() or not jd_path.exists():
            continue
        resume_text = resume_path.read_text(encoding="utf-8")
        jd_text = jd_path.read_text(encoding="utf-8")
        document = ResumeDocument(text=resume_text, filetype="TXT", source=str(resume_path))
        candidate_profile = build_candidate_profile_from_resume_auto(document)
        job_description = build_job_description_from_text(jd_text)
        fit_analysis = build_fit_analysis(candidate_profile, job_description)
        tailored_draft = build_tailored_resume_draft(
            candidate_profile, job_description, fit_analysis
        )
        agent = ReviewAgent(openai_service=openai_service)
        try:
            review_output = agent.run(
                candidate_profile,
                job_description,
                fit_analysis,
                tailored_draft,
                scenario["input_tailoring"],
            )
        except Exception as exc:  # noqa: BLE001 - one bad scenario shouldn't kill the run
            LOGGER.warning(
                "review_runner_scenario_failed",
                extra={"scenario": scenario.get("label"), "error": str(exc)},
            )
            continue
        approvals.append(bool(review_output.approved))
        fixtures_ok += 1

    duration = round(time.perf_counter() - started, 3)
    approval_rate = (sum(1 for v in approvals if v) / len(approvals)) if approvals else None
    return RunnerOutcome(
        name="review",
        passed=bool(approval_rate and approval_rate >= 0.66) and fixtures_ok > 0,
        duration_seconds=duration,
        headline_metric=round(approval_rate, 4) if approval_rate is not None else None,
        metric_label="clean-input approval rate",
        fixture_count=fixtures_ok,
        details={"approvals": approvals},
    )


def _run_orchestrator_e2e(openai_service) -> RunnerOutcome:
    """Run the end-to-end orchestrator scorecard.

    Mirrors ``orchestrator_e2e_runner.main`` but as a function so we
    can capture the aggregate average without parsing stdout.
    """
    from tests.quality.orchestrator_e2e_runner import (
        FIXTURE_PAIRS,
        RESUMES_DIR,
        JDS_DIR,
        _run_fixture,
    )

    if openai_service is None:
        # The E2E runner is meaningless without a real LLM — the four
        # agents each have a deterministic fallback that the per-agent
        # runners cover. Skip rather than emit a misleading metric.
        return RunnerOutcome(
            name="orchestrator_e2e",
            passed=True,
            duration_seconds=0.0,
            headline_metric=None,
            metric_label="skipped (requires --include-llm)",
            fixture_count=0,
            details={"skipped_reason": "no openai_service"},
        )

    started = time.perf_counter()
    overalls: list[float] = []
    fixtures_ok = 0
    errors: list[str] = []
    for label, resume_filename, jd_filename in FIXTURE_PAIRS:
        resume_path = RESUMES_DIR / resume_filename
        jd_path = JDS_DIR / jd_filename
        if not resume_path.exists() or not jd_path.exists():
            continue
        try:
            result = _run_fixture(
                label=label,
                resume_path=resume_path,
                jd_path=jd_path,
                openai_service=openai_service,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{label}: {type(exc).__name__}: {exc}")
            continue
        overalls.append(float(result["overall"]))
        fixtures_ok += 1

    duration = round(time.perf_counter() - started, 3)
    headline = _safe_average(overalls)
    return RunnerOutcome(
        name="orchestrator_e2e",
        passed=bool(headline and headline >= 0.7) and fixtures_ok > 0 and not errors,
        duration_seconds=duration,
        headline_metric=headline,
        metric_label="end-to-end average overall",
        fixture_count=fixtures_ok,
        error="; ".join(errors),
        details={"per_fixture_overall": overalls, "errors": errors},
    )


def _run_resume_parser(openai_service) -> RunnerOutcome:
    """Deterministic resume-parser scorecard.

    Always-deterministic — the regex parser doesn't care whether
    OpenAI is configured. A regression here usually means a fixture
    edit changed canonical skills.

    The `openai_service` arg is accepted (and ignored) for signature
    symmetry with the LLM-backed runners — the main loop calls all
    five runners uniformly with the resolved service.
    """
    del openai_service
    from tests.quality.parser_quality_runner import (
        FIXTURES_DIR,
        EXPECTED_DIR,
        _run_deterministic,
        score_profile,
    )
    from src.schemas import ResumeDocument

    started = time.perf_counter()
    scores: list[float] = []
    fixtures_ok = 0
    for fixture_path in sorted(FIXTURES_DIR.glob("*.txt")):
        expected_path = EXPECTED_DIR / (fixture_path.stem + ".json")
        if not expected_path.exists():
            continue
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        text = fixture_path.read_text(encoding="utf-8")
        document = ResumeDocument(text=text, filetype="TXT", source="nightly")
        profile = _run_deterministic(document)
        result = score_profile(profile, expected)
        scores.append(result["overall"])
        fixtures_ok += 1

    duration = round(time.perf_counter() - started, 3)
    headline = _safe_average(scores)
    return RunnerOutcome(
        name="resume_parser",
        passed=bool(headline and headline >= 0.7) and fixtures_ok > 0,
        duration_seconds=duration,
        headline_metric=headline,
        metric_label="parser average overall",
        fixture_count=fixtures_ok,
        details={"per_fixture_overall": scores},
    )


def _run_jd_parser(openai_service) -> RunnerOutcome:
    """Deterministic JD-parser scorecard. Same shape as resume_parser.

    `openai_service` accepted (and ignored) for runner-loop symmetry."""
    del openai_service
    from tests.quality.jd_parser_quality_runner import (
        FIXTURES_DIR,
        EXPECTED_DIR,
        score_jd,
    )
    from src.services.job_service import build_job_description_from_text

    started = time.perf_counter()
    scores: list[float] = []
    fixtures_ok = 0
    for fixture_path in sorted(FIXTURES_DIR.glob("*.txt")):
        expected_path = EXPECTED_DIR / (fixture_path.stem + ".json")
        if not expected_path.exists():
            continue
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        text = fixture_path.read_text(encoding="utf-8")
        jd = build_job_description_from_text(text)
        result = score_jd(jd, expected)
        scores.append(result["overall"])
        fixtures_ok += 1

    duration = round(time.perf_counter() - started, 3)
    headline = _safe_average(scores)
    return RunnerOutcome(
        name="jd_parser",
        passed=bool(headline and headline >= 0.7) and fixtures_ok > 0,
        duration_seconds=duration,
        headline_metric=headline,
        metric_label="jd parser average overall",
        fixture_count=fixtures_ok,
        details={"per_fixture_overall": scores},
    )


# Registry order is intentional: cheap deterministic runners first so a
# fixture regression surfaces before we spend on LLM calls. The LLM
# runners (tailoring, review, orchestrator_e2e) only execute when
# ``--include-llm`` is passed AND OpenAIService is_available().
_RUNNERS: list[tuple[str, Callable[[Any], RunnerOutcome], bool]] = [
    # (name, callable, requires_llm_for_meaningful_metric)
    ("resume_parser", _run_resume_parser, False),
    ("jd_parser", _run_jd_parser, False),
    ("tailoring", _run_tailoring, True),
    ("review", _run_review, True),
    ("orchestrator_e2e", _run_orchestrator_e2e, True),
]


# ---------------------------------------------------------------------------
# Baseline comparison
# ---------------------------------------------------------------------------


def _load_baseline(path: Optional[Path]) -> dict[str, float]:
    """Read a previously-emitted nightly summary and return a name → metric map.

    Returns an empty dict when the baseline file is missing or
    unparseable. The caller treats "no baseline" as "no regression
    check" rather than failing — the first night runs without
    history.
    """
    if not path:
        return {}
    if not path.exists():
        LOGGER.warning("nightly_eval_baseline_missing", extra={"path": str(path)})
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning(
            "nightly_eval_baseline_unreadable",
            extra={"path": str(path), "error": str(exc)},
        )
        return {}
    baseline: dict[str, float] = {}
    for runner in payload.get("runners") or []:
        name = runner.get("name")
        metric = runner.get("headline_metric")
        if name and isinstance(metric, (int, float)):
            baseline[name] = float(metric)
    return baseline


def _detect_regressions(
    runners: list[RunnerOutcome],
    baseline: dict[str, float],
    threshold: float,
) -> list[dict[str, Any]]:
    """Return a list of {name, baseline, current, delta} for any runner
    whose headline metric dropped by more than ``threshold`` (absolute).

    Improvements are not regressions; missing baselines are not
    regressions. A baseline of 0.93 vs a current of 0.80 with
    threshold=0.05 is a regression (delta=-0.13). A baseline of 0.93
    vs current of 0.91 with threshold=0.05 is NOT a regression
    (delta=-0.02).
    """
    regressions: list[dict[str, Any]] = []
    for outcome in runners:
        if outcome.headline_metric is None:
            continue
        previous = baseline.get(outcome.name)
        if previous is None:
            continue
        delta = outcome.headline_metric - previous
        if delta < -abs(threshold):
            regressions.append(
                {
                    "name": outcome.name,
                    "metric_label": outcome.metric_label,
                    "baseline": round(previous, 4),
                    "current": round(outcome.headline_metric, 4),
                    "delta": round(delta, 4),
                    "threshold": threshold,
                }
            )
    return regressions


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def _resolve_openai_service(include_llm: bool):
    if not include_llm:
        return None
    try:
        from src.openai_service import OpenAIService
    except Exception as exc:  # pragma: no cover - import guard
        LOGGER.error("nightly_eval_openai_import_failed", extra={"error": str(exc)})
        return None
    service = OpenAIService()
    if not service.is_available():
        LOGGER.warning(
            "nightly_eval_openai_unavailable",
            extra={"reason": "OPENAI_API_KEY missing or invalid"},
        )
        return None
    return service


def run_nightly_eval(
    *,
    include_llm: bool = False,
    baseline_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
    regression_threshold: float = 0.05,
    runners: Optional[list[str]] = None,
) -> NightlySummary:
    """Execute every registered runner and emit a JSON summary.

    Pure-Python entry point so the smoke tests (and any future cron-
    HTTP-trigger) can exercise this without going through ``__main__``.
    """
    started_at = _now_iso()
    overall_start = time.perf_counter()

    openai_service = _resolve_openai_service(include_llm)

    selected_runners = runners or [name for name, _, _ in _RUNNERS]
    outcomes: list[RunnerOutcome] = []
    for name, runner_fn, _requires_llm in _RUNNERS:
        if name not in selected_runners:
            continue
        try:
            outcome = runner_fn(openai_service)
        except Exception as exc:  # noqa: BLE001 - one bad runner shouldn't kill the report
            LOGGER.exception("nightly_eval_runner_crashed", extra={"runner": name})
            outcome = RunnerOutcome(
                name=name,
                passed=False,
                duration_seconds=0.0,
                error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
            )
        outcomes.append(outcome)
        LOGGER.info(
            "nightly_eval_runner_finished",
            extra={
                "runner": name,
                "passed": outcome.passed,
                "metric": outcome.headline_metric,
                "metric_label": outcome.metric_label,
                "duration_seconds": outcome.duration_seconds,
                "fixture_count": outcome.fixture_count,
            },
        )

    baseline = _load_baseline(baseline_path)
    regressions = _detect_regressions(outcomes, baseline, regression_threshold)
    failures = [o.name for o in outcomes if not o.passed]

    summary = NightlySummary(
        started_at=started_at,
        duration_seconds=round(time.perf_counter() - overall_start, 3),
        include_llm=include_llm and openai_service is not None,
        regression_threshold=regression_threshold,
        runners=[asdict(o) for o in outcomes],
        failures=failures,
        regressions=regressions,
        baseline_path=str(baseline_path) if baseline_path else "",
        overall_pass=not failures and not regressions,
    )

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(summary.to_dict(), indent=2), encoding="utf-8"
        )

    return summary


def _configure_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--include-llm",
        action="store_true",
        help="Run the LLM-dependent runners (tailoring, review, e2e). Requires OPENAI_API_KEY.",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="Previous nightly summary JSON to compare current metrics against.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path to write the JSON summary (also goes to stdout).",
    )
    parser.add_argument(
        "--regression-threshold",
        type=float,
        default=0.05,
        help="Maximum allowed drop in any headline metric (absolute, e.g. 0.05 = 5 points).",
    )
    parser.add_argument(
        "--runner",
        action="append",
        dest="runners",
        default=None,
        help="Limit to a specific runner. Pass multiple times to add more. Default: all.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase log verbosity (-v INFO, -vv DEBUG).",
    )
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    summary = run_nightly_eval(
        include_llm=args.include_llm,
        baseline_path=args.baseline,
        output_path=args.output,
        regression_threshold=args.regression_threshold,
        runners=args.runners,
    )

    # Stdout payload is the canonical record for log shippers. Keep it a
    # single JSON object (no newlines inside) so ``journalctl`` /
    # ``docker logs`` / log shippers downstream can grep one line per
    # nightly run.
    print(json.dumps(summary.to_dict()))

    if summary.failures:
        LOGGER.warning(
            "nightly_eval_failed",
            extra={"failures": summary.failures, "regressions": summary.regressions},
        )
    elif summary.regressions:
        LOGGER.warning("nightly_eval_regressed", extra={"regressions": summary.regressions})

    return 0 if summary.overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
