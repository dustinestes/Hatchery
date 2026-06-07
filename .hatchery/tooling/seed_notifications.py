#!/usr/bin/env python3
"""
Seed sample notifications for UI validation and screenshot capture.

Seeded records are marked with a '[seed]' suffix so they can be identified
and cleaned up without affecting real notification history.

Usage:
    uv run python .hatchery/tooling/seed_notifications.py seed warning
    uv run python .hatchery/tooling/seed_notifications.py seed activity
    uv run python .hatchery/tooling/seed_notifications.py seed all
    uv run python .hatchery/tooling/seed_notifications.py seed warning "custom message"
    uv run python .hatchery/tooling/seed_notifications.py clean

Requires Hatchery to have been started at least once so that hatchery.db
exists at the configured data directory path.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from lib import config, db
import lib.notifications as notif

SEED_MARKER = "[seed]"

WARNING_SAMPLES = [
    "Missing requirement: 'virsh' is not installed — VM lifecycle",
    "Missing requirement: 'virt-install' is not installed — VM creation",
    "Missing requirement: 'swtpm' is not installed — TPM emulation (Win11, Server 2025)",
    "Missing requirement: 'qemu-img' is not installed — disk image management",
]

ACTIVITY_SAMPLES = [
    "Clutch 'dev-lab.yaml' created.",
    "VM 'win11-dev' is hatching.",
    "VM 'server2022-qa' is hatching.",
    "Clutch 'qa-stack.yaml' created.",
    "VM 'win10-test' is hatching.",
]


def _seeded_count(tier: str) -> int:
    """Count seeded records of a given tier — used to cycle through samples."""
    conn = db.get_connection()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE tier = ? AND message LIKE ?",
            (tier, f"%{SEED_MARKER}%"),
        ).fetchone()[0]
    finally:
        conn.close()


def seed_one(tier: str, message: str | None = None) -> None:
    samples = WARNING_SAMPLES if tier == "warning" else ACTIVITY_SAMPLES
    if message is None:
        idx = _seeded_count(tier) % len(samples)
        message = samples[idx]
    notif.record(tier, f"{message} {SEED_MARKER}")
    print(f"[{tier}] {message}")


def seed_all() -> None:
    for msg in WARNING_SAMPLES:
        notif.record("warning", f"{msg} {SEED_MARKER}")
        print(f"[warning] {msg}")
    for msg in ACTIVITY_SAMPLES:
        notif.record("activity", f"{msg} {SEED_MARKER}")
        print(f"[activity] {msg}")
    total = len(WARNING_SAMPLES) + len(ACTIVITY_SAMPLES)
    print(f"\nSeeded {total} notifications.")


def clean() -> None:
    conn = db.get_connection()
    try:
        cursor = conn.execute(
            "DELETE FROM notifications WHERE message LIKE ?",
            (f"%{SEED_MARKER}%",),
        )
        conn.commit()
        print(f"Removed {cursor.rowcount} seeded notification(s).")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed or remove sample Hatchery notifications for UI validation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  seed warning                   insert the next curated warning (cycles through samples)
  seed activity                  insert the next curated activity notification
  seed all                       insert all curated samples at once
  seed warning "custom message"  insert a custom warning message
  clean                          remove all seeded notifications
        """,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    seed_parser = subparsers.add_parser("seed", help="insert a sample notification")
    seed_parser.add_argument(
        "tier",
        choices=["warning", "activity", "all"],
        help="tier to seed, or 'all' to insert every curated sample",
    )
    seed_parser.add_argument(
        "message",
        nargs="?",
        help="optional custom message — overrides the curated sample for this insert",
    )

    subparsers.add_parser("clean", help="remove all seeded notifications")

    args = parser.parse_args()

    config.load()
    db.init_db(config.data_dir() / "hatchery.db")

    if args.command == "seed":
        if args.tier == "all":
            if args.message:
                parser.error("'message' is not supported with tier 'all'")
            seed_all()
        else:
            seed_one(args.tier, args.message)
    elif args.command == "clean":
        clean()


if __name__ == "__main__":
    main()
