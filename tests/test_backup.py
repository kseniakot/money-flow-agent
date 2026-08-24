from app import backup, db


def _seed(path):
    conn = db.get_conn(str(path))
    db.init_db(conn)
    user = db.upsert_user(conn, tg_user_id=1, tg_username="me")
    db.save_expenses(
        conn,
        user["id"],
        [
            {
                "name": "молоко",
                "category": "молочка",
                "qty": 1,
                "unit": "шт",
                "unit_price": 1.9,
                "price": 1.9,
                "currency": "BYN",
                "purchased_at": "2026-08-13 10:00:00",
                "place": None,
                "source": "text",
            }
        ],
    )
    return conn


def test_backup_creates_restorable_copy(tmp_path):
    src = tmp_path / "expenses.sqlite"
    _seed(src)
    dest = backup.backup_db(src, tmp_path / "backups")
    assert dest is not None and dest.exists()
    copy = db.get_conn(str(dest))
    assert copy.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == 1


def test_backup_skips_empty_db(tmp_path):
    src = tmp_path / "empty.sqlite"
    db.init_db(db.get_conn(str(src)))
    assert backup.backup_db(src, tmp_path / "backups") is None


def test_backup_prunes_old(tmp_path):
    bdir = tmp_path / "backups"
    bdir.mkdir()
    (bdir / "expenses_2026-01-01_000000.sqlite").write_text("x")
    (bdir / "expenses_2026-01-02_000000.sqlite").write_text("x")
    src = tmp_path / "expenses.sqlite"
    _seed(src)
    backup.backup_db(src, bdir, keep=2)
    files = sorted(bdir.glob("expenses_*.sqlite"))
    assert len(files) == 2
    assert files[-1].name.startswith("expenses_2026-01-02") is False
