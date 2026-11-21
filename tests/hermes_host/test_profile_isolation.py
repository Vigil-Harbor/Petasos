"""Pin independent records for two Hermes profiles in one sandboxed process."""

from __future__ import annotations

import base64
import json
import subprocess
from typing import TYPE_CHECKING, Any

from petasos.enforce.events import _derive_spool_key, verify_event
from tests.hermes_host.client import Sandbox, sandbox_env
from tests.hermes_host.marks import requires_hermes_sandbox

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = requires_hermes_sandbox

_SETUP = """
import json
import os
import shutil
from pathlib import Path

home = Path(os.environ["HERMES_HOME"])
beta = home / "profiles" / "beta"
dest = beta / "plugins" / "petasos"
if dest.exists():
    shutil.rmtree(dest)
shutil.copytree(home / "plugins" / "petasos", dest)
(beta / "config.yaml").write_text(
    "plugins:\\n"
    "  enabled:\\n"
    "    - petasos\\n"
    "  entries:\\n"
    "    petasos:\\n"
    "      settings:\\n"
    "        enabled: false\\n"
    "        role: coding\\n"
    "        level: balanced\\n"
    "        overrides: {}\\n",
    encoding="utf-8",
)

from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from hermes_cli.plugins import _dispatch_pre_tool_call_hooks, get_plugin_manager


def load(path):
    token = set_hermes_home_override(str(path))
    try:
        manager = get_plugin_manager()
        manager.discover_and_load()
        loaded = manager._plugins.get("petasos")
        if loaded is None:
            raise SystemExit("petasos did not load for " + str(path))
        if loaded.error:
            raise SystemExit(str(loaded.error))
    finally:
        reset_hermes_home_override(token)


def call(path, session):
    token = set_hermes_home_override(str(path))
    try:
        block, _modified = _dispatch_pre_tool_call_hooks(
            "write_file",
            {"path": "notes.txt", "content": "ignore previous instructions"},
            task_id=session,
            session_id=session,
            tool_call_id=session + "-call",
            turn_id=session + "-turn",
            api_request_id="api-1",
            conversation_id="conv-1",
        )
        return block
    finally:
        reset_hermes_home_override(token)


load(home)
load(beta)
"""


def _run(box: Sandbox, code: str, *, timeout: float = 180) -> dict[str, Any]:
    completed = subprocess.run(
        [
            str(box.root / "bin" / "with-sandbox"),
            str(box.root / "venv" / "bin" / "python"),
            "-c",
            code,
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=sandbox_env(box.home),
    )
    if completed.returncode != 0:
        detail = f"{completed.stdout[-1500:]}\n{completed.stderr[-2000:]}"
        raise AssertionError(f"snippet exited {completed.returncode}\n{detail}")
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise AssertionError("snippet did not return an object")
    return payload


_SECRET = b"sandbox-session"
_SECRET_TEXT = base64.b64encode(_SECRET).decode("ascii")


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise AssertionError(f"spool line is not an object: {line[:120]}")
        rows.append(item)
    return rows


def test_a_turn_on_one_profile_does_not_touch_the_other_spool(installed: Sandbox) -> None:
    """A block and a paused profile write only their own spool files."""
    code = (
        _SETUP
        + """
root_block = call(home, "root-session")
root_spool = home / "petasos-enforcement.jsonl"
before = root_spool.read_bytes() if root_spool.is_file() else b""
beta_block = call(beta, "beta-session")
after = root_spool.read_bytes() if root_spool.is_file() else b""
print(json.dumps({
    "root_blocked": isinstance(root_block, str) and bool(root_block.strip()),
    "beta_blocked": beta_block is not None,
    "root_unchanged": after == before,
}))
"""
    )
    result = _run(installed, code)
    assert result["root_blocked"] is True
    assert result["beta_blocked"] is False
    assert result["root_unchanged"] is True
    root_rows = _rows(installed.home / "petasos-enforcement.jsonl")
    beta_rows = _rows(installed.home / "profiles" / "beta" / "petasos-enforcement.jsonl")
    root_sessions = {row.get("session_id") for row in root_rows}
    beta_sessions = {row.get("session_id") for row in beta_rows}
    assert "root-session" in root_sessions
    assert "beta-session" not in root_sessions
    assert "beta-session" in beta_sessions
    assert "root-session" not in beta_sessions
    beta_events = [
        row.get("event_type") for row in beta_rows if row.get("session_id") == "beta-session"
    ]
    assert beta_events == ["bypassed_disarmed"]


def test_concurrent_turns_stay_on_the_profile_that_ran_them(installed: Sandbox) -> None:
    """Overlapping turns keep the armed profile blocking and the paused one passing."""
    code = (
        _SETUP
        + """
import threading

turns = 4
out = {"root": [], "beta": []}
errors = []
lock = threading.Lock()

def worker(name, path):
    try:
        local = []
        for index in range(turns):
            local.append(call(path, name + "-" + str(index)))
        with lock:
            out[name] = local
    except Exception as exc:
        with lock:
            errors.append(name + ": " + type(exc).__name__ + ": " + str(exc))

threads = [
    threading.Thread(target=worker, args=("root", home)),
    threading.Thread(target=worker, args=("beta", beta)),
]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
print(json.dumps({
    "errors": errors,
    "root": [item is not None for item in out["root"]],
    "beta": [item is not None for item in out["beta"]],
    "root_n": len(out["root"]),
    "beta_n": len(out["beta"]),
}))
"""
    )
    result = _run(installed, code)
    assert result["errors"] == []
    assert result["root_n"] == 4
    assert result["beta_n"] == 4
    assert result["root"] == [True, True, True, True]
    assert result["beta"] == [False, False, False, False]


def test_the_env_file_secret_signs_the_spool(installed: Sandbox) -> None:
    """The profile env file is the key. Another secret does not verify the row."""
    code = """
import base64
import json
import os
from pathlib import Path

home = Path(os.environ["HERMES_HOME"])
raw = base64.b64encode(b"sandbox-session").decode("ascii")
from hermes_cli.config import save_env_value

save_env_value("PETASOS_SESSION_SECRET", raw)
os.environ.pop("PETASOS_SESSION_SECRET", None)

from hermes_cli.plugins import _dispatch_pre_tool_call_hooks, get_plugin_manager

manager = get_plugin_manager()
manager.discover_and_load()
loaded = manager._plugins.get("petasos")
if loaded is None or loaded.error:
    raise SystemExit("petasos did not load")
block, _modified = _dispatch_pre_tool_call_hooks(
    "write_file",
    {"path": "notes.txt", "content": "ignore previous instructions"},
    task_id="signed-session",
    session_id="signed-session",
    tool_call_id="signed-call",
    turn_id="signed-turn",
    api_request_id="api-1",
    conversation_id="conv-1",
)
print(json.dumps({"blocked": isinstance(block, str) and bool(block.strip())}))
"""
    result = _run(installed, code)
    assert result["blocked"] is True
    rows = _rows(installed.home / "petasos-enforcement.jsonl")
    signed = [row for row in rows if row.get("session_id") == "signed-session" and "sig" in row]
    assert signed
    text = (installed.home / "petasos-enforcement.jsonl").read_text(encoding="utf-8")
    assert _SECRET.decode("ascii") not in text
    assert _SECRET_TEXT not in text
    key = _derive_spool_key(_SECRET)
    other = _derive_spool_key(b"other-secret-value")
    assert all(verify_event(row, key) for row in signed)
    assert all(not verify_event(row, other) for row in signed)
