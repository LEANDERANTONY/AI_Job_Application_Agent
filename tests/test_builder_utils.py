from src.utils import markdown_to_text, render_markdown_list, safe_join_strings, slugify_text


def test_slugify_text_uses_fallback_for_empty_values():
    assert slugify_text("", fallback="default-name") == "default-name"
    assert slugify_text("Senior Data Analyst", fallback="default-name") == "senior-data-analyst"


def test_safe_join_strings_deduplicates_and_limits():
    result = safe_join_strings(["Python", "python", "SQL", "Python", "Tableau"], limit=2)

    assert result == "Python, SQL"


def test_render_markdown_list_returns_empty_state_for_empty_input():
    assert render_markdown_list([], "Nothing here") == "- Nothing here"


def test_markdown_to_text_supports_bullet_conversion_and_bold_stripping():
    markdown = "# Title\n\n- First\n- Second\n\n**Bold** line"

    assert markdown_to_text(markdown, bullet_marker="*") == "Title\n\n* First\n* Second\n\n**Bold** line"
    assert markdown_to_text(markdown, strip_bold=True) == "Title\n\n- First\n- Second\n\nBold line"