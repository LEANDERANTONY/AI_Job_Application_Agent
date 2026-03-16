from src.ui import page_artifacts


def test_resolve_resume_theme_widget_value_keeps_valid_stored_theme(monkeypatch):
    monkeypatch.setattr(page_artifacts, "get_tailored_resume_theme", lambda default_theme=None: "modern_professional")
    calls = []
    monkeypatch.setattr(page_artifacts, "set_tailored_resume_theme", lambda theme_name: calls.append(theme_name))

    resolved = page_artifacts._resolve_resume_theme_widget_value(
        "modern_professional",
        ["classic_ats", "modern_professional"],
    )

    assert resolved == "modern_professional"
    assert calls == []


def test_resolve_resume_theme_widget_value_resets_invalid_stored_theme(monkeypatch):
    monkeypatch.setattr(page_artifacts, "get_tailored_resume_theme", lambda default_theme=None: "broken_theme")
    calls = []
    monkeypatch.setattr(page_artifacts, "set_tailored_resume_theme", lambda theme_name: calls.append(theme_name))

    resolved = page_artifacts._resolve_resume_theme_widget_value(
        "modern_professional",
        ["classic_ats", "modern_professional"],
    )

    assert resolved == "modern_professional"
    assert calls == ["modern_professional"]


def test_build_download_widget_key_changes_when_artifact_content_changes():
    first = page_artifacts._build_download_widget_key(
        "download_tailored_resume_markdown",
        type("Artifact", (), {
            "title": "Resume",
            "summary": "Classic",
            "markdown": "# Resume\nClassic",
        })(),
    )
    second = page_artifacts._build_download_widget_key(
        "download_tailored_resume_markdown",
        type("Artifact", (), {
            "title": "Resume",
            "summary": "Modern",
            "markdown": "# Resume\nModern",
        })(),
    )

    assert first != second
    assert first.startswith("download_tailored_resume_markdown:")


def test_prepare_deferred_download_only_runs_when_uncached_and_clicked():
    calls = []

    prepared = page_artifacts._prepare_deferred_download(
        True,
        None,
        lambda: calls.append("prepared"),
    )

    assert prepared is True
    assert calls == ["prepared"]


def test_prepare_deferred_download_skips_when_payload_already_cached():
    calls = []

    prepared = page_artifacts._prepare_deferred_download(
        True,
        b"cached",
        lambda: calls.append("prepared"),
    )

    assert prepared is False
    assert calls == []


def test_queue_browser_download_stores_pending_payload(monkeypatch):
    captured = {}

    monkeypatch.setattr(page_artifacts, "set_pending_browser_download", lambda payload: captured.update(payload))

    page_artifacts._queue_browser_download(
        "report_pdf",
        b"pdf-bytes",
        "report.pdf",
        "application/pdf",
    )

    assert captured == {
        "target": "report_pdf",
        "data": b"pdf-bytes",
        "file_name": "report.pdf",
        "mime": "application/pdf",
    }


def test_render_pending_auto_download_only_consumes_matching_target(monkeypatch):
    calls = []

    monkeypatch.setattr(page_artifacts, "get_pending_browser_download", lambda: {
        "target": "tailored_resume_pdf",
        "data": b"pdf-bytes",
        "file_name": "resume.pdf",
        "mime": "application/pdf",
    })
    monkeypatch.setattr(page_artifacts, "render_auto_download", lambda data, file_name, mime, key: calls.append((data, file_name, mime, key)))
    monkeypatch.setattr(page_artifacts, "consume_pending_browser_download", lambda: calls.append("consumed"))
    monkeypatch.setattr(page_artifacts.st, "caption", lambda text: calls.append(text))

    rendered = page_artifacts._render_pending_auto_download("report_pdf")

    assert rendered is False
    assert calls == []


def test_render_pending_auto_download_renders_and_consumes_matching_target(monkeypatch):
    calls = []

    monkeypatch.setattr(page_artifacts, "get_pending_browser_download", lambda: {
        "target": "report_pdf",
        "data": b"pdf-bytes",
        "file_name": "report.pdf",
        "mime": "application/pdf",
    })
    monkeypatch.setattr(page_artifacts, "render_auto_download", lambda data, file_name, mime, key: calls.append((data, file_name, mime, key)))
    monkeypatch.setattr(page_artifacts, "consume_pending_browser_download", lambda: calls.append("consumed"))
    monkeypatch.setattr(page_artifacts.st, "caption", lambda text: calls.append(text))

    rendered = page_artifacts._render_pending_auto_download("report_pdf")

    assert rendered is True
    assert calls[0] == (b"pdf-bytes", "report.pdf", "application/pdf", "auto_download:report_pdf")
    assert "consumed" in calls