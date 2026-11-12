"""Pin immutable syntactic rule metadata and suppression floors."""

from __future__ import annotations

from petasos.scanners.minimal.taxonomy import RULE_TAXONOMY


class TestImmutableExports:
    """Pin Immutable Exports."""

    def test_rule_taxonomy_is_frozenset(self) -> None:
        """Pin rule taxonomy is frozenset."""
        assert isinstance(RULE_TAXONOMY, frozenset)
