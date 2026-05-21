"""Tests for src/job_search_synonyms.py — deterministic query expansion.

Covers each cluster type, multi-word members, longest-match-first,
unmatched-token passthrough, and the degenerate inputs (empty /
all-punctuation / lone stopword) that must collapse to '' so the RPC
short-circuits the FTS filter.

The expansion output must be valid input to Postgres
`to_tsquery('english', ...)`. We don't have a live Postgres here, so
a regex-based `_assert_tsquery_shaped` proxy checks the structural
invariants `to_tsquery` cares about: no stray operator chars in
lexemes, balanced parens, no dangling operators. The task's
before/after probes against the real Supabase project exercise the
genuine `to_tsquery` parser.
"""
from __future__ import annotations

import re

import pytest

from src.job_search_synonyms import (
    SYNONYM_CLUSTERS,
    _build_cluster_index,
    expand_query,
)


# ---------------------------------------------------------------------------
# Helper: a structural sanity check for to_tsquery-shaped output.
# ---------------------------------------------------------------------------


def _assert_tsquery_shaped(expr: str, allow_chars: str = "") -> None:
    """Assert `expr` looks like valid `to_tsquery` input.

    Empty string is explicitly valid (the RPC treats it as "no FTS
    filter"). Otherwise: balanced parens, only the allowed operator
    set, lexemes are bare words, and no dangling/leading operators.

    `allow_chars` widens the lexeme charset for the rare token (like
    "c++") that contains a non-operator punctuation char `to_tsquery`
    tolerates because the english dictionary normalises it.
    """
    if expr == "":
        return  # empty is a valid degenerate output

    # Balanced parentheses.
    depth = 0
    for ch in expr:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        assert depth >= 0, f"unbalanced parens in {expr!r}"
    assert depth == 0, f"unbalanced parens in {expr!r}"

    # Strip the structural tokens; whatever remains must be bare
    # word-lexemes (letters/digits — to_tsquery would choke on the
    # operator chars &|!():<>'" embedded in a lexeme).
    lexemes = re.sub(r"[()|&]|<->", " ", expr).split()
    assert lexemes, f"no lexemes in {expr!r}"
    lexeme_pattern = re.compile("[a-z0-9" + re.escape(allow_chars) + "]+")
    for lex in lexemes:
        assert lexeme_pattern.fullmatch(lex), (
            f"lexeme {lex!r} in {expr!r} contains a to_tsquery operator char"
        )

    # No operator may sit at the very start/end or be doubled.
    assert not re.match(r"^\s*[&|]", expr), f"leading operator in {expr!r}"
    assert not re.search(r"[&|]\s*$", expr), f"trailing operator in {expr!r}"
    assert not re.search(r"[&|]\s*[&|]", expr), f"doubled operator in {expr!r}"
    # An OR-group must never be empty: `()` is illegal.
    assert "()" not in expr.replace(" ", ""), f"empty group in {expr!r}"


# ---------------------------------------------------------------------------
# Degenerate inputs -> '' (RPC reads this as "no FTS filter").
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        None,
        "!!!",
        "()&|<>:",
        "   &  ",
        '"" \'\'',
    ],
)
def test_empty_and_punctuation_inputs_collapse_to_empty(raw):
    """Empty / whitespace / all-punctuation queries yield '' — the RPC
    short-circuits the FTS filter and returns recent jobs."""
    assert expand_query(raw) == ""


def test_lone_stopword_passes_through_but_stays_tsquery_valid():
    """A single English stopword like "the" isn't a cluster term, so it
    passes through as a plain lexeme. `to_tsquery('english','the')`
    yields an empty tsquery server-side (the english dict drops
    stopwords) — which the RPC then treats as no-match-everything; the
    point of THIS test is only that the string we hand to to_tsquery is
    structurally legal, not empty-mapped here."""
    result = expand_query("the")
    # We don't pre-stem or pre-drop stopwords — that's to_tsquery's job.
    assert result == "the"
    _assert_tsquery_shaped(result)


# ---------------------------------------------------------------------------
# Each cluster type expands.
# ---------------------------------------------------------------------------


