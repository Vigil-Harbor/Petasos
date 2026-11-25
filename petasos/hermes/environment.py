"""The environment a new Hermes process for one home would run.

Hermes records that environment under the home and activates it at startup.
Asking that environment is a separate Python process. The interpreter that
happens to be running this command is not the answer.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

# The path part of ``file:///C:/x``.
_DRIVE_LOCATION = re.compile(r"/[A-Za-z]:(?:/|$)")

_PROBE = (
    "import json, importlib.metadata\n"
    "try:\n"
    "    import petasos\n"
    "    import petasos.hermes.plugin\n"
    "    direct = importlib.metadata.distribution('petasos').read_text('direct_url.json')\n"
    "    print(json.dumps({'ok': True, 'version': str(petasos.__version__),\n"
    "                      'direct_url': direct}))\n"
    "except Exception as exc:\n"
    "    print(json.dumps({'ok': False, 'error': type(exc).__name__ + ': ' + str(exc)}))\n"
)


@dataclass(frozen=True, slots=True)
class Runtime:
    """The Python a new Hermes process for this home would use.

    ``note`` is empty, or one sentence when more than one install is recorded
    and Hermes itself could not say which one.
    """

    python: Path
    note: str = ""


@dataclass(frozen=True, slots=True)
class Probe:
    """Whether that Python can import Petasos.

    ``version`` is set when the import worked. ``error`` is set when it did not.
    """

    ok: bool
    version: str = ""
    error: str = ""
    direct_url: str = ""

    def matches_wheel(self, source: Path) -> bool | None:
        """Compare installed provenance to a local wheel; None means unknown.

        Hermes copies plugin inputs into a generation, so the recorded URL may
        name that snapshot. Its archive hash identifies the bytes across copies.
        """
        try:
            direct = json.loads(self.direct_url)
            archive = direct.get("archive_info", {})
            digest = archive.get("hashes", {}).get("sha256")
            if not digest and archive.get("hash", "").startswith("sha256="):
                digest = archive["hash"].removeprefix("sha256=")
            if isinstance(digest, str) and digest:
                return hashlib.sha256(source.read_bytes()).hexdigest() == digest
            installed = file_url_path(direct.get("url", ""))
            if installed is not None:
                if installed.resolve() == source.resolve():
                    return True
                if installed.is_file():
                    return installed.read_bytes() == source.read_bytes()
        except (OSError, ValueError, AttributeError, TypeError):
            pass
        return None


def file_url_path(url: str) -> Path | None:
    """The local path a ``file:`` URL names, or None for any other URL.

    Windows writes ``file:///C:/x``, whose path part is ``/C:/x``, and a
    share as ``file://server/share/x``. Elsewhere the path part is the path.
    The conversion is done here, not by ``url2pathname``, whose answers
    differ between Python versions.
    """
    parsed = urlparse(url)
    if parsed.scheme != "file":
        return None
    location = unquote(parsed.path)
    if os.name != "nt":
        return Path(location)
    if parsed.netloc.casefold() not in {"", "localhost"}:
        return Path(f"//{parsed.netloc}{location}")
    if _DRIVE_LOCATION.match(location):
        location = location[1:]
    return Path(location)


def runtime_python(home: Path) -> Runtime | None:
    """The committed environment's Python, or None when Hermes has not committed one."""
    from_hermes = _from_hermes()
    if from_hermes is not None:
        return from_hermes
    return _from_facts(home)


