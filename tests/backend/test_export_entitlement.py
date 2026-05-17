"""Export-entitlement gate (pricing-truth).

The landing pricing page promises Free "PDF export, ATS theme" and
Pro/Business "PDF + DOCX export, all themes". Before this gate that
differentiation was UNENFORCED -- any tier (and `/workspace/artifacts/
export` had no auth at all) could download DOCX / any theme, making
the Free vs Pro pricing bullets a fabricated claim.

`backend.tiers.export_entitlement_block_reason` is the policy (single
source of truth, lock-stepped with the pricing copy);
`backend.quota.enforce_export_entitlement` is the raiser that reuses
the canonical `QuotaExceededError` 429 path (exactly like the
`premium_applications` "Pro+ feature" rejection) so the frontend
renders the uniform upgrade nudge.

These tests are deliberately hermetic (pure functions, no Supabase /
OpenAI) so they run regardless of local `.env` credentials.
"""
from __future__ import annotations

import pytest

from backend.quota import enforce_export_entitlement
from backend.tiers import (
    FREE_EXPORT_FORMAT,
    FREE_EXPORT_THEME,
    export_entitlement_block_reason,
)
from src.errors import QuotaExceededError


# ── policy: export_entitlement_block_reason ─────────────────────────


def test_free_pdf_professional_neutral_is_allowed():
    # professional_neutral is the Free-tier theme (and the product
    # default). PDF + professional_neutral must pass cleanly.
    assert (
        export_entitlement_block_reason(
            "free",
            export_format="pdf",
            themes=("professional_neutral", "professional_neutral"),
        )
        is None
    )


def test_free_docx_is_blocked_with_docx_label():
    assert (
        export_entitlement_block_reason("free", export_format="docx")
        == "DOCX export"
    )


def test_free_non_default_theme_is_blocked_with_theme_label():
    # classic_ats is the Pro/Business-only alternate — blocked for Free.
    assert (
        export_entitlement_block_reason(
            "free", export_format="pdf", themes=("classic_ats",)
        )
        == "Custom export themes"
    )


def test_free_format_violation_takes_precedence_over_theme():
    # DOCX + a non-default theme: the format label is the one we surface.
    assert (
        export_entitlement_block_reason(
            "free", export_format="docx", themes=("classic_ats",)
        )
        == "DOCX export"
    )


def test_blank_or_default_values_never_upsell_free():
    # A caller omitting a theme (cover-letter export with default
    # resume_theme, etc.) must not be upsold.
    assert export_entitlement_block_reason("free") is None
    assert (
        export_entitlement_block_reason(
            "free", export_format="", themes=("", "   ")
        )
        is None
    )


def test_free_comparison_is_case_and_whitespace_insensitive():
    # Mirrors the request models' _strip_theme normalisation.
    assert (
        export_entitlement_block_reason(
            "free", export_format="  PDF ", themes=("  Professional_Neutral  ",)
        )
        is None
    )


@pytest.mark.parametrize("tier", ["pro", "business"])
def test_paid_tiers_have_full_entitlement(tier):
    assert (
        export_entitlement_block_reason(
            tier, export_format="docx", themes=("professional_neutral",)
        )
        is None
    )


def test_free_constants_match_pricing_copy():
    # If these change, the Free pricing bullet ("PDF export,
    # Professional theme") changed too -- a pricing decision, caught
    # here. professional_neutral is also the product-wide default.
    assert FREE_EXPORT_FORMAT == "pdf"
    assert FREE_EXPORT_THEME == "professional_neutral"


# ── raiser: enforce_export_entitlement ──────────────────────────────


def test_enforce_allows_free_pdf_professional_neutral():
    # No exception == allowed (Free's PDF + professional_neutral).
    enforce_export_entitlement(
        "free", export_format="pdf", themes=("professional_neutral",)
    )


@pytest.mark.parametrize("tier", ["pro", "business"])
def test_enforce_allows_paid_docx(tier):
    enforce_export_entitlement(
        tier, export_format="docx", themes=("professional_neutral",)
    )


def test_enforce_blocks_free_docx_as_quota_error():
    with pytest.raises(QuotaExceededError) as exc_info:
        enforce_export_entitlement("free", export_format="docx")
    err = exc_info.value
    # Reuses the canonical 429 shape (same as premium_applications):
    assert err.tier == "free"
    assert err.counter == "premium_export"
    assert err.cap == 0
    assert err.current == 0
    # lifetime, NOT a monthly counter -> frontend won't render a wrong
    # "resets on the 1st" line.
    assert err.reset_period == "lifetime"
    assert "Pro+" in err.user_message


def test_enforce_blocks_free_non_default_theme():
    # classic_ats is the Pro/Business-only alternate — Free is blocked.
    with pytest.raises(QuotaExceededError):
        enforce_export_entitlement(
            "free", export_format="pdf", themes=("classic_ats",)
        )