def test_role_abbreviation_expands_to_full_cluster():
    """`swe` -> the whole {swe, sde, software engineer, software
    developer} cluster as an OR-group, multi-word members as phrases."""
    result = expand_query("swe")
    assert result == "(swe | sde | software<->engineer | software<->developer)"
    _assert_tsquery_shaped(result)


def test_tech_term_abbreviation_expands():
    """`ml` -> {ml, machine learning}."""
    result = expand_query("ml")
    assert result == "(ml | machine<->learning)"
    _assert_tsquery_shaped(result)


def test_k8s_expands_to_kubernetes():
    result = expand_query("k8s")
    assert result == "(k8s | kubernetes)"
    _assert_tsquery_shaped(result)


def test_hyphenation_variant_query_matches_cluster():
    """A hyphenated query term ("front-end") tokenizes the same as
    "front end" / "frontend" and expands to the full cluster."""
    for variant in ("frontend", "front-end", "front end", "FRONT-END"):
        result = expand_query(variant)
        assert result == "(frontend | front<->end | front<->end)", variant
        _assert_tsquery_shaped(result)


def test_generic_equivalence_cluster_expands():
    """The loosest cluster: {engineer, developer, dev}. Any member
    expands to the same OR-group (rendered engineer-first)."""
    expected = "(engineer | developer | dev)"
    assert expand_query("developer") == expected
    assert expand_query("dev") == expected
    assert expand_query("engineer") == expected
    _assert_tsquery_shaped(expected)


def test_genai_three_member_spacing_cluster():
    """`genai` / `gen ai` / `generative ai` all reach the same group."""
    expected = "(genai | gen<->ai | generative<->ai)"
    assert expand_query("genai") == expected
    assert expand_query("gen ai") == expected
    assert expand_query("generative ai") == expected
    _assert_tsquery_shaped(expected)


# ---------------------------------------------------------------------------
# Multi-word cluster members.
# ---------------------------------------------------------------------------


def test_multiword_member_matched_as_token_sequence():
    """"machine learning" (a multi-word member of the {ml, machine
    learning} cluster) is matched as a 2-token sequence and expands to
    the same OR-group `ml` does."""
    result = expand_query("machine learning")
    assert result == "(ml | machine<->learning)"
    _assert_tsquery_shaped(result)


def test_multiword_member_emitted_as_phrase_operator():
    """A multi-word member inside an OR-group is a `<->` phrase, so the
    words must stay adjacent in the document to match."""
    result = expand_query("mle")
    assert result == "(mle | machine<->learning<->engineer)"
    assert "machine<->learning<->engineer" in result
    _assert_tsquery_shaped(result)


# ---------------------------------------------------------------------------
# Longest-match-first.
# ---------------------------------------------------------------------------


def test_longest_match_machine_learning_beats_bare_learning():
    """"machine learning engineer" must match the 3-token member
    "machine learning engineer" (the {mle, ...} cluster), NOT
    decompose into {ml,...} + a bare "engineer". Longest window wins."""
    result = expand_query("machine learning engineer")
    assert result == "(mle | machine<->learning<->engineer)"
    _assert_tsquery_shaped(result)


def test_longest_match_then_remaining_token_still_expands():
    """"ml engineer" — "machine learning engineer" is NOT present as a
    contiguous span, so position 0 matches the 1-token "ml" and
    position 1 separately matches "engineer". Both expand; AND-joined.
    This is the task's canonical example."""
    result = expand_query("ml engineer")
    assert result == "(ml | machine<->learning) & (engineer | developer | dev)"
    _assert_tsquery_shaped(result)


def test_longest_match_software_engineer_is_one_span_not_two():
    """"software engineer" is a single 2-token member of the {swe,...}
    cluster — it must NOT be read as "software" + the {engineer,...}
    cluster. So the output is the swe-cluster group ONLY, not a
    2-part AND."""
    result = expand_query("software engineer")
    assert result == "(swe | sde | software<->engineer | software<->developer)"
    assert " & " not in result  # single span, no AND
    _assert_tsquery_shaped(result)


# ---------------------------------------------------------------------------
# Unmatched-token passthrough + mixed queries.
# ---------------------------------------------------------------------------


