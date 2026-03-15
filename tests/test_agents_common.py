from src.agents.common import coerce_bool, coerce_string, coerce_string_list, unique_strings


def test_coerce_string_helpers_normalize_and_dedupe():
    assert coerce_string(None, default="fallback") == "fallback"
    assert coerce_string("  value  ") == "value"
    assert coerce_string_list([" Python ", "python", "SQL"], limit=5) == ["Python", "SQL"]
    assert unique_strings(["Docker", "docker", " SQL "], limit=5) == ["Docker", "SQL"]


def test_coerce_string_list_rejects_non_lists_and_coerce_bool_handles_common_tokens():
    assert coerce_string_list("not-a-list") == []
    assert coerce_bool(True) is True
    assert coerce_bool(" yes ") is True
    assert coerce_bool("0") is False
    assert coerce_bool("maybe") is False
