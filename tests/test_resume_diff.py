from src.resume_diff import build_resume_diff, build_resume_diff_metrics


def test_build_resume_diff_returns_unified_diff_text():
    original_text = "Name\nPython\nBuilt ML apps"
    tailored_text = "Name\nPython SQL\nBuilt production ML apps"

    diff_text = build_resume_diff(original_text, tailored_text)

    assert "--- original_resume" in diff_text
    assert "+++ tailored_resume" in diff_text
    assert "+Python SQL" in diff_text


def test_build_resume_diff_metrics_counts_changes():
    original_text = "Name\nPython\nBuilt ML apps"
    tailored_text = "Name\nPython SQL\nBuilt production ML apps"

    metrics = build_resume_diff_metrics(original_text, tailored_text)

    assert metrics["original_line_count"] == 3
    assert metrics["tailored_line_count"] == 3
    assert metrics["added_lines"] >= 1
    assert metrics["removed_lines"] >= 1
    assert 0 <= metrics["similarity_ratio"] <= 100