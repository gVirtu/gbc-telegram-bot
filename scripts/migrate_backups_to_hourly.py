"""Migration script: rename daily backup files to hourly format.

Renames backup_YYYYMMDD.state -> backup_YYYYMMDD_00.state in all chat backup
directories under data/backups/.

Usage:
    python scripts/migrate_backups_to_hourly.py [--data-dir ./data]

Run once manually. Safe to re-run (idempotent: skips if target already exists).
"""

import argparse
import sys
from pathlib import Path


def migrate(data_dir: Path) -> None:
    backups_root = data_dir / "backups"
    if not backups_root.exists():
        print(f"No backups directory found at {backups_root}; nothing to do.")
        return

    renamed = skipped = errors = 0

    for chat_dir in sorted(backups_root.iterdir()):
        if not chat_dir.is_dir():
            continue
        for src in sorted(chat_dir.glob("backup_????????.state")):
            date_part = src.stem.replace("backup_", "")  # YYYYMMDD
            dst = src.parent / f"backup_{date_part}_00.state"
            if dst.exists():
                print(f"  SKIP  {src.name} -> {dst.name} (target exists)")
                skipped += 1
                continue
            try:
                src.rename(dst)
                print(f"  OK    {src.name} -> {dst.name}")
                renamed += 1
            except Exception as exc:
                print(f"  ERROR {src.name}: {exc}", file=sys.stderr)
                errors += 1

    print(f"\nDone. renamed={renamed}, skipped={skipped}, errors={errors}")
    if errors:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate daily backups to hourly format.")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("./data"),
        help="Path to data directory (default: ./data)",
    )
    args = parser.parse_args()
    migrate(args.data_dir)


if __name__ == "__main__":
    main()
