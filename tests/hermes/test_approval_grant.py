"""Approval probes fail closed while ordinary human approvals remain usable."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from petasos.hermes import host


def _raise() -> Any:
    raise RuntimeError("approval probe failed")


@pytest.mark.parametrize("probe", ["yolo", "mode", "config", "missing_yolo"])
def test_a_failing_approval_probe_reports_an_unattended_grant(
    monkeypatch: pytest.MonkeyPatch, probe: str
) -> None:
    approval = SimpleNamespace(_yolo_active=lambda: False)
    context = SimpleNamespace(_get_approval_mode=lambda: "manual")
    config = SimpleNamespace(load_config=lambda: {"approvals": {"mode": "manual"}})
    if probe == "yolo":
        approval._yolo_active = _raise
    elif probe == "mode":
        context._get_approval_mode = _raise
    elif probe == "config":
        config.load_config = _raise
    else:
        delattr(approval, "_yolo_active")
    monkeypatch.setattr(host, "_approval", lambda: approval)
    monkeypatch.setattr(host, "load_module", lambda _name: context)
    monkeypatch.setattr(host, "_config", lambda: config)
    grant = host.approval_grant()
    assert grant.yolo
    assert grant.unattended


def test_normal_and_always_approved_probes_are_still_honoured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approval = SimpleNamespace(
        _yolo_active=lambda: False,
        is_approved=lambda command, rule: rule == "plugin_rule:kept",
    )
    monkeypatch.setattr(host, "_approval", lambda: approval)
    monkeypatch.setattr(host, "_config", lambda: SimpleNamespace(load_config=lambda: {}))
    assert not host.approval_grant().unattended
    assert host.rule_always_approved("kept")
    assert not host.rule_always_approved("other")
