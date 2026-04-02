from src.job_sources.matching import detect_role_families, title_matches_role_families


def test_detect_role_families_frontend_query():
    families = detect_role_families("frontend engineer")

    assert "frontend" in families


def test_title_matches_frontend_family_for_web_engineer_titles():
    families = detect_role_families("frontend engineer")

    assert title_matches_role_families("Senior Web Engineer", families) is True
    assert title_matches_role_families("UI Engineer", families) is True


def test_title_matches_data_science_family_for_decision_scientist_titles():
    families = detect_role_families("data scientist")

    assert title_matches_role_families("Senior Decision Scientist", families) is True
    assert title_matches_role_families("Lead Statistician", families) is True


def test_ai_engineering_family_requires_real_engineering_signal():
    families = detect_role_families("ai engineer")

    assert title_matches_role_families("Applied AI, Forward Deployed AI Engineer", families) is True
    assert title_matches_role_families("Staff Product Manager, Applied AI", families) is False
