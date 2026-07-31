#!/usr/bin/env python3
"""
Seed sample alerts for UI validation and screenshot capture.

Seeded records are marked with a '[seed]' suffix so they can be identified
and cleaned up without affecting real alert history.

Usage:
    uv run python .hatchery/tooling/seed_alerts.py seed
    uv run python .hatchery/tooling/seed_alerts.py seed all
    uv run python .hatchery/tooling/seed_alerts.py seed "custom message"
    uv run python .hatchery/tooling/seed_alerts.py clean

Requires Hatchery to have been started at least once so that hatchery.db
exists at the configured data directory path.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from lib import alerts, config, db

SEED_MARKER = "[seed]"

ALERT_SAMPLES = [
    "Missing requirement: 'virsh' is not installed — VM lifecycle",
    "Missing requirement: 'virt-install' is not installed — VM creation",
    "Missing requirement: 'swtpm' is not installed — TPM emulation (Win11, Server 2025)",
    "Missing requirement: 'qemu-img' is not installed — disk image management",
]


def _seeded_alert_count() -> int:
    conn = db.get_connection()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM alerts WHERE message LIKE ?",
            (f"%{SEED_MARKER}%",),
        ).fetchone()[0]
    finally:
        conn.close()


def seed_one(message: str | None = None) -> None:
    if message is None:
        message = ALERT_SAMPLES[_seeded_alert_count() % len(ALERT_SAMPLES)]
    alerts.record_alert(f"{message} {SEED_MARKER}")
    print(f"[alert] {message}")


def seed_all() -> None:
    for msg in ALERT_SAMPLES:
        alerts.record_alert(f"{msg} {SEED_MARKER}")
        print(f"[alert] {msg}")
    print(f"\nSeeded {len(ALERT_SAMPLES)} alert(s).")


def clean() -> None:
    conn = db.get_connection()
    try:
        a = conn.execute(
            "DELETE FROM alerts WHERE message LIKE ?", (f"%{SEED_MARKER}%",)
        ).rowcount
        conn.commit()
        print(f"Removed {a} seeded alert(s).")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed or remove sample Hatchery alerts for UI validation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  seed                         insert the next curated alert (cycles through samples)
  seed all                     insert all curated samples at once
  seed "custom message"        insert a custom alert message
  clean                        remove all seeded alerts
        """,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    seed_parser = subparsers.add_parser("seed", help="insert a sample alert")
    seed_parser.add_argument(
        "message",
        nargs="?",
        help="optional custom message, or 'all' to insert every curated sample",
    )

    subparsers.add_parser("clean", help="remove all seeded alerts")

    args = parser.parse_args()

    config.load()
    db.init_db(config.data_dir() / "hatchery.db")

    if args.command == "seed":
        if args.message == "all":
            seed_all()
        else:
            seed_one(args.message)
    elif args.command == "clean":
        clean()


if __name__ == "__main__":
    main()
