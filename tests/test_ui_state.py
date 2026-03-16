from types import SimpleNamespace

from src.ui import state


def test_ensure_state_sets_default_once(monkeypatch):
    fake_streamlit = SimpleNamespace(session_state={})
    monkeypatch.setattr(state, "st", fake_streamlit)

    first = state.ensure_state("example", {"count": 1})
    second = state.ensure_state("example", {"count": 2})

    assert first == {"count": 1}
    assert second == {"count": 1}
    assert fake_streamlit.session_state["example"] == {"count": 1}


def test_set_and_clear_authenticated_session(monkeypatch):
    fake_streamlit = SimpleNamespace(session_state={})
    monkeypatch.setattr(state, "st", fake_streamlit)
    auth_session = SimpleNamespace(
        access_token="access-token",
        refresh_token="refresh-token",
        user=SimpleNamespace(email="user@example.com"),
    )

    user = state.set_authenticated_session(auth_session)

    assert user.email == "user@example.com"
    assert state.is_authenticated() is True
    assert state.get_auth_tokens() == ("access-token", "refresh-token")

    cleared_user = state.clear_authenticated_session()

    assert cleared_user.email == "user@example.com"
    assert state.is_authenticated() is False
    assert state.get_auth_tokens() == (None, None)


def test_sync_signatures_clear_cached_export_bytes(monkeypatch):
    fake_streamlit = SimpleNamespace(
        session_state={
            state.APPLICATION_REPORT_PDF_BYTES: b"report-pdf",
            state.TAILORED_RESUME_PDF_BYTES: b"resume-pdf",
            state.EXPORT_BUNDLE_BYTES: b"bundle",
        }
    )
    monkeypatch.setattr(state, "st", fake_streamlit)

    state.sync_report_signature("report-v1")
    state.sync_tailored_resume_signature("resume-v1")

    assert state.get_cached_pdf_bytes() is None
    assert state.get_cached_tailored_resume_pdf_bytes() is None
    assert state.get_cached_export_bundle_bytes() is None


def test_request_menu_navigation_can_be_consumed_once(monkeypatch):
    fake_streamlit = SimpleNamespace(session_state={})
    monkeypatch.setattr(state, "st", fake_streamlit)

    state.request_menu_navigation("Manual JD Input")

    assert state.consume_pending_menu() == "Manual JD Input"
    assert state.consume_pending_menu() is None


def test_tailored_resume_pdf_cache_can_store_multiple_themes(monkeypatch):
    fake_streamlit = SimpleNamespace(session_state={})
    monkeypatch.setattr(state, "st", fake_streamlit)

    state.set_tailored_resume_theme("classic_ats")
    state.set_cached_tailored_resume_pdf_bytes(b"classic-pdf", theme_name="classic_ats")
    state.set_cached_tailored_resume_pdf_bytes(b"modern-pdf", theme_name="modern_professional")

    assert state.get_cached_tailored_resume_pdf_bytes("classic_ats") == b"classic-pdf"
    assert state.get_cached_tailored_resume_pdf_bytes("modern_professional") == b"modern-pdf"

    state.set_tailored_resume_theme("modern_professional")

    assert state.get_cached_tailored_resume_pdf_bytes() == b"modern-pdf"


def test_manual_jd_utility_panel_open_defaults_and_updates(monkeypatch):
    fake_streamlit = SimpleNamespace(session_state={})
    monkeypatch.setattr(state, "st", fake_streamlit)

    assert state.get_manual_jd_utility_panel_open() is True

    state.set_manual_jd_utility_panel_open(False)

    assert state.get_manual_jd_utility_panel_open() is False