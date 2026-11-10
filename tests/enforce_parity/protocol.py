"""The interface both enforcement oracles implement.

``PluginOracle`` replays a scenario through the reference plugin.
A later ``Enforcer`` adapter implements the same method and leaves the
corpus, the recorded outcomes and the replay test alone.
"""

from __future__ import annotations

from typing import Any, Protocol


class EnforcementAdapter(Protocol):
    """Replay one host-neutral scenario and return one outcome per step.

    ``scenario`` is the expanded document from ``tests.enforce_parity.load``:
    ``repeat`` has already been unrolled, and ``$repeat`` / ``$nest`` nodes
    have been expanded. ``$config`` and ``$home`` are still tokens. The
    adapter substitutes this run's config file and home directory, then
    scrubs those paths back to ``<config>`` and ``<home>`` in the outcome.

    Each outcome has ``id``, ``decision``, ``events``, ``logs`` and ``tier``.
    ``decision`` is ``allow``, ``block``, ``approve``, ``annotate`` or
    ``unchanged``, or ``None`` when the step does not decide a call.
    ``events`` are the spool rows written during the step, in order, without
    ``scan_id``, ``timestamp`` or ``sig``. ``logs`` are the operator lines
    (``PETASOS_...`` and the restart-required warnings). ``tier`` is the
    session tier after the step, or ``None`` when the step names no session
    or the tier cannot be read yet.
    """

    def replay(self, scenario: dict[str, Any]) -> list[dict[str, Any]]:
        """Run ``scenario`` from a clean process and return its outcomes."""
        ...
