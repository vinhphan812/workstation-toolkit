import sqlite3
from pathlib import Path
import workstation.modules.kanban as kanban

def test_kanban_health_reads_board_without_mutation(tmp_path, monkeypatch):
    board = tmp_path / 'boards' / 'demo'
    board.mkdir(parents=True)
    db = board / 'kanban.db'
    conn = sqlite3.connect(db)
    conn.execute('create table tasks(id text, title text, status text, completed_at integer)')
    conn.execute("insert into tasks values('1', 'done', 'done', 1)")
    conn.commit(); conn.close()
    monkeypatch.setattr(kanban, '_boards_root', lambda: tmp_path / 'boards')
    report = kanban.kanban_health()
    assert report['boards'][0]['name'] == 'demo'
    assert report['boards'][0]['statuses']['done'] == 1
