from workstation.modules.loc import loc_audit

def test_loc_audit_excludes_generated_and_counts_source(tmp_path):
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src' / 'main.py').write_text('# title\n\nprint("ok")\n')
    (tmp_path / 'node_modules').mkdir()
    (tmp_path / 'node_modules' / 'ignore.js').write_text('x\n' * 100)
    report = loc_audit(str(tmp_path))
    assert report['ok']
    assert report['files'] == 1
    assert report['total']['total'] == 3
    assert report['total']['code'] == 1
    assert report['total']['blank'] == 1
    assert report['total']['comment'] == 1
