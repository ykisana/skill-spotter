"""``skill-spotter`` command-line interface. The plugin's skills call this."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional

from . import __version__, lifecycle, paths, report, store

# Subcommands from SPEC section 12 that later milestones implement.
PLANNED = {
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

    show = sub.add_parser("show", help="show one pattern: prompts, steps, varying values")
    show.add_argument("pattern", help="pattern id, e.g. p42")
    show.add_argument("--json", action="store_true", help="machine-readable output")

    accept = sub.add_parser("accept", help="record that a pattern was saved as a skill")
    accept.add_argument("pattern", help="pattern id, e.g. p42")
    accept.add_argument("skill_path", help="path of the SKILL.md that was written")

    dismiss = sub.add_parser("dismiss", help="never suggest this pattern again")
    dismiss.add_argument("pattern", help="pattern id, e.g. p42")

    snooze = sub.add_parser("snooze", help="don't suggest this pattern for a while")
    snooze.add_argument("pattern", help="pattern id, e.g. p42")
    snooze.add_argument("--days", type=float, default=14, help="how long (default 14)")

    stats = sub.add_parser("stats", help="suggestions shown, accepted %%, skills used")
    stats.add_argument("--json", action="store_true", help="machine-readable output")

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
        if args.command == "show":
            return cmd_show(conn, args.pattern, as_json=args.json)
        if args.command == "accept":
            return cmd_accept(conn, args.pattern, args.skill_path)
        if args.command in ("dismiss", "snooze"):
            return cmd_dismiss_or_snooze(conn, args)
        if args.command == "stats":
            return cmd_stats(conn, as_json=args.json)
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
            "SELECT id, project_key, count, session_count, state, suggested_name, skill_path, "
            "(SELECT COUNT(*) FROM events e WHERE e.pattern_id = patterns.id AND e.type = 'used') "
            "AS uses FROM patterns WHERE state != 'dismissed' "
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
            used = f"  used {p['uses']}x" if p["state"] == "accepted" else ""
            print(
                f"  p{p['id']:<5} {name:<24} {p['count']}x in {p['session_count']} sessions"
                f"  [{p['state']}]{used}"
            )
    print(
        f"Suggestions: {'on' if enabled else 'paused'} · turns recorded: {counts['turns']}"
        f" · data: {base}"
    )
    return 0


def _pattern_or_error(text: str) -> Optional[int]:
    pattern_id = report.parse_pattern_id(text)
    if pattern_id is None:
        print(
            f"skill-spotter: {text!r} isn't a pattern id (expected something like p42).",
            file=sys.stderr,
        )
    return pattern_id


def cmd_show(conn: sqlite3.Connection, pattern: str, *, as_json: bool) -> int:
    pattern_id = _pattern_or_error(pattern)
    if pattern_id is None:
        return 2
    detail = report.pattern_detail(conn, pattern_id)
    if detail is None:
        print(
            f"skill-spotter: no pattern p{pattern_id}. Run `skill-spotter status`.", file=sys.stderr
        )
        return 1
    print(json.dumps(detail, indent=2) if as_json else report.format_detail(detail))
    return 0


def cmd_accept(conn: sqlite3.Connection, pattern: str, skill_path: str) -> int:
    pattern_id = _pattern_or_error(pattern)
    if pattern_id is None:
        return 2
    path = os.path.abspath(os.path.expanduser(skill_path))
    if not lifecycle.accept(conn, pattern_id, path, time.time(), via="draft"):
        print(f"skill-spotter: no pattern p{pattern_id}.", file=sys.stderr)
        return 1
    print(f"skill-spotter: p{pattern_id} saved as {path}.")
    return 0


def cmd_dismiss_or_snooze(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    pattern_id = _pattern_or_error(args.pattern)
    if pattern_id is None:
        return 2
    now = time.time()
    if args.command == "dismiss":
        ok = lifecycle.dismiss(conn, pattern_id, now)
        done = f"p{pattern_id} dismissed; it won't be suggested again."
    else:
        ok = lifecycle.snooze(conn, pattern_id, args.days, now)
        done = f"p{pattern_id} snoozed for {args.days:g} days."
    if not ok:
        print(
            f"skill-spotter: no pattern p{pattern_id} (or it's already a skill).", file=sys.stderr
        )
        return 1
    print(f"skill-spotter: {done}")
    return 0


def cmd_stats(conn: sqlite3.Connection, *, as_json: bool) -> int:
    data = lifecycle.stats(conn)
    if as_json:
        print(json.dumps(data, indent=2))
        return 0
    pct = "n/a" if data["accepted_pct"] is None else f"{data['accepted_pct']:g}%"
    print(
        f"turns recorded: {data['turns_recorded']} · patterns: {data['patterns']}\n"
        f"suggestions shown: {data['suggestions_shown']} "
        f"({data['patterns_suggested']} patterns)\n"
        f"accepted: {data['accepted']} ({pct}) · snoozed: {data['snoozed']} · "
        f"dismissed: {data['dismissed']}\n"
        f"skills used at least once: {data['skills_used_at_least_once']} "
        f"({data['skill_uses']} use{'' if data['skill_uses'] == 1 else 's'})"
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