def test_query_with_no_cluster_term_is_plain_and_joined():
    """No cluster term anywhere -> sanitized tokens AND-joined, still a
    valid to_tsquery string with no OR-groups."""
    result = expand_query("staff product manager")
    assert result == "staff & product & manager"
    _assert_tsquery_shaped(result)


def test_unmatched_tokens_pass_through_around_a_match():
    """Unmatched tokens are kept verbatim; matched ones expand;
    everything AND-joins in original order."""
    result = expand_query("remote ml role")
    assert result == "remote & (ml | machine<->learning) & role"
    _assert_tsquery_shaped(result)


def test_single_unmatched_token_is_returned_bare():
    result = expand_query("kubernetes-administrator-wizard".replace("-", " "))
    # "kubernetes" is a cluster member; the other two are not.
    assert result == "(k8s | kubernetes) & administrator & wizard"
    _assert_tsquery_shaped(result)


def test_operator_chars_in_query_are_stripped_not_passed_through():
    """A user pasting `c++ & python!` must not break to_tsquery — the
    tsquery operator chars (`&`, `!`) get stripped here, and the `+`
    in "c++" is harmless because the english dict in
    `to_tsquery('english', ...)` strips it server-side (verified by
    probe: `to_tsquery('english','c++')` -> `'c'`)."""
    result = expand_query("c++ & python!")
    # `&` and `!` removed (tsquery operators); `+` is not a tsquery
    # operator so "c++" passes through — to_tsquery normalises it.
    assert result == "c++ & python"
    _assert_tsquery_shaped(result, allow_chars="+")


def test_excluded_terms_are_not_clusters():
    """`pm`, `fe`, `be`, `it` were deliberately excluded — they must
    pass through as plain tokens, NOT expand."""
    for term in ("pm", "fe", "be", "it"):
        result = expand_query(term)
        assert result == term, f"{term!r} should not expand"
        _assert_tsquery_shaped(result)


def test_case_insensitive_matching():
    """Cluster detection is case-insensitive."""
    assert expand_query("ML") == "(ml | machine<->learning)"
    assert expand_query("Machine Learning") == "(ml | machine<->learning)"
    assert expand_query("SWE") == (
        "(swe | sde | software<->engineer | software<->developer)"
    )


def test_go_to_market_hyphenated_member():
    """`gtm` / `go-to-market` — the hyphenated 3-token member."""
    expected = "(gtm | go<->to<->market)"
    assert expand_query("gtm") == expected
    assert expand_query("go-to-market") == expected
    _assert_tsquery_shaped(expected)


def test_two_multiword_clusters_in_one_query():
    """"senior data scientist" — "senior" ({sr,senior}) then "data
    scientist" ({ds, data scientist}). Two expansions, AND-joined."""
    result = expand_query("senior data scientist")
    assert result == "(sr | senior) & (ds | data<->scientist)"
    _assert_tsquery_shaped(result)


# ---------------------------------------------------------------------------
# Cluster-data integrity (cheap guards against future edits).
# ---------------------------------------------------------------------------


def test_every_cluster_member_round_trips_through_expand_query():
    """Each member of each cluster, when used alone as the query,
    expands to its cluster's OR-group and yields tsquery-valid output.
    Catches a typo / stray operator char in the static data."""
    for cluster in SYNONYM_CLUSTERS:
        for member in cluster:
            result = expand_query(member)
            _assert_tsquery_shaped(result)
            if len(cluster) > 1:
                # Multi-member cluster -> parenthesised OR-group.
                assert result.startswith("(") and result.endswith(")"), (
                    f"{member!r} -> {result!r}"
                )
                assert "|" in result


def test_excluded_terms_absent_from_cluster_data():
    """Belt-and-braces: the deliberately-excluded ambiguous/noisy
    abbreviations must not appear as members anywhere."""
    all_members = {m.lower() for cluster in SYNONYM_CLUSTERS for m in cluster}
    for banned in ("pm", "fe", "be", "it"):
        assert banned not in all_members


def test_cluster_index_max_member_length_is_at_least_three():
    """The index drives the longest-match window; the data has 3-token
    members ("machine learning engineer", "go-to-market"), so the
    computed max must be >= 3 or longest-match would silently miss."""
    _index, max_len = _build_cluster_index()
    assert max_len >= 3
