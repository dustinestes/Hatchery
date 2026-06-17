#!/usr/bin/env python3
"""
Seed sample notifications for UI validation and screenshot capture.

Seeded records are marked with a '[seed]' suffix so they can be identified
and cleaned up without affecting real notification history.

Usage:
    uv run python .hatchery/tooling/seed_notifications.py seed alert
    uv run python .hatchery/tooling/seed_notifications.py seed activity
    uv run python .hatchery/tooling/seed_notifications.py seed all
    uv run python .hatchery/tooling/seed_notifications.py seed alert "custom message"
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

ALERT_SAMPLES = [
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


def _seeded_alert_count() -> int:
    conn = db.get_connection()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM alerts WHERE message LIKE ?",
            (f"%{SEED_MARKER}%",),
        ).fetchone()[0]
    finally:
        conn.close()


def _seeded_activity_count() -> int:
    conn = db.get_connection()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM activity WHERE message LIKE ?",
            (f"%{SEED_MARKER}%",),
        ).fetchone()[0]
    finally:
        conn.close()


def seed_one(tier: str, message: str | None = None) -> None:
    if tier == "alert":
        if message is None:
            message = ALERT_SAMPLES[_seeded_alert_count() % len(ALERT_SAMPLES)]
        notif.record_alert(f"{message} {SEED_MARKER}")
    else:
        if message is None:
            message = ACTIVITY_SAMPLES[_seeded_activity_count() % len(ACTIVITY_SAMPLES)]
        notif.record_activity(f"{message} {SEED_MARKER}")
    print(f"[{tier}] {message}")


def seed_all() -> None:
    for msg in ALERT_SAMPLES:
        notif.record_alert(f"{msg} {SEED_MARKER}")
        print(f"[alert] {msg}")
    for msg in ACTIVITY_SAMPLES:
        notif.record_activity(f"{msg} {SEED_MARKER}")
        print(f"[activity] {msg}")
    print(f"\nSeeded {len(ALERT_SAMPLES) + len(ACTIVITY_SAMPLES)} notifications.")


def clean() -> None:
    conn = db.get_connection()
    try:
        a = conn.execute(
            "DELETE FROM alerts WHERE message LIKE ?", (f"%{SEED_MARKER}%",)
        ).rowcount
        b = conn.execute(
            "DELETE FROM activity WHERE message LIKE ?", (f"%{SEED_MARKER}%",)
        ).rowcount
        conn.commit()
        print(f"Removed {a + b} seeded notification(s).")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed or remove sample Hatchery notifications for UI validation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  seed alert                    insert the next curated alert (cycles through samples)
  seed activity                 insert the next curated activity notification
  seed all                      insert all curated samples at once
  seed alert "custom message"   insert a custom alert message
  clean                         remove all seeded notifications
        """,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    seed_parser = subparsers.add_parser("seed", help="insert a sample notification")
    seed_parser.add_argument(
        "tier",
        choices=["alert", "activity", "all"],
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
