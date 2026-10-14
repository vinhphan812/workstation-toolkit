import sqlite3
from unittest.mock import patch
from workstation.modules.hermes import _check_integrity

def test_sqlite_integrity_check(tmp_path):
    db = tmp_path / "state.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE test(id INTEGER)")
    conn.commit()
    conn.close()
    assert _check_integrity(str(db)) == "ok"
