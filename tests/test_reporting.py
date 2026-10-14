import json
from pathlib import Path
import workstation.core.reporting as reporting

def test_write_report_writes_json_and_markdown(tmp_path, monkeypatch):
    monkeypatch.setattr(reporting, 'REPORTS_DIR', tmp_path)
    paths = reporting.write_report('unit', {'value': 1})
    assert Path(paths['json']).is_file()
    assert Path(paths['markdown']).is_file()
    assert json.loads(Path(paths['json']).read_text())['value'] == 1
