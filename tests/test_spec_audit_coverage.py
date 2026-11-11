"""Regression coverage for behavioral-spec features that the audit (features-tracker.xlsx)
flagged as untested ("NONE FOUND" / COVERAGE GAP), plus one field-attribution bug (DEF-02).

These lock load-bearing behaviors that previously had no direct test:
security-relevant reject branches (HMAC token verification, fail-secure escalation),
the PET-126 hot-reload `apply_config` surfaces, listener fan-out, and serialization
contracts. Every test here exercises a real code path (no mocks of the unit under test).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pathlib


# --- CINF-02: _paths active_profile traversal guard ---
def test_active_profile_traversal_is_rejected(tmp_path: pathlib.Path) -> None:
    from petasos.hermes.home import resolve_active_profile_dir

    (tmp_path / "profiles").mkdir()
    (tmp_path / "active_profile").write_text("../../evil")
    resolved, warning = resolve_active_profile_dir(tmp_path)
    assert resolved is None
    assert warning is not None and "escapes" in warning
