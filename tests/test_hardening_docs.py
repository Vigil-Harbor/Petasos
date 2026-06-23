"""Recurrence guard for the multi-home config-hardening guidance (PET-150).

Both ``docs/deployment/hardening.md`` § 6 and ``docs/security-hardening-checklist.md``
§ 7 (footgun 4c) tell the operator to put Petasos's ``config.yaml`` out of the
agent's reach. PET-150 widened that boundary from the single resolved active
config to *every* profile home (``profiles/*/config.yaml``, ``HERMES_HOME``, the
legacy root), because PET-146's Config Editor selector makes every home an
editable surface, and an agent that pre-stages a relaxed non-active config arms it
on the next operator equip or PET-147 live swap. This file reds if either doc ever
re-narrows that guidance, drops the pre-stage threat statement, or claims the
boundary is guard-side write-blocklisting rather than deployment posture (PET-125
Decision 2 preserved).

The assertion keys off stable ``petasos-doc-assert`` HTML-comment markers (the
PET-128 convention), not fragile prose substrings: markers survive prose
rewording. This is a pure-stdlib base-lane test (no ``petasos`` import, no ML
extras), so it runs in the default ``ci.yml`` lane (PET-106).

Known limit (honest): the marker asserts the authored posture tag, not the
surrounding prose, so a careless narrowing that left the marker intact would not
red. The reviewer confirms prose == marker once at authoring; a light prose-anchor
backstop is deferred (spec § Deferred).
"""

from __future__ import annotations

from pathlib import Path

import pytest

# The marker sentinel, identical to the literal embedded in the Markdown docs and
# to the PET-128 sibling suite (``test_docs_usage_consistency.py``). The grammar
# is re-implemented here rather than imported to keep this doc-led guard
# self-contained (spec Decision 1).
_MARKER_PREFIX = "petasos-doc-assert:"

_REPO_ROOT = Path(__file__).resolve().parent.parent
_HARDENING_DOC = _REPO_ROOT / "docs" / "deployment" / "hardening.md"
_CHECKLIST_DOC = _REPO_ROOT / "docs" / "security-hardening-checklist.md"

# Both guarded docs, parametrized by a readable id so a failure names the file.
_GUARDED_DOCS = [
    pytest.param(_HARDENING_DOC, id="hardening.md"),
    pytest.param(_CHECKLIST_DOC, id="security-hardening-checklist.md"),
]


def _doc_assert_markers(path: Path, *, required: frozenset[str]) -> dict[str, str]:
    """Parse ``petasos-doc-assert`` markers from one doc into ``{key: value}``.

    A marker line is ``<sentinel> <pair> [<pair> ...]`` where each ``<pair>`` is
    ``key=value``; tokens split on whitespace, then on the first ``=``. This parses
    one doc at a time and never pools two files' markers, so a per-doc divergence
    reds the offending doc instead of masquerading as a duplicate-key error.

    Fail-loud, mirroring the PET-128 parser:
      * a token with no ``=`` raises;
      * an empty value, or an empty CSV element, raises;
      * a duplicate key anywhere in the file raises;
      * any key in ``required`` absent from the parsed markers raises, naming the
        missing key, so a deleted marker reds with a message rather than a bare
        ``KeyError`` at the call site.
    """
    parsed: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if _MARKER_PREFIX not in raw_line:
            continue
        # Text after the sentinel, then drop the HTML-comment close.
        segment = raw_line.split(_MARKER_PREFIX, 1)[1].split("-->", 1)[0].strip()
        for token in segment.split():
            if "=" not in token:
                raise ValueError(
                    f"malformed doc-assert token {token!r} in {path.name} (expected key=value)"
                )
            key, value = token.split("=", 1)
            if not value:
                raise ValueError(f"empty value for doc-assert key {key!r} in {path.name}")
            if "," in value and any(part == "" for part in value.split(",")):
                raise ValueError(f"empty CSV element in doc-assert key {key!r} in {path.name}")
            if key in parsed:
                raise ValueError(f"duplicate doc-assert key {key!r} in {path.name}")
            parsed[key] = value
    missing = required - parsed.keys()
    if missing:
        raise ValueError(f"missing required doc-assert key(s) {sorted(missing)} in {path.name}")
    return parsed


@pytest.mark.parametrize("doc", _GUARDED_DOCS)
def test_hardening_doc_scopes_all_profile_homes(doc: Path) -> None:
    # Regression for PET-150: both docs must scope the deny-write boundary to all
    # profile homes and name the pre-stage-on-equip/swap threat. A silent
    # re-narrowing to the active profile reds here.
    required = frozenset({"multihome_config_unreachable", "multihome_prestage_threat"})
    markers = _doc_assert_markers(doc, required=required)
    assert markers["multihome_config_unreachable"] == "all-profile-homes"
    assert markers["multihome_prestage_threat"] == "equip-or-live-swap"


@pytest.mark.parametrize("doc", _GUARDED_DOCS)
def test_hardening_doc_no_guard_blocklist_claim(doc: Path) -> None:
    # Regression for PET-150 (Decision 2): the boundary is deployment posture, not
    # guard-side write-blocklisting (PET-125 Decision 2 preserved). A positive
    # marker locks the posture; an edit that claimed the guard enforces the
    # boundary would have to flip this value to one the assert rejects.
    markers = _doc_assert_markers(doc, required=frozenset({"config_boundary_mechanism"}))
    assert markers["config_boundary_mechanism"] == "deployment-posture"


# --- New-parser fail-loud contract ------------------------------------------
# The sibling PET-128 tests cover a *different* parser function, so this self-
# contained reader needs its own fail-loud coverage (spec Decision 1).


def _write(tmp_path: Path, body: str) -> Path:
    doc = tmp_path / "fixture.md"
    doc.write_text(body, encoding="utf-8")
    return doc


def test_parser_raises_on_malformed_token(tmp_path: Path) -> None:
    doc = _write(tmp_path, "<!-- petasos-doc-assert: novalue -->\n")
    with pytest.raises(ValueError, match="malformed doc-assert token"):
        _doc_assert_markers(doc, required=frozenset())


def test_parser_raises_on_empty_value(tmp_path: Path) -> None:
    doc = _write(tmp_path, "<!-- petasos-doc-assert: k= -->\n")
    with pytest.raises(ValueError, match="empty value"):
        _doc_assert_markers(doc, required=frozenset({"k"}))


def test_parser_raises_on_empty_csv_element(tmp_path: Path) -> None:
    doc = _write(tmp_path, "<!-- petasos-doc-assert: k=a,,b -->\n")
    with pytest.raises(ValueError, match="empty CSV element"):
        _doc_assert_markers(doc, required=frozenset({"k"}))


def test_parser_raises_on_duplicate_key(tmp_path: Path) -> None:
    doc = _write(
        tmp_path,
        "<!-- petasos-doc-assert: k=1 -->\n<!-- petasos-doc-assert: k=2 -->\n",
    )
    with pytest.raises(ValueError, match="duplicate doc-assert key"):
        _doc_assert_markers(doc, required=frozenset({"k"}))


def test_parser_raises_on_missing_required_key(tmp_path: Path) -> None:
    doc = _write(tmp_path, "<!-- petasos-doc-assert: present=1 -->\n")
    with pytest.raises(ValueError, match="missing required doc-assert key"):
        _doc_assert_markers(doc, required=frozenset({"absent"}))
