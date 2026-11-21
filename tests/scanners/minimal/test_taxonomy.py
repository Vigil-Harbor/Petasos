"""Pin immutable syntactic rule metadata and suppression floors."""

from __future__ import annotations

from petasos.scanners.minimal.taxonomy import RULE_TAXONOMY


class TestImmutableExports:
    def test_rule_taxonomy_is_frozenset(self) -> None:
        assert isinstance(RULE_TAXONOMY, frozenset)
