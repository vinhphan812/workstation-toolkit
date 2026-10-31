import json
import os
import sqlite3
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from workstation.modules.kanban import archive_tasks


def _seed_archive(tmp_path: Path, task_id: str = "existing"):
    board = tmp_path / "board"
    board.mkdir()
    db = board / "kanban.db"
    now = int(time.time())
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, body TEXT, status TEXT, created_at INTEGER, updated_at INTEGER, completed_at INTEGER, metadata TEXT)")
    completed = now - 40 * 86400
    conn.execute("INSERT INTO tasks VALUES (?, ?, '', 'done', ?, ?, ?, '{}')", (task_id, "live-title", now-90*86400, completed, completed))
    conn.commit()
    conn.close()
    archive_dir = board / "archive" / time.strftime("%Y-%m", time.gmtime(completed))
    archive_dir.mkdir(parents=True)
    archive = archive_dir / f"{task_id}.json"
    return board, db, archive


def _task_count(db: Path, task_id="existing"):
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT count(*) FROM tasks WHERE id=?", (task_id,)).fetchone()[0]


def test_existing_archive_collision_preserves_archive_and_live_task(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(tmp_path))
    board, db, archive = _seed_archive(tmp_path)
    previous = b'{"id":"existing","title":"previous archive"}\n'
    archive.write_bytes(previous)

    result = archive_tasks(30, board="board", execute=True, yes=True)

    assert archive.read_bytes() == previous
    assert _task_count(db) == 1
    assert result["archived_count"] == 0
    assert result["skipped_count"] == 1


def test_archive_symlink_collision_refuses_write_and_keeps_task(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(tmp_path))
    board, db, archive = _seed_archive(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text("keep me", encoding="utf-8")
    try:
        archive.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")

    result = archive_tasks(30, board="board", execute=True, yes=True)

    assert result["skipped_count"] == 1
    assert outside.read_text(encoding="utf-8") == "keep me"
    assert _task_count(db) == 1


def test_archive_write_failure_keeps_task_and_cleans_tempfile(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(tmp_path))
    board, db, archive = _seed_archive(tmp_path)
    real_link = os.link
    def fail_publish(src, dst, *args, **kwargs):
        raise OSError("injected publication failure")
    monkeypatch.setattr(os, "link", fail_publish)

    with pytest.raises(OSError, match="injected"):
        archive_tasks(30, board="board", execute=True, yes=True)

    assert _task_count(db) == 1
    assert not archive.exists()
    assert not list(archive.parent.glob(".*.tmp"))


def test_archive_published_and_then_task_removed(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(tmp_path))
    board, db, archive = _seed_archive(tmp_path)

    result = archive_tasks(30, board="board", execute=True, yes=True)

    published = Path(result["results"][0]["archived_to"])
    assert json.loads(published.read_text(encoding="utf-8"))["id"] == "existing"
    assert _task_count(db) == 0
    assert not list(published.parent.glob(".*.tmp"))


def test_concurrent_destination_creation_never_overwrites_or_deletes_task(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(tmp_path))
    board, db, archive = _seed_archive(tmp_path)
    raced_bytes = b'{"id":"existing","title":"raced"}'
    real_link = os.link
    def win_race(src, dst, *args, **kwargs):
        Path(dst).write_bytes(raced_bytes)
        return real_link(src, dst, *args, **kwargs)

    with patch("workstation.modules.kanban.os.link", side_effect=win_race):
        with pytest.raises(FileExistsError):
            archive_tasks(30, board="board", execute=True, yes=True)

    assert archive.read_bytes() == raced_bytes
    assert _task_count(db) == 1
