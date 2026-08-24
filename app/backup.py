import logging
import sqlite3
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


def _has_data(db_path: Path) -> bool:
    conn = sqlite3.connect(str(db_path))
    try:
        for table in ("expenses", "wallet_movements", "subscriptions"):
            if conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
                return True
        return False
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def backup_db(db_path: Path, backup_dir: Path, keep: int = 20) -> Path | None:
    db_path = Path(db_path)
    backup_dir = Path(backup_dir)
    if not db_path.exists() or not _has_data(db_path):
        return None

    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    dest = backup_dir / f"expenses_{stamp}.sqlite"

    src = sqlite3.connect(str(db_path))
    try:
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    backups = sorted(backup_dir.glob("expenses_*.sqlite"))
    for old in backups[:-keep]:
        old.unlink()

    log.info("db backup -> %s (kept %d)", dest.name, min(len(backups), keep))
    return dest
