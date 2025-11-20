from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.pty_watcher import PtyWatcher  # noqa: E402
from app.services.status_repo import (  # noqa: E402
    StatusRepository,
    format_timestamp,
    min_timestamp_for_window,
)


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(message)s")


async def _run_pty_watch(interval: float | None) -> None:
    watcher = PtyWatcher(interval=interval)
    await watcher.run()


def _run_pty_status(args: argparse.Namespace) -> None:
    repo = StatusRepository()
    min_ts = min_timestamp_for_window(args.since)
    rows = repo.list_status(min_ts)
    if args.json:
        print(json.dumps(rows, indent=2))
        return
    if args.short:
        if not rows:
            print("[no workers]")
            return
        chunks = []
        for row in rows:
            worker = row["worker_id"] or row["pane_id"]
            state = row["state"] or "-"
            chunks.append(f"[{worker}: {state}]")
        print(" ".join(chunks))
        return
    if not rows:
        print("No PTYs tracked (status database empty).")
        return
    table_rows = []
    for row in rows:
        table_rows.append(
            [
                row["pane_id"],
                row["tmux_target"] or "-",
                row["state"] or "-",
                (row["summary"] or "").strip(),
                format_timestamp(row["last_polled_ts"]),
            ]
        )
    headers = ["Pane", "Target", "State", "Summary", "Last polled"]
    _print_table(headers, table_rows)


def _run_pty_tail(args: argparse.Namespace) -> None:
    repo = StatusRepository()
    rows = repo.tail_history(args.pane_id, limit=args.limit)
    if args.json:
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        print(f"No history found for pane {args.pane_id}.")
        return
    table_rows = []
    for row in rows:
        table_rows.append(
            [
                format_timestamp(row["ts"]),
                row["state"],
                (row["summary"] or "").strip(),
            ]
        )
    headers = ["Timestamp", "State", "Summary"]
    print(f"History for {rows[0]['tmux_target'] or args.pane_id} (limit {args.limit}):")
    _print_table(headers, table_rows)


def _print_table(headers: list[str], rows: Iterable[Iterable[str]]) -> None:
    rows = list(rows)
    widths = [len(header) for header in headers]
    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))
    fmt = "  ".join(f"{{:{w}}}" for w in widths)
    print(fmt.format(*headers))
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print(fmt.format(*row))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="conductor", description="Conductor helper CLI")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    subparsers = parser.add_subparsers(dest="command")

    pty_parser = subparsers.add_parser("pty", help="PTY helper commands")
    pty_subparsers = pty_parser.add_subparsers(dest="pty_command")

    watch_parser = pty_subparsers.add_parser("watch", help="Run the tmux watcher daemon")
    watch_parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Polling interval in seconds (defaults to CONDUCTOR_WATCHER_INTERVAL).",
    )
    watch_parser.set_defaults(func=lambda args: asyncio.run(_run_pty_watch(args.interval)))

    status_parser = pty_subparsers.add_parser("status", help="List tracked PTYs and their states")
    status_parser.add_argument(
        "--since",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Only show panes polled within the past SECONDS (default: all).",
    )
    status_parser.add_argument("--json", action="store_true", help="Output raw JSON rows.")
    status_parser.add_argument(
        "--short",
        action="store_true",
        help="Print compact summary (e.g., for tmux status line) instead of the table.",
    )
    status_parser.set_defaults(func=_run_pty_status)

    tail_parser = pty_subparsers.add_parser("tail", help="Show status history for a pane")
    tail_parser.add_argument("pane_id", help="tmux pane id to inspect (e.g., %14)")
    tail_parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of history rows to display (default 50).",
    )
    tail_parser.add_argument("--json", action="store_true", help="Output JSON history rows.")
    tail_parser.set_defaults(func=_run_pty_tail)

    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    _configure_logging(args.verbose)
    try:
        args.func(args)
    except KeyboardInterrupt:
        logging.info("Interrupted, shutting down watcher")
    return 0


if __name__ == "__main__":
    sys.exit(main())
