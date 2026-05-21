"""Deterministic synonym / abbreviation expansion for job search.

A relevance audit of the cached-jobs search found it does zero
synonym handling: a search for "ml" and a search for "machine
learning" overlapped only 28%, and "swe" found just 53 of 5,346
software-engineer jobs. The fix here is a static, hand-curated
synonym map — no ML, no remote calls — applied to the raw query
before it reaches Postgres FTS.

`expand_query(raw)` lowercases + tokenizes the query, detects
cluster members LONGEST-MATCH-FIRST (so the multi-word "machine
learning" wins over the bare token "learning"), replaces each
matched term with an OR-group of its whole cluster, passes
unmatched tokens through, and returns a string in Postgres
`to_tsquery` syntax.

The output is fed to `to_tsquery('english', ...)` in the
`search_cached_jobs_ranked` RPC. `to_tsquery` is STRICT — it
raises on malformed input — so this module is careful to:
  * strip every character `to_tsquery` treats as an operator
    (`& | ! ( ) < > : ' "`) out of each token,
  * drop tokens that sanitize down to empty,
  * emit `''` (the empty string) for a query that has nothing
    searchable left (empty / all-punctuation / a lone stopword).
    The RPC treats an empty `p_query` as "no FTS filter" and
    returns recent jobs, so `''` is the correct degenerate output.

We deliberately do NOT pre-stem tokens — `to_tsquery('english',
...)` runs the english dictionary over each lexeme itself. This
module only builds the boolean/phrase OPERATOR STRUCTURE:
  * an OR-group  -> `(t1 | t2 | t3)`
  * a multi-word cluster member -> a phrase `word1<->word2`
  * AND between query parts -> `&`

Example: `expand_query("ml engineer")`
  -> `(ml | machine<->learning) & (engineer | developer | dev)`
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# The synonym clusters. Each inner list is a bidirectional equivalence
# class: if the query contains ANY member, the query part is expanded to
# an OR of ALL members. Members may be multi-word ("machine learning");
# those are matched as consecutive token sequences and emitted as
# `<->` phrases.
#
# DELIBERATELY EXCLUDED (do not add): `pm` (ambiguous — product /
# project / program manager), `fe` / `be` ("be" is an English word, so
# the cluster would pull in noise), `it` (English pronoun -> noise).
# ---------------------------------------------------------------------------

SYNONYM_CLUSTERS: list[list[str]] = [
    # -- Role abbreviations --------------------------------------------
    ["swe", "sde", "software engineer", "software developer"],
    ["sre", "site reliability engineer"],
    ["ae", "account executive"],
    ["sdr", "sales development representative"],
    ["bdr", "business development representative"],
    ["mle", "machine learning engineer"],
    ["tpm", "technical program manager"],
    ["csm", "customer success manager"],
    ["pmm", "product marketing manager"],
    ["ds", "data scientist"],
    ["da", "data analyst"],
    ["qa", "quality assurance"],
    ["sr", "senior"],
    ["jr", "junior"],
    ["vp", "vice president"],
    # -- Tech / skill terms -------------------------------------------
    ["ml", "machine learning"],
    ["ai", "artificial intelligence"],
    ["genai", "gen ai", "generative ai"],
    ["llm", "llms", "large language model"],
    ["nlp", "natural language processing"],
    ["k8s", "kubernetes"],
    ["js", "javascript"],
    ["ts", "typescript"],
    ["gtm", "go-to-market"],
    # -- Hyphenation / spacing variants -------------------------------
    ["frontend", "front-end", "front end"],
    ["backend", "back-end", "back end"],
    ["fullstack", "full-stack", "full stack"],
    ["devops", "dev ops"],
    # -- Generic equivalence (loosest cluster) ------------------------
    # Ordered engineer-first so the rendered OR-group reads
    # `(engineer | developer | dev)` — OR is commutative so order is
    # cosmetic, but this keeps the output matching the spec example.
    ["engineer", "developer", "dev"],
]


# Characters `to_tsquery` interprets as operators / syntax. Anything in
# this set is stripped from a token so the lexeme that reaches
# `to_tsquery` is a plain word. Hyphen is intentionally NOT here — see
# `_tokenize`, which splits on hyphens so "front-end" -> two tokens
# (the hyphenated cluster members are stored space-form anyway).
_TSQUERY_OPERATOR_CHARS = "&|!()<>:'\""

# Translation table that deletes every operator char in one pass.
_OPERATOR_STRIP_TABLE = {ord(ch): None for ch in _TSQUERY_OPERATOR_CHARS}

# Token splitter. We split on any run of whitespace OR hyphen so that
# "front-end" / "front end" / "go-to-market" all tokenize identically.
# Keeping this aligned with the way cluster members are normalized
# (see `_normalize_member`) is what makes hyphen variants match.
_TOKEN_SPLIT_RE = re.compile(r"[\s\-]+")


def _sanitize_token(token: str) -> str:
    """Reduce one raw token to a bare lexeme safe for `to_tsquery`.

    Strips the `to_tsquery` operator characters and surrounding
    whitespace. May return '' (caller drops empties).
    """
    return token.translate(_OPERATOR_STRIP_TABLE).strip()


def _tokenize(text: str) -> list[str]:
    """Lowercase, split on whitespace/hyphen, sanitize, drop empties."""
    lowered = str(text or "").lower()
    raw_tokens = _TOKEN_SPLIT_RE.split(lowered)
    tokens: list[str] = []
    for raw in raw_tokens:
        clean = _sanitize_token(raw)
        if clean:
            tokens.append(clean)
    return tokens


def _normalize_member(member: str) -> tuple[str, ...]:
    """Normalize a cluster member into a tuple of bare tokens.

    Uses the SAME tokenizer as the query so "front-end" and
    "front end" both reduce to ("front", "end") — that token-sequence
    equality is the whole mechanism by which hyphen variants match.
    """
    return tuple(_tokenize(member))


def _member_to_tsquery_term(member_tokens: tuple[str, ...]) -> str:
    """Render one cluster member (already token-tuple form) as a
    `to_tsquery` term: a single word stays a word; a multi-word member
    becomes a `<->` phrase (`word1<->word2`)."""
    return "<->".join(member_tokens)


def _build_cluster_index() -> tuple[
    dict[tuple[str, ...], list[str]], int
]:
    """Pre-compute the lookup used by `expand_query`.

    Returns:
      * a dict mapping each member's token-tuple -> the rendered
        `to_tsquery` OR-group for that member's whole cluster
        (e.g. ("ml",) -> "(ml | machine<->learning)"). A single-member
        cluster gets no parentheses — it's just the term.
      * the longest member length, in tokens — drives the
        longest-match-first window in `expand_query`.
    """
    index: dict[tuple[str, ...], list[str]] = {}
    max_len = 1
    for cluster in SYNONYM_CLUSTERS:
        # Normalize every member once; render the cluster's OR-group.
        normalized_members = [_normalize_member(m) for m in cluster]
        # Drop members that normalize to nothing (defensive — shouldn't
        # happen with the static data above).
        normalized_members = [m for m in normalized_members if m]
        if not normalized_members:
            continue
        terms = [_member_to_tsquery_term(m) for m in normalized_members]
        if len(terms) == 1:
            or_group = terms[0]
        else:
            or_group = "(" + " | ".join(terms) + ")"
        for member_tokens in normalized_members:
            # First cluster wins if a member somehow appears twice
            # across clusters (it doesn't in the static data, but keep
            # the behaviour deterministic).
            index.setdefault(member_tokens, [or_group])
            max_len = max(max_len, len(member_tokens))
    return index, max_len


# Built once at import — the cluster data is static.
_CLUSTER_INDEX, _MAX_MEMBER_TOKENS = _build_cluster_index()


def expand_query(raw_query: str) -> str:
    """Expand a raw job-search query into a `to_tsquery` string.

    Behaviour:
      * Tokenizes (lowercase, split on whitespace/hyphen, strip
        operator chars).
      * Walks the tokens left-to-right; at each position tries the
        LONGEST cluster member first (down to length 1) so multi-word
        members ("machine learning") beat their constituent words
        ("learning").
      * A matched span -> the cluster's OR-group `(a | b | c)`.
      * An unmatched token -> passed through verbatim.
      * Parts are joined with ` & ` (AND).

    Returns a string valid as input to `to_tsquery('english', ...)`.
    Returns `''` when nothing searchable survives (empty query,
    all-punctuation query, a single English stopword) — the RPC reads
    an empty `p_query` as "no FTS filter" and returns recent jobs, so
    `''` is the right degenerate result.

    When the query contains NO cluster term at all, the output is just
    the sanitized tokens AND-joined — still a valid `to_tsquery`
    string, just with no OR-groups.

    Note: this does NOT stem. `to_tsquery('english', ...)` applies the
    english dictionary to each lexeme itself; pre-stemming here would
    double-process and could corrupt the lexeme.
    """
    tokens = _tokenize(raw_query)
    if not tokens:
        return ""

    parts: list[str] = []
    i = 0
    n = len(tokens)
    while i < n:
        matched = False
        # Longest-match-first: try the widest window the data supports,
        # capped at what's left in the token stream.
        max_window = min(_MAX_MEMBER_TOKENS, n - i)
        for window in range(max_window, 0, -1):
            span = tuple(tokens[i : i + window])
            group = _CLUSTER_INDEX.get(span)
            if group is not None:
                parts.append(group[0])
                i += window
                matched = True
                break
        if not matched:
            # Unmatched token passes through verbatim. It's already
            # sanitized (operator chars stripped) by `_tokenize`.
            parts.append(tokens[i])
            i += 1

    if not parts:
        return ""
    return " & ".join(parts)
