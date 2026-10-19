"""``skill-spotter`` command-line interface. The plugin's skills call this."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path

from . import __version__, paths, store

# Subcommands from SPEC section 12 that later milestones implement.
PLANNED = {
    "show": "M1",
    "dismiss": "M2",
    "snooze": "M2",
    "stats": "M2",
    "train": "M4",
    "extras": "M4",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skill-spotter",
        description="Spot repeated Claude Code tasks and suggest saving them as skills.",
    )
    parser.add_argument("--version", action="version", version=f"skill-spotter {__version__}")
    parser.add_argument(
        "--data-dir",
        help="data directory (default: $SKILL_SPOTTER_DATA, $CLAUDE_PLUGIN_DATA, "
        f"or {paths.FALLBACK_DATA_DIR})",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    status = sub.add_parser("status", help="show patterns, suggestions and created skills")
    status.add_argument("--json", action="store_true", help="machine-readable output")

    sub.add_parser("on", help="resume suggestions")
    sub.add_parser("off", help="pause suggestions")

    forget = sub.add_parser("forget", help="delete all stored data")
    forget.add_argument("--yes", action="store_true", help="don't ask for confirmation")

    for name, milestone in PLANNED.items():
        sub.add_parser(name, help=f"(not implemented yet, {milestone})")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    base = paths.data_dir(args.data_dir)

    if args.command in PLANNED:
        print(
            f"skill-spotter {args.command}: not implemented yet "
            f"(planned for {PLANNED[args.command]}).",
            file=sys.stderr,
        )
        return 2
    if args.command == "forget":
        return cmd_forget(base, assume_yes=args.yes)

    try:
        conn = store.connect(paths.db_path(base))
    except (sqlite3.DatabaseError, RuntimeError) as exc:
        print(
            f"skill-spotter: can't open the database in {base}: {exc}\n"
            "Run `skill-spotter forget` (or /skill-spotter:forget) to start fresh.",
            file=sys.stderr,
        )
        return 1
    try:
        if args.command == "status":
            return cmd_status(conn, base, as_json=args.json)
        if args.command in ("on", "off"):
            store.set_setting(conn, "enabled", "1" if args.command == "on" else "0")
            state = "on" if args.command == "on" else "paused"
            print(f"skill-spotter suggestions: {state}.")
            return 0
    finally:
        conn.close()
    parser.error(f"unknown command {args.command!r}")
    return 2


def cmd_status(conn: sqlite3.Connection, base: Path, *, as_json: bool) -> int:
    counts = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("turns", "actions", "patterns")
    }
    patterns = [
        dict(row)
        for row in conn.execute(
            "SELECT id, project_key, count, session_count, state, suggested_name, skill_path "
            "FROM patterns WHERE state != 'dismissed' "
            "ORDER BY count DESC, last_seen DESC LIMIT 20"
        )
    ]
    enabled = store.is_enabled(conn)

    if as_json:
        report = {"enabled": enabled, "data_dir": str(base), "counts": counts, "patterns": patterns}
        print(json.dumps(report, indent=2))
        return 0

    if not patterns:
        print("skill-spotter: no patterns yet.")
    else:
        print("skill-spotter patterns:")
        for p in patterns:
            name = f"/{p['suggested_name']}" if p["suggested_name"] else "(unnamed)"
            print(
                f"  p{p['id']:<5} {name:<24} {p['count']}x in {p['session_count']} sessions"
                f"  [{p['state']}]"
            )
    print(
        f"Suggestions: {'on' if enabled else 'paused'} · turns recorded: {counts['turns']}"
        f" · data: {base}"
    )
    return 0


def cmd_forget(base: Path, *, assume_yes: bool) -> int:
    if not assume_yes:
        reply = input(f"Delete all skill-spotter data in {base}? [y/N] ")
        if reply.strip().lower() not in ("y", "yes"):
            print("Nothing deleted.")
            return 1
    if base.exists():
        shutil.rmtree(base)
    print(f"Deleted all skill-spotter data ({base}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
