from src.ui import state


def test_clear_authenticated_session_resets_saved_jobs_state(monkeypatch):
    session = {
        state.AUTH_ACCESS_TOKEN: "access",
        state.AUTH_REFRESH_TOKEN: "refresh",
        state.AUTH_USER: object(),
        state.SAVED_JOBS: [{"id": "job-1"}],
        state.SAVED_JOBS_USER_ID: "user-123",
        state.SAVED_JOBS_NOTICE: {"message": "Saved"},
    }

    monkeypatch.setattr(state.st, "session_state", session)

    state.clear_authenticated_session()

    assert state.SAVED_JOBS not in session
    assert state.SAVED_JOBS_USER_ID not in session
    assert state.SAVED_JOBS_NOTICE not in session
