"""Doc/source consistency tests for the user-facing usage pages (PET-128).

The pages under ``docs/usage/`` state load-bearing numbers and lists in human
prose (for example "22 rules across 5 families"). Prose drifts silently from the
code it describes -- the "17 rules" stale-count class of bug. To stop that, each
page embeds machine-readable markers next to the prose. The markers are HTML
comments, invisible in rendered Markdown and on GitHub::

    <!-- petasos-doc-assert: rule_taxonomy_total=22 -->
    <!-- petasos-doc-assert: presidio_opt_in=PERSON,LOCATION,DATE_TIME,NRP,URL -->

``_parse_doc_asserts`` parses the markers and fails loudly (duplicate key, empty
value, missing required key all raise). Each test then compares the parsed values
to the imported source using the comparison mode pinned for that key: integer
equality, an ordered list, or set membership. The reviewer confirms prose ==
marker once at authoring; these tests guarantee marker == source forever.

All imports are base-safe module-level constants (no ML extras), so this file
runs in the default ``ci.yml`` lane (PET-106: ``console`` is not a scanner, so no
new extras lane is needed).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from petasos.console._config_meta import _FIELD_META, _SECTION_REGISTRY
from petasos.scanners.llama_firewall import _COMPONENT_TAXONOMY
from petasos.scanners.minimal import (
    _AGENT_DIRECTIVE_RULE_IDS,
    _COMMAND_RULE_IDS,
    _ENCODING_RULE_IDS,
    _INJECTION_RULE_IDS,
    _ROLE_SWITCH_RULE_IDS,
    _STRUCTURAL_RULE_IDS,
    RULE_TAXONOMY,
)
from petasos.scanners.presidio import (
    DEFAULT_PRESIDIO_ENTITIES,
    NOISY_OPT_IN_ENTITIES,
)

# Single source of truth for the marker sentinel. The Markdown pages MUST use
# this identical literal; the parser keys off it.
_MARKER_PREFIX = "petasos-doc-assert:"

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCANNERS_DOC = _REPO_ROOT / "docs" / "usage" / "scanners.md"
_CONFIG_DOC = _REPO_ROOT / "docs" / "usage" / "configuration.md"
_CONSOLE_JS = _REPO_ROOT / "petasos" / "console" / "static" / "petasos.js"


def _parse_doc_asserts(
    path: Path,
    *,
    required: frozenset[str],
    int_keys: frozenset[str] = frozenset(),
) -> dict[str, str]:
    """Parse ``petasos-doc-assert`` markers from ``path`` into a flat dict.

    A marker line is ``<prefix> <pair> [<pair> ...]`` where each ``<pair>`` is
    ``key=value``. Tokens split on whitespace, then on the first ``=``. Multiple
    pairs per line are allowed (the ``rule_family.*`` marker); a value containing
    commas is a CSV. Because tokens split on whitespace, CSV values can never
    contain spaces.

    Fails loudly, never silently:
      * a token with no ``=`` raises;
      * an empty value, or an empty CSV element, raises;
      * a key in ``int_keys`` whose value is not a base-10 integer raises;
      * a duplicate key anywhere in the file raises (drift cannot hide behind a
        second copy);
      * any key in ``required`` absent from the parsed markers raises, naming the
        missing key -- so a deleted marker reds its test rather than yielding a
        silent zero-assertion pass.
    """
    parsed: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if _MARKER_PREFIX not in raw_line:
            continue
        # Take the text after the sentinel, then drop the HTML-comment close.
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
            if key in int_keys and not _is_int(value):
                raise ValueError(
                    f"doc-assert key {key!r} expected an integer, got {value!r} in {path.name}"
                )
            if key in parsed:
                raise ValueError(f"duplicate doc-assert key {key!r} in {path.name}")
            parsed[key] = value
    missing = required - parsed.keys()
    if missing:
        raise ValueError(f"missing required doc-assert key(s) {sorted(missing)} in {path.name}")
    return parsed


def _is_int(value: str) -> bool:
    try:
        int(value)
    except ValueError:
        return False
    return True


def _csv(parsed: dict[str, str], key: str) -> list[str]:
    return parsed[key].split(",")


# The seven marker keys the rule-count test requires, bridged to their source
# frozensets. The bridge is explicit (not inferred from the keys present in the
# file) so a deleted marker is caught by the required-key contract, and so the
# marker key ``role_switch`` maps unambiguously to ``_ROLE_SWITCH_RULE_IDS``.
_RULE_FAMILY_SOURCE: dict[str, frozenset[str]] = {
    "rule_family.injection": _INJECTION_RULE_IDS,
    "rule_family.role_switch": _ROLE_SWITCH_RULE_IDS,
    "rule_family.structural": _STRUCTURAL_RULE_IDS,
    "rule_family.encoding": _ENCODING_RULE_IDS,
    "rule_family.command": _COMMAND_RULE_IDS,
    "rule_family.agent_directive": _AGENT_DIRECTIVE_RULE_IDS,
}


def test_docs_scanner_rule_count_matches_taxonomy() -> None:
    # Regression for PET-128: scanners.md must pin the real MinimalScanner
    # taxonomy. Adding/removing a rule without updating the doc reds this.
    required = frozenset({"rule_taxonomy_total", *_RULE_FAMILY_SOURCE})
    parsed = _parse_doc_asserts(_SCANNERS_DOC, required=required, int_keys=required)
    assert int(parsed["rule_taxonomy_total"]) == len(RULE_TAXONOMY)
    for marker_key, source_ids in _RULE_FAMILY_SOURCE.items():
        assert int(parsed[marker_key]) == len(source_ids), marker_key
    # The six families partition the taxonomy: their lengths sum to the total.
    # So moving a rule between families reds a per-family marker even though the
    # total is unchanged.
    assert sum(len(ids) for ids in _RULE_FAMILY_SOURCE.values()) == len(RULE_TAXONOMY)


def test_docs_llamafirewall_components_match_source() -> None:
    # Regression for PET-128: the three named LlamaFirewall components.
    parsed = _parse_doc_asserts(_SCANNERS_DOC, required=frozenset({"llamafirewall_components"}))
    assert set(_csv(parsed, "llamafirewall_components")) == set(_COMPONENT_TAXONOMY.keys())


def test_docs_presidio_default_set_matches_source() -> None:
    # Regression for PET-128: the Presidio default vs opt-in entity bands.
    # Compared as sets; the source tuples' order is not a documented contract,
    # so a benign source reorder must not red this test.
    parsed = _parse_doc_asserts(
        _SCANNERS_DOC,
        required=frozenset({"presidio_default", "presidio_opt_in"}),
    )
    assert set(_csv(parsed, "presidio_default")) == set(DEFAULT_PRESIDIO_ENTITIES)
    assert set(_csv(parsed, "presidio_opt_in")) == set(NOISY_OPT_IN_ENTITIES)


def test_docs_config_sections_match_meta() -> None:
    # Regression for PET-128: configuration.md must match the editor's sections
    # (in render order) and document every editor-surfaced field.
    parsed = _parse_doc_asserts(
        _CONFIG_DOC,
        required=frozenset({"config_sections", "config_field_count", "config_fields"}),
        int_keys=frozenset({"config_field_count"}),
    )

    registry_order = [section.key for section in _SECTION_REGISTRY]

    # (a) section list, in render order (tuple position is the contract).
    assert _csv(parsed, "config_sections") == registry_order

    # (b) the human-facing field count equals the live field total.
    assert int(parsed["config_field_count"]) == len(_FIELD_META)

    # (c) every field's `section` value has a registry entry. Closes the gap
    # where a field could carry a section value with no registry entry (the
    # "unknown" sentinel) yet still count toward the total.
    assert {meta["section"] for meta in _FIELD_META.values()} == set(registry_order)

    # (d) documented field set matches the live field set, bidirectionally, over
    # the author-maintained config_fields marker (not an open-ended scan of every
    # backtick span, which would false-positive on profile/section/enum spans).
    documented = _csv(parsed, "config_fields")
    assert set(documented) == set(_FIELD_META)
    assert int(parsed["config_field_count"]) == len(documented)

    # Forward prose coverage: each documented field appears as a backtick-
    # delimited token in the prose (marker lines excluded). Backtick delimiting
    # is required because `presidio_entities` is a substring of
    # `presidio_entities_extra`; a bare substring match would let the longer
    # field satisfy the shorter field's check.
    prose = "\n".join(
        line
        for line in _CONFIG_DOC.read_text(encoding="utf-8").splitlines()
        if _MARKER_PREFIX not in line
    )
    for name in documented:
        assert f"`{name}`" in prose, name


def test_docs_links_present_in_console_js() -> None:
    # Regression for PET-128: the About tab links both usage pages. String pin
    # only (no DOM/JS execution); guards the surfacing edit against silent loss.
    js = _CONSOLE_JS.read_text(encoding="utf-8")
    assert "docs/usage/scanners.md" in js
    assert "docs/usage/configuration.md" in js


# --- Parser fail-loud contract (the silent-drift guard itself) --------------
# These exercise the three drift shapes the suite must catch beyond value flips
# (which the source-comparison tests above catch structurally): a deleted marker
# (missing required key) and a duplicated marker key, plus empty/shape guards.


def _write(tmp_path: Path, body: str) -> Path:
    doc = tmp_path / "fixture.md"
    doc.write_text(body, encoding="utf-8")
    return doc


def test_parser_raises_on_duplicate_key(tmp_path: Path) -> None:
    doc = _write(
        tmp_path,
        "<!-- petasos-doc-assert: k=1 -->\n<!-- petasos-doc-assert: k=2 -->\n",
    )
    with pytest.raises(ValueError, match="duplicate doc-assert key"):
        _parse_doc_asserts(doc, required=frozenset({"k"}))


def test_parser_raises_on_missing_required_key(tmp_path: Path) -> None:
    doc = _write(tmp_path, "<!-- petasos-doc-assert: present=1 -->\n")
    with pytest.raises(ValueError, match="missing required doc-assert key"):
        _parse_doc_asserts(doc, required=frozenset({"absent"}))


def test_parser_raises_on_empty_value(tmp_path: Path) -> None:
    doc = _write(tmp_path, "<!-- petasos-doc-assert: k= -->\n")
    with pytest.raises(ValueError, match="empty value"):
        _parse_doc_asserts(doc, required=frozenset({"k"}))


def test_parser_raises_on_empty_csv_element(tmp_path: Path) -> None:
    doc = _write(tmp_path, "<!-- petasos-doc-assert: k=a,,b -->\n")
    with pytest.raises(ValueError, match="empty CSV element"):
        _parse_doc_asserts(doc, required=frozenset({"k"}))


def test_parser_raises_on_non_int_where_int_expected(tmp_path: Path) -> None:
    doc = _write(tmp_path, "<!-- petasos-doc-assert: n=abc -->\n")
    with pytest.raises(ValueError, match="expected an integer"):
        _parse_doc_asserts(doc, required=frozenset({"n"}), int_keys=frozenset({"n"}))
