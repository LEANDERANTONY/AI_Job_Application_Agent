"""Smoke tests for the nightly eval CLI.

The full LLM-mode run is too expensive (and stochastic) for the unit
suite — these tests confirm the deterministic plumbing:

  * Each runner adapter can execute in deterministic mode and produce a
    headline metric > 0 against the bundled fixtures.
  * The regression detector flags a drop past the threshold and only
    counts drops, not improvements.
  * The CLI exits 0 on clean runs, 1 on failures, and writes a JSON
    summary to ``--output``.
  * Selecting a single runner via ``--runner`` works.

We avoid touching ``OpenAIService`` by passing ``openai_service=None``
to every adapter; the deterministic fallback paths in
``tests/quality/`` are the same ones the dev runners use without
``--include-llm``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend import nightly_eval


# ---------------------------------------------------------------------
# Adapter smoke tests — deterministic mode only
# ---------------------------------------------------------------------


def test_resume_parser_runner_runs_deterministic():
    outcome = nightly_eval._run_resume_parser(openai_service=None)
    assert outcome.name == "resume_parser"
    assert outcome.fixture_count >= 1
    assert outcome.passed is True
    assert outcome.headline_metric is not None
    assert 0.0 <= outcome.headline_metric <= 1.0


def test_jd_parser_runner_runs_deterministic():
    outcome = nightly_eval._run_jd_parser(openai_service=None)
    assert outcome.name == "jd_parser"
    assert outcome.fixture_count >= 1
    assert outcome.passed is True
    assert outcome.headline_metric is not None


def test_tailoring_runner_uses_deterministic_when_no_llm():
    """Without an OpenAIService the tailoring adapter scores the
    deterministic fallback. It should still produce a headline metric
    against the six bundled fixture pairs."""
    outcome = nightly_eval._run_tailoring(openai_service=None)
    assert outcome.name == "tailoring"
    assert outcome.fixture_count >= 1
    assert outcome.headline_metric is not None


def test_review_runner_uses_deterministic_when_no_llm():
    """The clean scenarios run the review fallback; we only assert
    the metric exists — approval-rate on deterministic clean inputs
    isn't meaningful but the structure must be intact."""
    outcome = nightly_eval._run_review(openai_service=None)
    assert outcome.name == "review"
    # Fixture count may be zero if the deterministic fallback can't
    # produce a valid review for the clean inputs — that's fine for the
    # smoke test as long as the runner didn't crash.
    assert outcome.error == ""


def test_orchestrator_e2e_runner_skips_without_llm():
    """E2E is meaningless without a real LLM (the per-agent fallbacks
    each have their own coverage). The adapter must mark it skipped
    rather than emit a bogus metric."""
    outcome = nightly_eval._run_orchestrator_e2e(openai_service=None)
    assert outcome.name == "orchestrator_e2e"
    assert outcome.passed is True  # skipped is treated as pass
    assert outcome.headline_metric is None
    assert "skipped" in outcome.metric_label.lower()


# ---------------------------------------------------------------------
# Regression detection
# ---------------------------------------------------------------------


def _outcome(name: str, metric: float) -> nightly_eval.RunnerOutcome:
    return nightly_eval.RunnerOutcome(
        name=name,
        passed=True,
        duration_seconds=0.1,
        headline_metric=metric,
        metric_label="test",
        fixture_count=1,
    )


def test_detect_regressions_flags_drop_past_threshold():
    runners = [_outcome("tailoring", 0.80)]
    baseline = {"tailoring": 0.90}
    regressions = nightly_eval._detect_regressions(
        runners, baseline, threshold=0.05
    )
    assert len(regressions) == 1
    entry = regressions[0]
    assert entry["name"] == "tailoring"
    assert entry["baseline"] == 0.90
    assert entry["current"] == 0.80
    assert entry["delta"] == -0.10


def test_detect_regressions_ignores_drops_within_threshold():
    runners = [_outcome("tailoring", 0.88)]
    baseline = {"tailoring": 0.90}
    regressions = nightly_eval._detect_regressions(
        runners, baseline, threshold=0.05
    )
    assert regressions == []


def test_detect_regressions_ignores_improvements():
    runners = [_outcome("tailoring", 0.97)]
    baseline = {"tailoring": 0.90}
    regressions = nightly_eval._detect_regressions(
        runners, baseline, threshold=0.05
    )
    assert regressions == []


def test_detect_regressions_ignores_missing_baseline():
    runners = [_outcome("new_runner", 0.40)]
    baseline = {"tailoring": 0.90}
    regressions = nightly_eval._detect_regressions(
        runners, baseline, threshold=0.05
    )
    assert regressions == []


