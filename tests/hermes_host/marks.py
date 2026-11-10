"""Skip the Hermes host tests unless a sandbox was prepared."""

from __future__ import annotations

import os

import pytest

requires_hermes_sandbox = pytest.mark.skipif(
    not os.environ.get("PETASOS_HERMES_SANDBOX"),
    reason="PETASOS_HERMES_SANDBOX is not set to a prepared Hermes sandbox",
)
