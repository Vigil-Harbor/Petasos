"""Argument handling for the ``petasos`` command.

The words a person reads are produced by ``doctor``, ``install``, and
``migrate_cmd``. This module only chooses which one to run.
"""

from __future__ import annotations

import argparse
import sys

from petasos.hermes.doctor import examine, render_json, render_text
from petasos.hermes.install import install_plugin
from petasos.hermes.migrate_cmd import migrate_profile
from petasos.hermes.target import resolve_target


def main(argv: list[str] | None = None) -> int:
    """Parse ``argv`` and run one subcommand. Return the exit status."""
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        return 2 if code is None else int(code)
    command = getattr(args, "command", None)
    if command == "doctor":
        return _doctor(args)
    if command == "hermes":
        if getattr(args, "hermes_command", None) != "install":
            print("Choose a hermes command. Try: petasos hermes install --help", file=sys.stderr)
            return 2
        return _install(args)
    if command == "config":
        if getattr(args, "config_command", None) != "migrate":
            print("Choose a config command. Try: petasos config migrate --help", file=sys.stderr)
            return 2
        return _migrate(args)
    parser.print_help(sys.stderr)
    return 2


def _doctor(args: argparse.Namespace) -> int:
    try:
        home, reason = resolve_target(home=args.home, profile=args.profile)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    report = examine(home, home_reason=reason)
    if args.json:
        sys.stdout.write(render_json(report))
    else:
        sys.stdout.write(render_text(report, verbose=bool(args.verbose), color=_color(args.json)))
    return report.exit_code


def _install(args: argparse.Namespace) -> int:
    if args.run and not args.released:
        print(
            "--run only applies to the released installer. "
            "The development install writes the plugin files itself. "
            "Add --released --run to run Hermes's installer.",
            file=sys.stderr,
        )
        return 2
    try:
        home, reason = resolve_target(home=args.home, profile=args.profile)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    result = install_plugin(
        home,
        home_reason=reason,
        dry_run=bool(args.dry_run),
        force=bool(args.force),
        released=bool(args.released),
        run=bool(args.run),
        color=_color(False),
    )
    sys.stdout.write(result.text)
    return result.exit_code


def _migrate(args: argparse.Namespace) -> int:
    try:
        home, reason = resolve_target(home=args.home, profile=args.profile)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    result = migrate_profile(
        home,
        home_reason=reason,
        write=bool(args.write),
        proceed=bool(args.proceed),
    )
    sys.stdout.write(result.text)
    return result.exit_code


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="petasos",
        description="Set up Petasos and check that it is protecting a Hermes agent.",
    )
    sub = parser.add_subparsers(dest="command")

    doctor = sub.add_parser(
        "doctor",
        help="Say whether Petasos is protecting one Hermes profile, and what to do if it is not.",
    )
    _target_flags(doctor)
    doctor.add_argument(
        "--json",
        action="store_true",
        help="Print the same report as JSON for a script.",
    )
    doctor.add_argument(
        "--verbose",
        action="store_true",
        help="Add paths, versions, and every setting with where it came from.",
    )
    doctor.set_defaults(command="doctor")

    hermes = sub.add_parser("hermes", help="Install Petasos into a Hermes profile.")
    hermes_sub = hermes.add_subparsers(dest="hermes_command")
    install = hermes_sub.add_parser(
        "install",
        help="Put the plugin in place and turn it on. Running it again updates the files.",
    )
    _target_flags(install)
    install.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change, and change nothing.",
    )
    install.add_argument(
        "--force",
        action="store_true",
        help="Replace a plugin directory that is not already Petasos.",
    )
    install.add_argument(
        "--released",
        action="store_true",
        help="Print Hermes's install command for the published plugin instead of writing files.",
    )
    install.add_argument(
        "--run",
        action="store_true",
        help="With --released, run Hermes's installer from this Python.",
    )
    install.set_defaults(command="hermes", hermes_command="install")

    config = sub.add_parser("config", help="Work with Petasos settings.")
    config_sub = config.add_subparsers(dest="config_command")
    migrate = config_sub.add_parser(
        "migrate",
        help="Show the new settings that match an old petasos: section.",
    )
    _target_flags(migrate)
    migrate.add_argument(
        "--write",
        action="store_true",
        help="Store the new settings through Hermes. The old section is left in place.",
    )
    migrate.add_argument(
        "--proceed",
        action="store_true",
        help="With --write, store the settings even when some old values were not copied.",
    )
    migrate.set_defaults(command="config", config_command="migrate")
    return parser


def _target_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--home",
        help="Hermes home to use. The default is the one the plugin would use.",
    )
    parser.add_argument(
        "--profile",
        help="Profile name under that home. 'default' is the home with no profile.",
    )


def install_registered_cli(parser: argparse.ArgumentParser) -> None:
    """Add Petasos subcommands to the parser Hermes created for ``hermes petasos``.

    Hermes calls this while it is building ``hermes --help``. The handler is
    :func:`run_registered`, which Hermes sets as the command function.
    """
    sub = parser.add_subparsers(dest="petasos_command")
    doctor = sub.add_parser(
        "doctor",
        help="Say whether Petasos is protecting this profile, and what to do if it is not.",
    )
    _target_flags(doctor)
    doctor.add_argument(
        "--json",
        action="store_true",
        help="Print the same report as JSON for a script.",
    )
    doctor.add_argument(
        "--verbose",
        action="store_true",
        help="Add paths, versions, and every setting with where it came from.",
    )
    install = sub.add_parser(
        "install",
        help="Refresh the plugin files for this profile and turn the plugin on.",
    )
    _target_flags(install)
    install.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change, and change nothing.",
    )
    install.add_argument(
        "--force",
        action="store_true",
        help="Replace a plugin directory that is not already Petasos.",
    )
    install.add_argument(
        "--released",
        action="store_true",
        help="Print Hermes's install command for the published plugin instead of writing files.",
    )
    install.add_argument(
        "--run",
        action="store_true",
        help="With --released, run Hermes's installer from this Python.",
    )
    config = sub.add_parser("config", help="Work with Petasos settings.")
    config_sub = config.add_subparsers(dest="config_command")
    migrate = config_sub.add_parser(
        "migrate",
        help="Show the new settings that match an old petasos: section.",
    )
    _target_flags(migrate)
    migrate.add_argument(
        "--write",
        action="store_true",
        help="Store the new settings through Hermes. The old section is left in place.",
    )
    migrate.add_argument(
        "--proceed",
        action="store_true",
        help="With --write, store the settings even when some old values were not copied.",
    )


def run_registered(args: argparse.Namespace) -> int:
    """Run the subcommand Hermes parsed for ``hermes petasos``. Return the exit status."""
    command = getattr(args, "petasos_command", None)
    if command == "doctor":
        return _doctor(args)
    if command == "install":
        return _install(args)
    if command == "config":
        if getattr(args, "config_command", None) != "migrate":
            print(
                "Choose a config command. Try: hermes petasos config migrate --help",
                file=sys.stderr,
            )
            return 2
        return _migrate(args)
    print("Choose a command: doctor, install, or config migrate.", file=sys.stderr)
    return 2


def _color(json_output: bool) -> bool:
    if json_output:
        return False
    return sys.stdout.isatty()
