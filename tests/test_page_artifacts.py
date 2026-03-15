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