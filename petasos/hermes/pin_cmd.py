"""Fix settings in Hermes's managed file, without ever running as administrator."""

from __future__ import annotations

import json
import os
import shlex
import sys
import tempfile
from pathlib import Path
from typing import Any

from petasos.hermes.doctor_support import read_config, use_home
from petasos.hermes.managed import effective_config, hook_timeout, read_managed, writable
from petasos.hermes.pinning import (
    LIMITS,
    differences,
    merge_pin,
    pin_values,
    remove_pin,
)


def change_pin(
    home: Path, *, remove: bool = False, write: bool = False, accept_profile_changes: bool = False
) -> tuple[str, int]:
    """Print the scope before writing; return the result and an exit status."""
    try:
        with use_home(home):
            scope = read_managed()
            if scope.directory is None:
                return "Machine-level pinning is not available on this platform.\n", 2
            if remove:
                profile, problem = read_config(home / "config.yaml")
                if problem is not None:
                    return "The profile's file could not be read, so nothing was removed.\n", 2
                changed = differences(profile, scope.document)
                proposed = remove_pin(scope.document)
                summary = (
                    "Removing this pin lets each profile's own settings "
                    "and plugin lists take effect.\n"
                )
                if changed:
                    summary += "The profile differs from the pin:\n" + "\n".join(changed) + "\n"
                    if not accept_profile_changes:
                        return summary + (
                            "Nothing was written. Read these changes, then add "
                            "--accept-profile-changes to accept them when removing the pin.\n"
                        ), 2
            else:
                values = pin_values(effective_config(), timeout=hook_timeout())
                proposed = merge_pin(scope.document, values)
                summary = describe_pin(home, values)
            if not write:
                return summary + "Nothing was written. Add --write to prepare this change.\n", 0
            # The disclosure must reach the person before even a staging file is created.
            sys.stdout.write(summary)
            sys.stdout.flush()
            return write_document(scope.directory, proposed), 0
    except (OSError, ValueError, RuntimeError) as exc:
        return f"Nothing was written. {exc}\n", 2


def describe_pin(home: Path, values: dict[str, Any]) -> str:
    """The complete disclosure, shared by preview and write."""
    plugins = values["plugins"]
    settings = plugins["entries"]["petasos"]["settings"]
    on = ", ".join(plugins["enabled"]) or "none"
    off = ", ".join(plugins["disabled"]) or "none"
    armed = "on" if settings["enabled"] else "off"
    return (
        f"Pin the current settings for {home}.\n"
        f"Plugins kept on: {on}.\n"
        f"Plugins kept off: {off}.\n"
        "No plugin can be turned on or off until the profile is unpinned.\n"
        f"Every Petasos setting is stored at its current value. Protection is {armed}. "
        f"Job: {settings['role']}. Strictness: {settings['level']}.\n"
        "The time limit for plugin checks stays at "
        f"{plugins['hook_callback_timeout']:g} seconds.\n"
        "While pinned, Petasos uses these settings and nothing a profile holds, "
        "and the settings form will not save.\n"
        "This managed file applies to every profile using this managed directory.\n"
        "An account that can redirect Hermes to another managed directory can bypass the pin.\n"
        f"{LIMITS}\n"
    )


def write_document(directory: Path, document: dict[str, Any]) -> str:
    """Atomically replace a writable file, or stage the complete document privately."""
    body = json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    target = directory / "config.yaml"
    if writable(directory):
        fd, name = tempfile.mkstemp(prefix=".petasos-pin-", dir=directory)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return (
            f"Wrote {target}.\n"
            "This account can write the managed directory, so this pin does not protect "
            "settings from this account.\nRun petasos doctor to check what is in force.\n"
        )
    staging = Path(tempfile.mkdtemp(prefix="petasos-pin-"))
    source = staging / "config.yaml"
    source.write_text(body, encoding="utf-8")
    source.chmod(0o600)
    return (
        f"Prepared the complete managed document at {source}.\n"
        "Run these system commands with administrator rights:\n"
        f"mkdir -p -- {shlex.quote(str(directory))}\n"
        f"install -m 0644 -- {shlex.quote(str(source))} {shlex.quote(str(target))}\n"
        "Then run petasos doctor with the same home and profile to check what was installed.\n"
        "The prepared file belongs to this account. Inspect it before installing it, "
        "and do not run Petasos or Python with administrator rights.\n"
    )
