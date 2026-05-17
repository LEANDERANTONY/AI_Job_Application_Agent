"""Contract test for `_validate_workspace_snapshot`.

The "persist a parsed résumé before any analysis runs" feature (so a
tab reload restores it, parity with the resume-builder) depends on a
specific, easily-broken contract: the saved-workspace validator must
accept a *résumé-only* snapshot — real `candidate_profile` /
`resume_document`, but the other required sections present only as
empty dicts (no analysis has run yet). The frontend builds exactly
that shape and POSTs it to /workspace/save.

If a future change makes `_validate_workspace_snapshot` require any of
those sections to be *non-empty*, the provisional résumé save would
start 4xx-ing silently and the reload-restore would regress. These
hermetic tests (pure function, no Supabase) pin the contract.
"""
from __future__ import annotations

import pytest

from backend.services.workspace_persistence_service import (
    _validate_workspace_snapshot,
)

# The 5 sections the validator requires to each be a dict.
_REQUIRED = [
    "candidate_profile",
    "job_description",
    "fit_analysis",
    "tailored_draft",
    "artifacts",
]


def _resume_only_snapshot() -> dict:
    """Mirrors what the frontend résumé-autosave effect sends: real
    résumé sections, the rest present as empty dicts."""
    return {
        "resume_document": {"filetype": "pdf", "text": "…"},
        "candidate_profile": {"full_name": "Leander Antony", "skills": ["Python"]},
        "job_description": {},
        "jd_summary_view": {},
        "fit_analysis": {},
        "tailored_draft": {},
        "agent_result": None,
        "artifacts": {},
        "workflow": {},
    }


def test_resume_only_snapshot_passes_validation():
    # The load-bearing assertion: empty {} for the not-yet-existing
    # sections satisfies the isinstance(dict) check, so a parsed-résumé
    # snapshot persists fine before any analysis.
    payload = _validate_workspace_snapshot(_resume_only_snapshot())
    assert payload["candidate_profile"]["full_name"] == "Leander Antony"
    for section in _REQUIRED:
        assert isinstance(payload[section], dict)


@pytest.mark.parametrize("missing", _REQUIRED)
def test_missing_required_section_still_rejected(missing):
    # The relax is "empty dict is OK", NOT "anything goes" — a section
    # that isn't a dict at all must still raise (the validator stays a
    # real guard).
    snap = _resume_only_snapshot()
    snap[missing] = None  # not a dict
    with pytest.raises(ValueError) as exc:
        _validate_workspace_snapshot(snap)
    assert missing in str(exc.value)


def test_absent_section_rejected():
    snap = _resume_only_snapshot()
    del snap["artifacts"]
    with pytest.raises(ValueError):
        _validate_workspace_snapshot(snap)