def probe_petasos(python: Path) -> Probe:
    """Ask ``python`` whether it can import Petasos. This process is not asked."""
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["PYTHONNOUSERSITE"] = "1"
    try:
        completed = subprocess.run(
            [str(python), "-I", "-c", _PROBE],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Probe(ok=False, error=str(exc) or type(exc).__name__)
    line = completed.stdout.strip().splitlines()
    if completed.returncode != 0 or not line:
        detail = (completed.stderr or completed.stdout).strip() or f"exit {completed.returncode}"
        return Probe(ok=False, error=detail.splitlines()[-1])
    try:
        payload = json.loads(line[-1])
    except json.JSONDecodeError:
        return Probe(ok=False, error="The environment did not answer.")
    if not isinstance(payload, dict):
        return Probe(ok=False, error="The environment did not answer.")
    if payload.get("ok") is True and isinstance(payload.get("version"), str):
        direct = payload.get("direct_url")
        return Probe(
            ok=True,
            version=payload["version"],
            direct_url=direct if isinstance(direct, str) else "",
        )
    error = payload.get("error")
    return Probe(ok=False, error=error if isinstance(error, str) and error else "import failed")


def republish(*, repair: bool = False) -> tuple[bool, str]:
    """Ask Hermes to rebuild the environment for the plugins it already runs.

    The enabled set is not changed. Hermes's admission writes any config it
    needs. This function does not write ``config.yaml``. ``repair`` rebuilds
    even when Hermes's stamp still matches, which is how a missing package is
    put back.
    """
    from petasos.hermes.host import load_module

    command = load_module("hermes_cli.plugins_cmd")
    if command is None:
        return False, (
            "Hermes is not available in this Python, so its environment was not rebuilt. "
            "Run the same command as hermes petasos ..., which uses Hermes's own Python."
        )
    admit = getattr(command, "_admit_and_save_plugin_sets", None)
    enabled_set = getattr(command, "_get_enabled_set", None)
    disabled_set = getattr(command, "_get_disabled_set", None)
    version_of = getattr(command, "_plugin_selection_version", None)
    if (
        not callable(admit)
        or not callable(enabled_set)
        or not callable(disabled_set)
        or not callable(version_of)
    ):
        return False, "This Hermes has no way to rebuild the environment a new process runs."
    try:
        if repair:
            # ``repair=True`` together with a plugin selection is refused: repair
            # restores the recorded graph and cannot change the selection.
            _repair()
        else:
            admit(
                enabled_set(),
                disabled_set(),
                expected_config=version_of(),
                action="Rebuild the environment",
            )
    except SystemExit as exc:
        return False, f"Hermes stopped while rebuilding the environment (exit {exc.code})."
    except Exception as exc:
        text = str(exc).strip() or type(exc).__name__
        first = text.splitlines()[0]
        if len(first) > 500:
            first = first[:500] + "..."
        return False, f"Hermes did not rebuild the environment: {first}"
    return True, "Hermes rebuilt the environment a new process runs."


def _repair() -> None:
    """Rebuild the recorded graph even when the stamp still matches.

    Passing a plugin selection with ``repair=True`` is refused. The recorded
    graph already names the plugins and the wheel they installed.
    """
    from petasos.hermes.host import load_module

    client = load_module("pm.client")
    sync = getattr(client, "sync_venv", None) if client is not None else None
    if not callable(sync):
        raise RuntimeError("This Hermes has no way to repair its environment.")
    sync(explicit=True, repair=True)


def _from_hermes() -> Runtime | None:
    from petasos.hermes.host import load_module

    environments = load_module("pm.environments")
    paths = load_module("pm.paths")
    if environments is None or paths is None:
        return None
    committed = getattr(environments, "committed_venv", None)
    repo_root = getattr(paths, "repo_root", None)
    if not callable(committed) or not callable(repo_root):
        return None
    try:
        environment = committed(repo_root())
    except Exception:
        return None
    if environment is None:
        return None
    python = _interpreter(Path(environment))
    if python is None:
        return None
    return Runtime(python=python)


def _installs(home: Path) -> Path | None:
    """Where Hermes records environments for ``home``.

    Every profile under a root shares the root's record, so a profile home
    has none of its own.
    """
    candidates = [home / "installs"]
    if home.parent.name == "profiles":
        candidates.insert(0, home.parent.parent / "installs")
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def _from_facts(home: Path) -> Runtime | None:
    installs = _installs(home)
    if installs is None:
        return None
    try:
        facts = [path for path in installs.glob("*/facts.json") if path.is_file()]
    except OSError:
        return None
    facts.sort(key=lambda path: path.stat().st_mtime_ns, reverse=True)
    note = ""
    if len(facts) > 1:
        note = (
            "More than one Hermes install is recorded for this profile. "
            "This check used the one written most recently."
        )
    for path in facts:
        python = _python_named(installs, path)
        if python is not None:
            return Runtime(python=python, note=note)
    return None


def _python_named(installs: Path, facts: Path) -> Path | None:
    try:
        payload = json.loads(facts.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    packages = payload.get("packages") if isinstance(payload, dict) else None
    venv = packages.get("venv") if isinstance(packages, dict) else None
    raw = venv.get("environment") if isinstance(venv, dict) else None
    if not isinstance(raw, str) or raw == "":
        return None
    environment = Path(raw)
    try:
        if not environment.resolve().is_relative_to(installs.resolve()):
            return None
    except OSError:
        return None
    return _interpreter(environment)


def _interpreter(environment: Path) -> Path | None:
    for candidate in (
        environment / "bin" / "python",
        environment / "Scripts" / "python.exe",
    ):
        if candidate.is_file():
            return candidate
    return None