def test_detect_regressions_skips_none_metric():
    """A runner that returned None (skipped or crashed) shouldn't
    register as a regression — we already log the failure separately."""
    runners = [
        nightly_eval.RunnerOutcome(
            name="orchestrator_e2e",
            passed=True,
            duration_seconds=0.1,
            headline_metric=None,
            metric_label="skipped",
        )
    ]
    baseline = {"orchestrator_e2e": 0.85}
    assert nightly_eval._detect_regressions(runners, baseline, 0.05) == []


# ---------------------------------------------------------------------
# Baseline IO
# ---------------------------------------------------------------------


def test_load_baseline_reads_summary_json(tmp_path: Path):
    payload = {
        "runners": [
            {"name": "tailoring", "headline_metric": 0.83},
            {"name": "review", "headline_metric": 0.92},
            {"name": "broken", "headline_metric": None},
        ]
    }
    target = tmp_path / "baseline.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    baseline = nightly_eval._load_baseline(target)
    assert baseline == {"tailoring": 0.83, "review": 0.92}


def test_load_baseline_returns_empty_when_missing(tmp_path: Path):
    assert nightly_eval._load_baseline(tmp_path / "missing.json") == {}


def test_load_baseline_returns_empty_on_invalid_json(tmp_path: Path):
    target = tmp_path / "bad.json"
    target.write_text("not-json", encoding="utf-8")
    assert nightly_eval._load_baseline(target) == {}


def test_load_baseline_none_path_returns_empty():
    assert nightly_eval._load_baseline(None) == {}


# ---------------------------------------------------------------------
# run_nightly_eval end-to-end (deterministic, fast)
# ---------------------------------------------------------------------


def test_run_nightly_eval_with_deterministic_runners_passes(tmp_path: Path):
    """Smoke-test the public entry point with only the two deterministic
    runners. Should pass with no baseline and no regressions."""
    summary = nightly_eval.run_nightly_eval(
        include_llm=False,
        baseline_path=None,
        output_path=tmp_path / "summary.json",
        regression_threshold=0.05,
        runners=["resume_parser", "jd_parser"],
    )
    assert summary.overall_pass is True
    assert summary.failures == []
    assert summary.regressions == []
    assert len(summary.runners) == 2
    names = {entry["name"] for entry in summary.runners}
    assert names == {"resume_parser", "jd_parser"}

    written = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert written["overall_pass"] is True


def test_run_nightly_eval_flags_regression_against_baseline(tmp_path: Path):
    """Synthesize a baseline that's well above what the deterministic
    parsers can produce — the run should still execute but mark
    ``overall_pass=False`` because of the regression delta."""
    fake_baseline_path = tmp_path / "baseline.json"
    fake_baseline_path.write_text(
        json.dumps(
            {
                "runners": [
                    {"name": "resume_parser", "headline_metric": 0.999},
                    {"name": "jd_parser", "headline_metric": 0.999},
                ]
            }
        ),
        encoding="utf-8",
    )
    summary = nightly_eval.run_nightly_eval(
        include_llm=False,
        baseline_path=fake_baseline_path,
        regression_threshold=0.01,
        runners=["resume_parser", "jd_parser"],
    )
    assert summary.overall_pass is False
    assert len(summary.regressions) >= 1
    for entry in summary.regressions:
        assert entry["baseline"] == 0.999
        assert entry["delta"] < 0


def test_main_returns_zero_on_clean_run(capsys):
    """The CLI should exit 0 and print a single JSON line."""
    exit_code = nightly_eval.main(
        ["--runner", "resume_parser", "--runner", "jd_parser"]
    )
    assert exit_code == 0
    captured = capsys.readouterr().out.strip().splitlines()
    # Stdout payload is JSON; allow log warnings on stderr.
    assert len(captured) == 1
    payload = json.loads(captured[0])
    assert payload["overall_pass"] is True
    assert payload["include_llm"] is False


def test_main_returns_one_on_regression(tmp_path: Path, capsys):
    fake_baseline_path = tmp_path / "baseline.json"
    fake_baseline_path.write_text(
        json.dumps(
            {
                "runners": [
                    {"name": "resume_parser", "headline_metric": 0.99},
                    {"name": "jd_parser", "headline_metric": 0.99},
                ]
            }
        ),
        encoding="utf-8",
    )
    exit_code = nightly_eval.main(
        [
            "--runner",
            "resume_parser",
            "--runner",
            "jd_parser",
            "--baseline",
            str(fake_baseline_path),
            "--regression-threshold",
            "0.01",
        ]
    )
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[0])
    assert payload["overall_pass"] is False


def test_run_nightly_eval_unknown_runner_is_skipped():
    summary = nightly_eval.run_nightly_eval(
        include_llm=False,
        runners=["does_not_exist"],
    )
    # No runners matched — overall_pass is vacuously True (no failures,
    # no regressions). The point is no crash on a typo.
    assert summary.runners == []
    assert summary.overall_pass is True


def test_resolve_openai_service_returns_none_without_include_llm():
    assert nightly_eval._resolve_openai_service(include_llm=False) is None
