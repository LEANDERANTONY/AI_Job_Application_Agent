"""/workspace/quota counts the saved workspace cheaply (M4).

The saved_workspaces persistent count used load_workspace, which selects the
heavy workflow_snapshot / cover-letter / résumé JSON blobs — tens-to-hundreds
of KB — just to derive a 0/1. This endpoint is polled on every workspace
mount and after every run, so it now uses a lightweight count_active read.
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.services import workspace_quota_service as svc


def test_persistent_count_for_workspaces_uses_lightweight_count(monkeypatch):
    class _FakeStore:
        def __init__(self, *args, **kwargs):
            pass

        def is_configured(self):
            return True

        def count_active(self, access_token, refresh_token, user_id, now=None):
            return 1

        def load_workspace(self, *args, **kwargs):
            raise AssertionError(
                "load_workspace (heavy blob read) must not be called — M4"
            )

    monkeypatch.setattr(svc, "SavedWorkspaceStore", _FakeStore)

    auth_context = SimpleNamespace(
        app_user=SimpleNamespace(id="u1"),
        auth_service=SimpleNamespace(),
    )

    result = svc._persistent_count(
        counter_name="saved_workspaces",
        auth_context=auth_context,
        access_token="a",
        refresh_token="r",
        cap=1,
    )

    # count_active was used (1); load_workspace would have raised.
    assert result == 1
